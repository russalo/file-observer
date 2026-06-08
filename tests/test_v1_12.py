"""v1.12.0 — post-v1.5 PDF arc residual closure (falsify-first).

Two residuals closed:
  (A) Owner-permission-locked encrypted PDFs. The v1.11 dispatch had a
      `not meta["encrypted"]` gate that skipped the cascade. pypdf itself
      handles empty-password decrypt via `reader.decrypt("")`. v1.12 relaxes
      the gate and surfaces a new `extraction_permission_bypassed` value in
      `FileRecord.safety_flags` (the cross-format disclosure surface) when
      the primary EXTRACT permission (ISO 32000 bit 5) was not set in
      `user_access_permissions` but metadata was extracted anyway. No SCHEMA
      bump — safety_flags is already a stable list[str] field since v0.7.
  (B) Uncompressed xref-stream PDFs. `_pdf_xref_stream_map` previously called
      `_safe_inflate(body)` unconditionally; the no-filter case (42 PDFs on
      corpora_infra) now uses the raw body, with the v1.8.1 bounded-observation
      discipline preserved (aggregate `total_raw >= PDF_INFLATE_CAP` cap +
      `/Length`-bounded `_pdf_stream_body`).

The leg-1 in-house swarm review identified 15 findings; this test module
encodes the falsification for each fix. The critical bugs were:
  - Wrong permission bit checked (#15, EXTRACT_TEXT_AND_GRAPHICS bit 10 →
    primary EXTRACT bit 5).
  - page_count overwrite without null guard (#2/#7) — encrypted classic-xref
    PDFs would have their v1.7-anchor page_count silently overwritten by
    pypdf's `len(reader.pages)`, breaking the byte-identical contract.
  - cryptography not in ScanContext.dependencies (#3/#8) — Pillar-1 violation;
    same install can produce different manifests based on crypto presence.
  - No oracle parity gate on the no-filter xref-stream path (#9).
  - Strict `>` rather than `>=` on PDF_INFLATE_CAP cap (#10) — 64MB no-filter
    body slipped on first iteration.
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    SCHEMA_VERSION,
)

pypdf = pytest.importorskip("pypdf")
# v1.12 fixtures: AES-256 encrypt requires the cryptography package; without it,
# pypdf raises DependencyError during fixture construction. importorskip cleanly
# (leg-1 review #13) instead of FAIL-as-regression.
pytest.importorskip("cryptography")
from pypdf.constants import UserAccessPermissions  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _encrypted_pdf(extract_allowed: bool, user_password: str = "") -> bytes:
    """AES-256 encrypted PDF with the primary EXTRACT bit (ISO 32000 bit 5,
    pypdf `UserAccessPermissions.EXTRACT = 16`) set or cleared.

    Caltrans-2025 shape: empty user password, owner password set, AES-256.
    """
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
        algorithm="AES-256",
    )
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _uncompressed_xref_pdf(npages: int = 3) -> bytes:
    """A minimal PDF with an UNCOMPRESSED xref stream (no /Filter)."""
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
    out += b"%d 0 obj\n<< /Type /XRef /W [1 2 1] /Size %d /Root 1 0 R /Length %d >>\nstream\n" % (
        xnum, size, len(xref_raw),
    )
    out += xref_raw + b"\nendstream\nendobj\n"
    startxref = offs[xnum]
    out += b"startxref\n%d\n%%%%EOF" % startxref
    return bytes(out)


def _xref_pdf_with_explicit_filter(filter_name: bytes, npages: int = 3) -> bytes:
    """An xref STREAM whose dict declares `/Filter /<filter_name>` (e.g. `/None`
    or `/Identity` — both legal PDF declarations of NO compression). The body is
    raw entry bytes per /W. v1.12 PR #55 leg-4 Gemini review: the original v1.12
    `/Filter not in d` substring check failed on these; the round-3 fix matches
    explicitly for compression filter names."""
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
    out += (
        b"%d 0 obj\n<< /Type /XRef /W [1 2 1] /Filter /%s "
        b"/Size %d /Root 1 0 R /Length %d >>\nstream\n"
        % (xnum, filter_name, size, len(xref_raw))
    )
    out += xref_raw + b"\nendstream\nendobj\n"
    out += b"startxref\n%d\n%%%%EOF" % offs[xnum]
    return bytes(out)


def _uncompressed_xref_with_filter_in_title() -> bytes:
    """v1.12 leg-1 review #14: a PDF whose xref-stream dict has NO `/Filter` key
    but contains the substring `/Filter` inside a /Title or similar string value.
    The substring check `b"/Filter" not in d` would mis-classify this; the
    key-presence regex `re.search(rb"/Filter\\s*[/\\[]", d)` must not match."""
    # We can't easily put a /Title inside an xref-stream dict in a clean way that
    # pypdf accepts, so we directly construct an xref-stream dict with a literal-
    # string Producer containing the substring "/Filter". The xref-stream itself
    # has no compression filter, so the v1.12 patched path MUST take the
    # raw-body branch.
    page_count = 2
    page_nums = [3, 4]
    kids = b"[" + b" ".join(b"%d 0 R" % n for n in page_nums) + b"]"
    objs: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids %s /Count %d >>" % (kids, page_count)),
        (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"),
        (4, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"),
    ]
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offs: dict[int, int] = {}
    for num, b in objs:
        offs[num] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (num, b)
    xnum = 5
    offs[xnum] = len(out)
    size = xnum + 1

    def e(t: int, a: int, b: int) -> bytes:
        return struct.pack(">B", t) + struct.pack(">H", a) + struct.pack(">B", b)

    rows = {0: e(0, 0, 0), xnum: e(1, offs[xnum], 0)}
    for o, _ in objs:
        rows[o] = e(1, offs[o], 0)
    xref_raw = b"".join(rows[i] for i in range(size))
    # The xref-stream dict carries a /Producer with a literal string containing
    # the substring `/Filter` — a v1.11-substring check would false-positive.
    out += (
        b"%d 0 obj\n<< /Type /XRef /W [1 2 1] /Size %d /Root 1 0 R "
        b"/Producer (Generated by tool that documents /Filter usage) "
        b"/Length %d >>\nstream\n" % (xnum, size, len(xref_raw))
    )
    out += xref_raw + b"\nendstream\nendobj\n"
    out += b"startxref\n%d\n%%%%EOF" % offs[xnum]
    return bytes(out)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _scan_one(path: Path):
    cfg = ScannerConfig(enable_specialists=True)
    s = Scanner(source_dir=path.parent, config=cfg)
    m = s.scan()
    for rec in m.files:
        if rec.path == path.name:
            return rec
    raise AssertionError(f"file {path.name} not found in manifest")


# ---------------------------------------------------------------------------
# (A) Owner-permission-locked encrypted PDFs — disclosure via safety_flags
# ---------------------------------------------------------------------------

class TestEncryptedDecode:
    def test_encrypted_extract_allowed_recovers_metadata(self, tmp_path):
        """Empty-user-pw AES-256 PDF with EXTRACT permitted (Caltrans shape):
        recover page_count + producer; no `extraction_permission_bypassed` flag."""
        data = _encrypted_pdf(extract_allowed=True)
        p = _write(tmp_path, "extract_allowed.pdf", data)
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["page_count"] == 2, f"expected 2 pages, got {pdf.get('page_count')!r}"
        assert pdf["encrypted"] is True
        assert pdf.get("parser") == "pypdf"
        # Disclosure is on safety_flags now, NOT a pdf-namespaced bool (leg-1 #12)
        assert "permission_flags_bypassed" not in pdf, (
            "v1.12: the pdf.permission_flags_bypassed field was REMOVED — promoted to safety_flags"
        )
        assert "extraction_permission_bypassed" not in rec.safety_flags, (
            f"extract permitted; safety flag should be absent; got {rec.safety_flags!r}"
        )

    def test_encrypted_extract_denied_recovers_with_safety_flag(self, tmp_path):
        """Empty-user-pw AES-256 PDF with primary EXTRACT bit (bit 5) cleared:
        observe-with-disclosure — metadata recovered AND
        `extraction_permission_bypassed` appears in safety_flags."""
        data = _encrypted_pdf(extract_allowed=False)
        p = _write(tmp_path, "extract_denied.pdf", data)
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["page_count"] == 2
        assert pdf["encrypted"] is True
        assert pdf.get("parser") == "pypdf"
        assert "extraction_permission_bypassed" in rec.safety_flags, (
            f"extract denied but we extracted; flag missing; safety_flags={rec.safety_flags!r}"
        )
        # Field must NOT appear in the pdf namespace (leg-1 #12)
        assert "permission_flags_bypassed" not in pdf

    def test_real_password_pdf_does_not_bypass(self, tmp_path):
        """PDF requiring a real (non-empty) user password — MUST NOT prompt;
        cascade returns None cleanly; no bypass disclosure (we never got in)."""
        data = _encrypted_pdf(extract_allowed=True, user_password="not-empty-pwd")
        p = _write(tmp_path, "real_password.pdf", data)
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["encrypted"] is True
        assert pdf.get("producer") is None, (
            f"real-password PDF: producer should be null; got {pdf.get('producer')!r}"
        )
        assert pdf.get("parser") in (None, "none")
        assert "extraction_permission_bypassed" not in rec.safety_flags

    def test_unencrypted_pdf_no_bypass_flag(self, tmp_path):
        """Sanity: an unencrypted PDF never gets the bypass disclosure."""
        p = _write(tmp_path, "plain.pdf", _uncompressed_xref_pdf(npages=2))
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["encrypted"] is False
        assert "extraction_permission_bypassed" not in rec.safety_flags


# ---------------------------------------------------------------------------
# (B) Uncompressed xref streams
# ---------------------------------------------------------------------------

class TestUncompressedXrefStream:
    def test_uncompressed_xref_recovers_page_count(self, tmp_path):
        """An xref STREAM with no /Filter — v1.11 nulled via the Flate-only
        assumption; v1.12 recovers via the patched no-filter path."""
        data = _uncompressed_xref_pdf(npages=5)
        p = _write(tmp_path, "uncompressed_xref.pdf", data)
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["xref_type"] == "stream"
        assert pdf["page_count"] == 5

    def test_uncompressed_xref_oracle_parity_with_pypdf(self, tmp_path):
        """v1.12 leg-1 review #9: the no-filter xref-stream path MUST agree
        with pypdf, same as v1.8's Flate-path parity test."""
        for npages in (3, 7, 13):
            data = _uncompressed_xref_pdf(npages=npages)
            p = _write(tmp_path, f"oracle_{npages}.pdf", data)

            with open(p, "rb") as fh:
                reader = pypdf.PdfReader(fh, strict=False)
                pypdf_pages = len(reader.pages)
            assert pypdf_pages == npages

            scanner = Scanner(source_dir=p.parent, config=ScannerConfig(enable_specialists=True))
            stdlib_result = scanner._pdf_via_stdlib(p, whole=data)
            assert stdlib_result is not None, f"stdlib failed on uncompressed-xref n={npages}"
            assert stdlib_result["page_count"] == pypdf_pages, (
                f"oracle disagreement n={npages}: stdlib={stdlib_result['page_count']!r} pypdf={pypdf_pages!r}"
            )

    def test_filter_explicit_none_recovers(self, tmp_path):
        """PR #55 leg-4 Gemini review: a PDF declaring `/Filter /None` (legal PDF
        syntax for "no compression") MUST recover via the raw-body path. v1.12
        original regex (`/Filter not in d`) would route it to inflate → fail → null."""
        data = _xref_pdf_with_explicit_filter(b"None", npages=4)
        p = _write(tmp_path, "filter_none.pdf", data)
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["page_count"] == 4, (
            f"/Filter /None should recover via raw-body path; got page_count={pdf.get('page_count')!r}"
        )

    def test_filter_explicit_identity_recovers(self, tmp_path):
        """PR #55 leg-4: same shape with `/Filter /Identity` — another legal PDF
        no-op filter declaration."""
        data = _xref_pdf_with_explicit_filter(b"Identity", npages=6)
        p = _write(tmp_path, "filter_identity.pdf", data)
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["page_count"] == 6

    def test_filter_substring_in_dict_value_does_not_mis_classify(self, tmp_path):
        """v1.12 leg-1 review #14: a literal-string value containing the substring
        '/Filter' (with no actual /Filter KEY) must take the raw-body branch
        (`re.search(rb"/Filter\\s*[/\\[]", d)` is False — key-followed-by-/ or [)."""
        data = _uncompressed_xref_with_filter_in_title()
        p = _write(tmp_path, "filter_substring.pdf", data)
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        assert pdf["page_count"] == 2, (
            f"PDF with '/Filter' in a string value should still recover via no-filter path; got {pdf.get('page_count')!r}"
        )


