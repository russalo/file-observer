"""v1.12.1 — red-team hardening (falsify-first).

Adversarial inputs targeting the NEW v1.12 code paths:
  Surface 1: encryption decode path (the relaxed cascade gate)
  Surface 2: uncompressed xref-stream path (raw-body branch + /None/Identity)
  Surface 3: cascade merge in _pdf_decode_compressed (signal-only stub handling)
  Surface 4: transient marker plumbing (_safety_extras, _pdf_encryption_unsupported)
  Surface 5: cryptography fallback (getattr lookup, _dep_err_match tuple)

Cross-cuts: v1.8.1 guards still hold; Pillar-1 determinism under hostile input.

Scope: scratch/v1_12_1_redteam_scope.md.

Precedent: v1.8.1 caught 6 findings across 26 vectors. Expect 3-7 v1.12-specific
findings + 0-2 pre-existing.
"""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    manifest_to_json,
)

pypdf = pytest.importorskip("pypdf")
pytest.importorskip("cryptography")
from pypdf.constants import UserAccessPermissions  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixture builders (extended from test_v1_12.py)
# ---------------------------------------------------------------------------

def _encrypted_pdf(extract_allowed: bool, user_password: str = "", *, algorithm: str = "AES-256") -> bytes:
    """AES-256 encrypted PDF by default; algorithm parameterizable for hostile shapes."""
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_blank_page(width=200, height=200)
    perms = (
        UserAccessPermissions.PRINT | UserAccessPermissions.EXTRACT
        if extract_allowed
        else UserAccessPermissions.PRINT
    )
    w.encrypt(
        user_password=user_password,
        owner_password="owner-secret",
        permissions_flag=perms,
        algorithm=algorithm,
    )
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _encrypted_pdf_all_perms_cleared(user_password: str = "") -> bytes:
    """Encrypted PDF with EVERY permission bit cleared (no print, no extract,
    no modify, no annotate, no fill, no anything). The extreme bypass case."""
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    # Permissions = 0 → all required bits remain set (R7/R8 are reserved-1) but
    # no GRANT bits set; bit 5 (EXTRACT) is cleared.
    w.encrypt(
        user_password=user_password,
        owner_password="owner-secret",
        permissions_flag=UserAccessPermissions(0),
        algorithm="AES-256",
    )
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _xref_pdf(filter_decl: bytes | None, *, predictor: int | None = None, npages: int = 3) -> bytes:
    """Build a minimal PDF with an xref STREAM. `filter_decl` controls /Filter:
    None → no /Filter key at all; b"/None" → explicit no-op; etc."""
    page_nums = list(range(3, 3 + npages))
    kids = b"[" + b" ".join(b"%d 0 R" % n for n in page_nums) + b"]"
    objs: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids %s /Count %d >>" % (kids, npages)),
    ]
    objs += [(n, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>") for n in page_nums]
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offs: dict[int, int] = {}
    for num, b in objs:
        offs[num] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (num, b)
    xnum = max(o for o, _ in objs) + 1
    offs[xnum] = len(out)
    size = xnum + 1

    def e(t: int, a: int, b: int) -> bytes:
        return struct.pack(">B", t) + struct.pack(">H", a) + struct.pack(">B", b)

    rows = {0: e(0, 0, 0), xnum: e(1, offs[xnum], 0)}
    for o, _ in objs:
        rows[o] = e(1, offs[o], 0)
    xref_raw = b"".join(rows[i] for i in range(size))
    filter_part = (b" /Filter " + filter_decl) if filter_decl is not None else b""
    pred_part = (b" /Predictor %d /Columns 4" % predictor) if predictor is not None else b""
    out += (
        b"%d 0 obj\n<< /Type /XRef /W [1 2 1]%s%s /Size %d /Root 1 0 R /Length %d >>\nstream\n"
        % (xnum, filter_part, pred_part, size, len(xref_raw))
    )
    out += xref_raw + b"\nendstream\nendobj\n"
    out += b"startxref\n%d\n%%%%EOF" % offs[xnum]
    return bytes(out)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _scan_one(path: Path, **cfg_kwargs):
    cfg = ScannerConfig(enable_specialists=True, **cfg_kwargs)
    s = Scanner(source_dir=path.parent, config=cfg)
    m = s.scan()
    for rec in m.files:
        if rec.path == path.name:
            return rec, m
    raise AssertionError(f"file {path.name} not found in manifest")


# ===========================================================================
# Surface 1 — Encryption decode path
# ===========================================================================

class TestEncryptionDecodeHardening:
    def test_S1_2_rc4_encrypted_pdf_nulls_cleanly(self, tmp_path):
        """v1.12.1 S1.2: encrypted PDF using RC4 (not AES) — pypdf either
        decrypts via the RC4 path (no cryptography needed) or raises a non-
        DependencyError. Either way: no crash, no leak."""
        data = _encrypted_pdf(extract_allowed=True, algorithm="RC4-128")
        p = _write(tmp_path, "rc4.pdf", data)
        rec, _ = _scan_one(p)
        # Never-crash: scan completed; PDF present in manifest
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["encrypted"] is True
        # RC4 doesn't trip the DependencyError path; pypdf decrypts cleanly.
        # If pypdf cascade ran, parser should be 'pypdf'; else 'none' is fine.
        assert pdf.get("parser") in ("pypdf", "none")

    def test_S1_4_all_permissions_cleared_extreme_bypass(self, tmp_path):
        """v1.12.1 S1.4: encrypted PDF with EVERY permission bit cleared
        (UserAccessPermissions(0)). The extreme bypass case — extraction MUST
        be disclosed via safety_flags."""
        data = _encrypted_pdf_all_perms_cleared()
        p = _write(tmp_path, "all_cleared.pdf", data)
        rec, _ = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["encrypted"] is True
        # Bit 5 (EXTRACT) is cleared → bypass disclosure must fire
        assert "extraction_permission_bypassed" in rec.safety_flags, (
            f"all bits cleared but bypass not disclosed; safety_flags={rec.safety_flags!r}"
        )

    def test_S1_5_user_access_permissions_returns_None(self, tmp_path, monkeypatch):
        """v1.12.1 S1.5: encrypted=True but user_access_permissions returns
        None (unusual reader state). The `is not None` guard must catch it;
        no crash, no false bypass disclosure."""
        data = _encrypted_pdf(extract_allowed=True)
        p = _write(tmp_path, "perms_none.pdf", data)

        orig = pypdf.PdfReader

        class _NonePerms(orig):
            @property
            def user_access_permissions(self):
                return None

        monkeypatch.setattr(pypdf, "PdfReader", _NonePerms)
        rec, _ = _scan_one(p)
        # No crash; no bypass disclosure (we never determined the permission state)
        assert "extraction_permission_bypassed" not in rec.safety_flags

    def test_S1_6_perms_object_lacks_contains(self, tmp_path, monkeypatch):
        """v1.12.1 S1.6: hostile pypdf state where user_access_permissions
        returns an object lacking __contains__. The `EXTRACT not in perms` check
        would raise TypeError; broad-Exception cascade must null cleanly."""
        data = _encrypted_pdf(extract_allowed=False)
        p = _write(tmp_path, "hostile_perms.pdf", data)

        class _NoContains:
            pass

        orig = pypdf.PdfReader

        class _HostileReader(orig):
            @property
            def user_access_permissions(self):
                return _NoContains()

        monkeypatch.setattr(pypdf, "PdfReader", _HostileReader)
        rec, _ = _scan_one(p)
        # Never-crash: scan completed
        # The TypeError on `EXTRACT not in perms` should be swallowed by the
        # final broad Exception clause in _pdf_via_pypdf's permission block.
        assert rec is not None


# ===========================================================================
# Surface 2 — Uncompressed xref-stream path
# ===========================================================================

class TestUncompressedXrefHardening:
    def test_S2_2_raw_body_with_predictor_declared(self, tmp_path):
        """v1.12.1 S2.2: /Filter /None (raw body) + /Predictor 12. The current
        code path: filter_match captures 'None' → raw=body → then predictor
        check runs and calls _png_predictor_undo on raw bytes. Verify what
        actually happens — does this corrupt the xref entries?"""
        data = _xref_pdf(filter_decl=b"/None", predictor=12, npages=3)
        p = _write(tmp_path, "raw_with_predictor.pdf", data)
        rec, _ = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        # FALSIFY: what does this report? If page_count is 3, the no-filter
        # + predictor combo currently works (or accidentally works). If it's
        # null or wrong, we have a finding.
        # PIN: never-crash, value must be either correct (3) or null — never wrong.
        pc = pdf.get("page_count")
        assert pc is None or pc == 3, (
            f"raw-body+predictor produced wrong page_count: {pc!r} (expected 3 or null)"
        )

    def test_S2_3_filter_array_with_none_first(self, tmp_path):
        """v1.12.1 S2.3: /Filter [/None] — array containing the no-op filter.
        Current regex captures the first identifier after [/. Verify behavior."""
        data = _xref_pdf(filter_decl=b"[/None]", npages=4)
        p = _write(tmp_path, "filter_array_none.pdf", data)
        rec, _ = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        # FALSIFY: does /Filter [/None] route to raw-body? Should — current
        # regex matches /Filter\s*[/\[]\s*/?([A-Za-z][A-Za-z0-9]*) — array
        # `[/None]` matches with /[ then captures "None".
        pc = pdf.get("page_count")
        assert pc is None or pc == 4, (
            f"array-filter with /None produced wrong page_count: {pc!r}"
        )

    def test_S2_4_whitespace_tolerance(self, tmp_path):
        """v1.12.1 S2.4: /Filter with absurd whitespace before the value name."""
        # Use the raw-PDF builder so we can inject arbitrary whitespace
        data = _xref_pdf(filter_decl=b"\t\n\r /None", npages=5)
        p = _write(tmp_path, "ws_filter.pdf", data)
        rec, _ = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        # Should still route to raw-body via the \s* in the regex
        pc = pdf.get("page_count")
        assert pc is None or pc == 5

    def test_S2_6_length_clipping_does_not_crash(self, tmp_path):
        """v1.12.1 S2.6: /Length declares 1 GB but actual stream is small.
        Python slice clips at file end; verify no crash and bounded behavior."""
        # Build a normal no-filter xref PDF, then manually inflate the /Length
        # field in the dict to a hostile value.
        data = bytearray(_xref_pdf(filter_decl=None, npages=3))
        # Replace the /Length value with a huge number
        import re
        new_data = re.sub(rb"/Length \d+", b"/Length 1000000000", bytes(data))
        p = _write(tmp_path, "huge_length.pdf", new_data)
        rec, _ = _scan_one(p)
        # Never-crash; never wrong value (3 or null)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        pc = pdf.get("page_count")
        assert pc is None or pc == 3


# ===========================================================================
# Surface 3 — Cascade merge in _pdf_decode_compressed
# ===========================================================================

class TestCascadeMergeHardening:
    def test_S3_2_bypass_only_then_stdlib_recovers(self, tmp_path, monkeypatch):
        """v1.12.1 S3.2: pypdf returns bypass-only stub (all data None,
        bypass=True). Round-2 #4 fix: stdlib should run and merge data fields
        while preserving bypass disclosure."""
        data = _encrypted_pdf(extract_allowed=False)
        p = _write(tmp_path, "bypass_then_stdlib.pdf", data)

        orig = pypdf.PdfReader

        class _ZeroPages(orig):
            @property
            def pages(self):
                # Simulate "decrypted but len(pages) raises"
                raise RuntimeError("hostile pages access")

            @property
            def metadata(self):
                return None

        monkeypatch.setattr(pypdf, "PdfReader", _ZeroPages)
        rec, _ = _scan_one(p)
        # The bypass disclosure must survive through to safety_flags
        assert "extraction_permission_bypassed" in rec.safety_flags, (
            f"bypass disclosure lost; safety_flags={rec.safety_flags!r}"
        )

    def test_S3_4_pypdf_page_count_zero_is_not_all_none(self, tmp_path, monkeypatch):
        """v1.12.1 S3.4: subtle — what if pypdf returns page_count=0 (a
        meaningful zero)? The `all(... is None for k in data_fields)` check
        must use `is None`, NOT truthiness. Otherwise 0 would be treated
        as "no data" and the merge falls through to stdlib, possibly
        overwriting a meaningful 0."""
        # Construct a non-encrypted PDF; force pypdf to return page_count=0.
        # (Scanner is already imported at module top — no local import needed.)
        data = _xref_pdf(filter_decl=None, npages=2)
        p = _write(tmp_path, "plain.pdf", data)

        # We test the cascade logic by direct method call rather than
        # monkeypatching pypdf — verify the all-None check is `is None`.
        with monkeypatch.context() as mp:
            def fake_pypdf(path, whole=None):
                return {"parser": "pypdf", "page_count": 0,
                        "title": None, "author": None, "producer": None,
                        "creator": None, "creation_date": None,
                        "permission_flags_bypassed": False}
            mp.setattr(Scanner, "_pdf_via_pypdf", staticmethod(fake_pypdf))
            scanner = Scanner(source_dir=p.parent, config=ScannerConfig(enable_specialists=True))
            result = scanner._pdf_decode_compressed(p, whole=data)
        # page_count=0 was set explicitly by (fake) pypdf — it MUST be preserved,
        # not treated as None / fallen-through to stdlib.
        assert result is not None
        assert result["page_count"] == 0, (
            f"page_count=0 was overwritten or lost: {result['page_count']!r} — "
            "the all-None check must use `is None`, not truthiness"
        )


# ===========================================================================
# Surface 4 — Transient marker plumbing
# ===========================================================================

class TestTransientMarkerPlumbing:
    def test_S4_3_pre_existing_safety_flag_plus_bypass(self, tmp_path):
        """v1.12.1 S4.3: a PDF with /JS (has_javascript) AND encryption + extract
        denied (extraction_permission_bypassed). Both must survive, list sorted.

        Inject /JS marker via a PDF comment (`%...\\n` is a valid PDF comment per
        ISO 32000 §7.2.4) inserted between the header and the body. The marker
        triggers `detect_safety_flags`'s sample-level `b"/JS" in sample` check
        without breaking PDF structure (pypdf still decrypts the body cleanly)."""
        enc_data = _encrypted_pdf(extract_allowed=False)
        # Find the end of the PDF header (`%PDF-1.x\n%\xe2\xe3...\n`) and inject
        # a `%/JS\n` comment immediately after — both are legal PDF comments.
        # The /JS substring is what detect_safety_flags samples for.
        nl1 = enc_data.find(b"\n")
        nl2 = enc_data.find(b"\n", nl1 + 1)  # past the binary-marker comment
        injected = enc_data[:nl2 + 1] + b"%/JS marker\n" + enc_data[nl2 + 1:]
        p = _write(tmp_path, "js_plus_encrypted.pdf", injected)
        rec, _ = _scan_one(p)
        # Both flags must be present; safety_flags must be sorted
        assert "has_javascript" in rec.safety_flags, (
            f"has_javascript missing; safety_flags={rec.safety_flags!r}"
        )
        assert "extraction_permission_bypassed" in rec.safety_flags, (
            f"bypass disclosure lost when has_javascript also fires; safety_flags={rec.safety_flags!r}"
        )
        assert rec.safety_flags == sorted(rec.safety_flags), (
            f"safety_flags not sorted: {rec.safety_flags!r}"
        )

    def test_S4_5_transient_keys_never_in_provenance_or_manifest(self, tmp_path):
        """v1.12.1 S4.5: the transient keys (_safety_extras, _pdf_encryption_unsupported)
        MUST be popped before signal_provenance is built and MUST never appear in
        the serialized manifest JSON. Verified via grep on the manifest output."""
        data = _encrypted_pdf(extract_allowed=False)
        p = _write(tmp_path, "marker_leak_check.pdf", data)
        rec, m = _scan_one(p)

        # Direct check on the record
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert "_safety_extras" not in pdf
        assert "_pdf_encryption_unsupported" not in pdf

        # Provenance must not have entries keyed on these transient names
        for prov_key in (rec.signal_provenance or {}).keys():
            assert "_safety_extras" not in prov_key, (
                f"transient key leaked into provenance: {prov_key!r}"
            )
            assert "_pdf_encryption_unsupported" not in prov_key, (
                f"transient key leaked into provenance: {prov_key!r}"
            )

        # Full manifest JSON round-trip — grep for the transient strings
        manifest_json = manifest_to_json(m)
        assert "_safety_extras" not in manifest_json, (
            "_safety_extras leaked into the serialized manifest"
        )
        assert "_pdf_encryption_unsupported" not in manifest_json, (
            "_pdf_encryption_unsupported leaked into the serialized manifest"
        )


# ===========================================================================
# Surface 5 — Cryptography fallback
# ===========================================================================

class TestCryptographyFallback:
    def test_S5_1_old_pypdf_without_dependency_error_class(self, tmp_path, monkeypatch):
        """v1.12.1 S5.1: simulate an old pypdf that lacks errors.DependencyError.
        The getattr lookup must return None; the except tuple `()` matches
        nothing; subsequent decrypt failure (non-DependencyError) falls through
        to the broad Exception handler → returns None → cascade to stdlib."""
        data = _encrypted_pdf(extract_allowed=True)
        p = _write(tmp_path, "old_pypdf.pdf", data)

        # Save and restore the real errors module
        real_errors = pypdf.errors
        try:
            # Remove DependencyError from pypdf.errors namespace
            class FakeErrors:
                pass

            for attr in dir(real_errors):
                if not attr.startswith("_") and attr != "DependencyError":
                    setattr(FakeErrors, attr, getattr(real_errors, attr))
            monkeypatch.setattr(pypdf, "errors", FakeErrors)

            # Force decrypt to raise a NON-DependencyError exception
            orig = pypdf.PdfReader

            class _BadDecrypt(orig):
                def decrypt(self, password):  # type: ignore[override]
                    raise RuntimeError("simulated non-DepErr failure")

            monkeypatch.setattr(pypdf, "PdfReader", _BadDecrypt)

            # Scan — must not crash; should null cleanly
            rec, _ = _scan_one(p)
            pdf = (rec.specialist_metadata or {}).get("pdf") or {}
            assert pdf["encrypted"] is True
            # parser should be 'none' (pypdf failed; stdlib couldn't decrypt either)
            assert pdf.get("parser") in (None, "none")
        finally:
            # monkeypatch.setattr handles restoration via undo
            pass

    def test_S5_3_weird_cryptography_version(self, tmp_path, monkeypatch):
        """v1.12.1 S5.3 + Codex P2: cryptography.__version__ is a bare object()
        whose `str(v)` yields the default repr "<object at 0x...>" — embedding
        a memory address. The fix MUST normalize this to "unknown" so manifest
        emission is (a) JSON-safe AND (b) deterministic across processes.
        Verifies both: no crash + stable "unknown" value (not the address-bearing
        repr)."""
        import cryptography

        # A bare object — its str() is "<object object at 0x...>" with a memory
        # address that varies across processes. This is the EXACT case Codex P2
        # flagged.
        monkeypatch.setattr(cryptography, "__version__", object())

        (tmp_path / "trivial.txt").write_text("hello")
        cfg = ScannerConfig(enable_specialists=True)
        m = Scanner(source_dir=tmp_path, config=cfg).scan()
        deps = m.context.dependencies
        assert "cryptography" in deps
        # JSON-safe (no crash on manifest serialization)
        json.dumps(deps)
        # Pillar-1: the version MUST be "unknown", NOT the address-bearing repr.
        # If we stored "<object object at 0x7f...>", `manifest_checksum` would
        # be non-deterministic across processes.
        cv = deps["cryptography"]["version"]
        assert cv == "unknown", (
            f"hostile-version coercion failed: got {cv!r} — address-bearing reprs "
            f"break Pillar-1 across processes; must normalize to 'unknown'"
        )


# ===========================================================================
# Cross-cut: v1.8.1 guards still hold under v1.12 paths
# ===========================================================================

class TestV1_8_1_GuardsHoldUnderV1_12:
    def test_C1_columns_attacker_controlled_under_no_filter(self, tmp_path):
        """v1.12.1 C.1: /Columns attacker-controlled — the v1.8.1 guard
        (`columns < 1 or columns > len(raw)`) applies inside _png_predictor_undo.
        The raw-body path with no /Predictor never calls undo; verify with
        /Predictor declared explicitly that the guard still fires."""
        # /Filter /None + /Predictor 12 + hostile /Columns
        data = bytearray(_xref_pdf(filter_decl=b"/None", predictor=12, npages=2))
        # Inflate /Columns to a hostile value (huge)
        import re
        new_data = re.sub(rb"/Columns \d+", b"/Columns 999999999", bytes(data))
        p = _write(tmp_path, "hostile_columns.pdf", new_data)
        rec, _ = _scan_one(p)
        # Never-crash; never wrong value (the guard nulls; v1.7 anchor still works)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        pc = pdf.get("page_count")
        # Either the anchor recovers via fallback (2), or it nulls — never crashes.
        assert pc in (None, 2)


# ===========================================================================
# Cross-cut: Determinism (Pillar 1)
# ===========================================================================

class TestRedTeamDeterminism:
    def test_D1_workers_equality_under_hostile_encrypted(self, tmp_path):
        """v1.12.1 D.1: workers=1 vs workers=N byte-identical on a directory
        of hostile encrypted PDFs."""
        for i, alg in enumerate(("AES-256", "AES-128", "RC4-128")):
            try:
                d = _encrypted_pdf(extract_allowed=(i % 2 == 0), algorithm=alg)
            except Exception:
                continue  # skip if algorithm unsupported
            _write(tmp_path, f"enc_{i}_{alg}.pdf", d)
        # Add the bypass case
        _write(tmp_path, "all_cleared.pdf", _encrypted_pdf_all_perms_cleared())

        cfg1 = ScannerConfig(enable_specialists=True, workers=1)
        cfg4 = ScannerConfig(enable_specialists=True, workers=4)
        m1 = Scanner(source_dir=tmp_path, config=cfg1).scan()
        m4 = Scanner(source_dir=tmp_path, config=cfg4).scan()
        assert m1.manifest_checksum == m4.manifest_checksum, (
            f"workers-equality violated under hostile encrypted: "
            f"workers=1 {m1.manifest_checksum} vs workers=4 {m4.manifest_checksum}"
        )

    def test_D2_two_consecutive_scans_byte_identical(self, tmp_path):
        """v1.12.1 D.2: scanning the same fixture twice produces identical
        manifest_checksum — no wall-clock drift in any new path (v1.8.2 lesson)."""
        data = _encrypted_pdf(extract_allowed=False)
        _write(tmp_path, "encrypted.pdf", data)
        cfg = ScannerConfig(enable_specialists=True)
        m1 = Scanner(source_dir=tmp_path, config=cfg).scan()
        m2 = Scanner(source_dir=tmp_path, config=cfg).scan()
        assert m1.manifest_checksum == m2.manifest_checksum, (
            f"non-determinism: scan 1 {m1.manifest_checksum} vs scan 2 {m2.manifest_checksum}"
        )

    def test_D3_scan_context_dependencies_json_roundtrip(self, tmp_path):
        """v1.12.1 D.3: ScanContext.dependencies must JSON-round-trip cleanly
        (including the new cryptography entry)."""
        (tmp_path / "t.txt").write_text("x")
        cfg = ScannerConfig(enable_specialists=True)
        m = Scanner(source_dir=tmp_path, config=cfg).scan()
        s = json.dumps(m.context.dependencies, sort_keys=True)
        back = json.loads(s)
        assert back == m.context.dependencies
        assert "cryptography" in back


# ===========================================================================
# Version bump check
# ===========================================================================

def test_v1_12_1_version_bump():
    """v1.12.1 shipped the red-team hardening on the 1.12.x line. Pin to the
    1.12.x line rather than the exact patch (later patches bump it; the exact
    current-version pin lives in test_packaging.py)."""
    assert SCANNER_VERSION.startswith("1.12."), f"got {SCANNER_VERSION!r}"