# ---------------------------------------------------------------------------
# v1.12 contract: page_count NEVER overwritten by cascade on existing value
# ---------------------------------------------------------------------------

class TestPageCountNeverOverwritten:
    def test_anchor_page_count_preserved_through_cascade(self, tmp_path):
        """v1.12 leg-1 review #2/#7: an encrypted classic-xref PDF where the
        v1.7 anchor reads page_count from plaintext /Count MUST NOT have it
        overwritten when the v1.12 relaxed gate fires the cascade. The merge
        is strict null-fill for ALL fields, page_count included."""
        data = _encrypted_pdf(extract_allowed=True)
        p = _write(tmp_path, "encrypted_classic.pdf", data)
        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}
        # Both the v1.7 anchor and the cascade agree on 2 pages for this fixture
        # — the test asserts the recovered value is correct AND consistent.
        assert pdf["page_count"] == 2


# ---------------------------------------------------------------------------
# Capability-locked determinism: cryptography in ScanContext.dependencies
# ---------------------------------------------------------------------------

class TestScanContextDependencies:
    def test_cryptography_in_dependencies(self, tmp_path):
        """v1.12 leg-1 review #3/#8: pypdf needs cryptography for AES-256/V5
        decrypt; without it, manifest output diverges on encrypted PDFs.
        cryptography MUST be in ScanContext.dependencies for Pillar-1."""
        (tmp_path / "empty.txt").write_text("hello")
        cfg = ScannerConfig(enable_specialists=True)
        m = Scanner(source_dir=tmp_path, config=cfg).scan()
        deps = m.context.dependencies
        assert "cryptography" in deps, f"cryptography missing from deps: {list(deps.keys())}"
        # In this test env, cryptography IS available
        assert deps["cryptography"]["available"] is True


# ---------------------------------------------------------------------------
# v1.12 round-2 leg-1 #6 (+ Gemini leg-2 minor): the DependencyError path
# ---------------------------------------------------------------------------

class TestEncryptionUnsupportedPath:
    """Pin the cryptography-absent branch: pypdf raises DependencyError on AES
    decrypt → marker propagates → scan_file emits ERR_PDF_ENCRYPTION_UNSUPPORTED,
    `pdf.parser` is NOT mis-stamped to 'pypdf' (round-2 leg-1 #2-#10), and the
    aggregate quality counters reflect the failure (round-2 leg-1 #11/#12)."""

    def test_dependency_error_emits_error_record_and_counts(self, tmp_path, monkeypatch):
        from file_observer import scanner as scanner_mod
        from file_observer.scanner import ERR_PDF_ENCRYPTION_UNSUPPORTED

        # Build a real AES-256 encrypted PDF first (in this test env cryptography
        # IS present, so the fixture builder works). Then monkeypatch the live
        # `_pdf_via_pypdf` path so that on this scan, `reader.decrypt("")` raises
        # the pypdf DependencyError — simulating the cryptography-absent install.
        data = _encrypted_pdf(extract_allowed=False)
        p = _write(tmp_path, "encrypted_no_crypto.pdf", data)

        # Make decrypt() raise pypdf.errors.DependencyError when the cascade runs.
        DepErr = pypdf.errors.DependencyError
        orig_pdf_reader = pypdf.PdfReader

        class _BlockingReader(orig_pdf_reader):
            def decrypt(self, password):  # type: ignore[override]
                raise DepErr("cryptography>=3.1 is required for AES algorithm")

        monkeypatch.setattr(pypdf, "PdfReader", _BlockingReader)

        rec = _scan_one(p)
        pdf = (rec.specialist_metadata or {}).get("pdf") or {}

        # 1. ErrorRecord emitted with the correct code (round-2 leg-1 #6)
        codes = [e.code for e in (rec.errors or [])]
        assert ERR_PDF_ENCRYPTION_UNSUPPORTED in codes, (
            f"expected ERR_PDF_ENCRYPTION_UNSUPPORTED in errors; got {codes!r}"
        )
        # 2. Transient marker MUST NOT leak into the manifest (#3/#8 plumbing)
        assert "_pdf_encryption_unsupported" not in pdf
        # 3. The "parser" field MUST NOT be mis-stamped as 'pypdf' when pypdf
        #    recovered nothing (round-2 leg-1 #2/#3/#5/#7/#8/#10)
        assert pdf.get("parser") in (None, "none"), (
            f"parser mis-attributed: should not be 'pypdf' when pypdf raised "
            f"DependencyError and recovered no fields; got {pdf.get('parser')!r}"
        )

    def test_quality_specialist_failures_counts_pdf_encryption_unsupported(self, tmp_path, monkeypatch):
        """Round-2 leg-1 #11/#12: ERR_PDF_ENCRYPTION_UNSUPPORTED MUST be counted
        in ScanQuality.specialist_failures + per-directory failures + the
        specialist_stats[tool].failed bucket."""
        from file_observer.scanner import ERR_PDF_ENCRYPTION_UNSUPPORTED

        data = _encrypted_pdf(extract_allowed=False)
        p = _write(tmp_path, "encrypted.pdf", data)

        DepErr = pypdf.errors.DependencyError
        orig_pdf_reader = pypdf.PdfReader

        class _BlockingReader(orig_pdf_reader):
            def decrypt(self, password):  # type: ignore[override]
                raise DepErr("cryptography>=3.1 is required for AES algorithm")

        monkeypatch.setattr(pypdf, "PdfReader", _BlockingReader)

        cfg = ScannerConfig(enable_specialists=True)
        m = Scanner(source_dir=tmp_path, config=cfg).scan()

        # Top-level aggregate
        assert m.quality.specialist_failures >= 1, (
            f"specialist_failures should reflect the AES-decrypt failure; got {m.quality.specialist_failures}"
        )
        # specialist_stats[pdf_extraction].failed
        stats = m.quality.specialist_stats.get("pdf_extraction") or {}
        assert stats.get("failed", 0) >= 1, (
            f"specialist_stats[pdf_extraction].failed should reflect the AES-decrypt failure; got {stats!r}"
        )
        # per-directory aggregate
        per_dir = m.quality.per_directory_summary
        total_dir_failures = sum(d.get("specialist_failures", 0) for d in per_dir)
        assert total_dir_failures >= 1, (
            f"per-directory specialist_failures should reflect the AES-decrypt failure; got {per_dir!r}"
        )


# ---------------------------------------------------------------------------
# Version bumps
# ---------------------------------------------------------------------------

class TestVersionBumps:
    def test_scanner_version_is_1_12_x(self):
        # v1.12.1 patch bumps to 1.12.1; pin to the 1.12.x line rather than the
        # exact patch (test_v1_12_1.py owns the exact patch-version pin).
        assert SCANNER_VERSION.startswith("1.12."), f"got {SCANNER_VERSION!r}"

    def test_schema_version_unchanged_at_1_8(self):
        """v1.12 promotes the disclosure to safety_flags (existing stable list[str])
        rather than adding a new pdf-namespaced bool — no SCHEMA bump (leg-1 #12)."""
        assert SCHEMA_VERSION == "1.8", f"got {SCHEMA_VERSION!r}"


# ---------------------------------------------------------------------------
# Corpus invariants (skipped unless corpus is available)
# ---------------------------------------------------------------------------

CORPUS = Path("/srv/projects/pkplab/scanner-corpora/corpora_infra")


@pytest.mark.skipif(not CORPUS.exists(), reason="corpora_infra not available")
class TestCorpusInvariants:
    def test_caltrans_owner_locked_pdfs_recover(self):
        """The 2 Caltrans owner-locked PDFs recover producer + page_count.
        The corrected EXTRACT bit (#15 fix) revealed that Caltrans has bit 5
        (primary EXTRACT) CLEARED while bit 10 (the deprecated accessibility
        override) is set — i.e. they're exactly the bypass-disclosure case.
        v1.12 correctly surfaces `extraction_permission_bypassed` on them."""
        for name in (
            "T2_state_dot/Caltrans-2025/2025-standard-plans-errata-no1-locked-a11y.pdf",
            "T2_state_dot/Caltrans-2025/2025-standard-plans-locked.pdf",
        ):
            p = CORPUS / name
            if not p.exists():
                pytest.skip(f"missing corpus file: {name}")
            cfg = ScannerConfig(enable_specialists=True)
            s = Scanner(source_dir=p.parent, config=cfg)
            m = s.scan()
            rec = next((r for r in m.files if r.path == p.name), None)
            assert rec is not None
            pdf = (rec.specialist_metadata or {}).get("pdf") or {}
            assert pdf["encrypted"] is True
            assert pdf["page_count"] is not None, f"{name}: page_count still null"
            assert pdf["producer"] is not None, f"{name}: producer still null"
            # Caltrans has bit 5 (EXTRACT) CLEARED — bypass disclosure must fire
            assert "extraction_permission_bypassed" in rec.safety_flags, (
                f"{name}: bit 5 cleared but disclosure missing; safety_flags={rec.safety_flags!r}"
            )
            # And the legacy pdf-namespaced bool should NOT exist (promoted to safety_flags)
            assert "permission_flags_bypassed" not in pdf
