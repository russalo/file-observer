"""v1.12.0 — post-v1.5 PDF arc residual closure (falsify-first).

Two residuals closed:
  (A) Owner-permission-locked encrypted PDFs: the v1.11 dispatch had a
      `not meta["encrypted"]` gate that skipped the cascade entirely; pypdf
      itself already handles empty-password decrypt. v1.12 relaxes the gate
      and surfaces `pdf.permission_flags_bypassed: bool` (provisional,
      SCHEMA 1.8 → 1.9).
  (B) Uncompressed xref-stream PDFs: the stdlib decoder's `_pdf_stream_body`
      assumed Flate compression. PDFs that emit `/Filter`-absent xref streams
      (42 on corpora_infra; e.g. WSDOT standard plans) nulled page_count.
      v1.12 adds the no-filter path to `_pdf_xref_stream_map`.

The original §3.3 framing (PNG predictor extension) was data-pivoted on
2026-06-07: `scratch/measure_predictor_gap.py` returned 0 predictor-gap PDFs
on corpora_infra. The actual residuals are uncompressed-xref, not exotic-
predictor. Falsify-first did its job. See v1.12 RFC §3.3 + §6.1.
"""
from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    SCHEMA_VERSION,
)

pypdf = pytest.importorskip("pypdf")
from pypdf.constants import UserAccessPermissions  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _encrypted_pdf(extract_allowed: bool, user_password: str = "") -> bytes:
    """AES-256 encrypted PDF with the EXTRACT bit set or cleared.

    Caltrans-2025 shape: empty user password, owner password set, AES-256.
    When `extract_allowed=False`, the EXTRACT_TEXT_AND_GRAPHICS bit is cleared
    — the consumer scenario for `permission_flags_bypassed=true`.
    """
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.add_blank_page(width=200, height=200)
    perms = (
        UserAccessPermissions.PRINT | UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS
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
    """A minimal PDF with an UNCOMPRESSED xref stream (no /Filter) — the v1.8
    stdlib decoder skipped these (Flate-only). Page tree is regular objects;
    the xref stream's body is the raw entry bytes per the /W widths.

    Built from the v1.8 fixture skeleton, simplified: the page tree is NOT
    in an /ObjStm (so v1.7's anchor reader can still produce a value via
    classic mechanisms — but we craft the file with ONLY an xref-stream
    trailer to force the cascade through `_pdf_xref_stream_map`).
    """
    # Catalog + Pages + N Page objects, then an xref STREAM with no /Filter.
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
        # /W [1 2 1] — type 1 byte, offset 2 bytes, gen/index 1 byte
        return struct.pack(">B", t) + struct.pack(">H", a) + struct.pack(">B", b)

    rows = {
        0: e(0, 0, 0),
        xnum: e(1, offs[xnum], 0),
    }
    for o, _ in objs:
        rows[o] = e(1, offs[o], 0)
    xref_raw = b"".join(rows[i] for i in range(size))
    # NO /Filter — raw uncompressed bytes
    out += b"%d 0 obj\n<< /Type /XRef /W [1 2 1] /Size %d /Root 1 0 R /Length %d >>\nstream\n" % (
        xnum, size, len(xref_raw),
    )
    out += xref_raw + b"\nendstream\nendobj\n"
    startxref = offs[xnum]
    out += b"startxref\n%d\n%%%%EOF" % startxref
    return bytes(out)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _scan_one(path: Path) -> dict:
    cfg = ScannerConfig(enable_specialists=True)
    s = Scanner(source_dir=path.parent, config=cfg)
    m = s.scan()
    for rec in m.files:
        if rec.path == path.name:
            return (rec.specialist_metadata or {}).get("pdf") or {}
    raise AssertionError(f"file {path.name} not found in manifest")


# ---------------------------------------------------------------------------
# (A) Owner-permission-locked encrypted PDFs
# ---------------------------------------------------------------------------

class TestEncryptedDecode:
    def test_encrypted_extract_allowed_recovers_metadata(self, tmp_path):
        """An empty-user-password AES-256 PDF with EXTRACT permitted — Caltrans
        shape. Should recover page_count + producer; permission_flags_bypassed=False."""
        data = _encrypted_pdf(extract_allowed=True)
        p = _write(tmp_path, "extract_allowed.pdf", data)
        pdf = _scan_one(p)
        assert pdf["page_count"] == 2, f"expected 2 pages, got {pdf.get('page_count')!r}"
        assert pdf["encrypted"] is True
        assert pdf.get("permission_flags_bypassed") is False, (
            f"extract was permitted; bypass should be false; got {pdf.get('permission_flags_bypassed')!r}"
        )
        assert pdf.get("parser") == "pypdf"

    def test_encrypted_extract_denied_recovers_with_bypass_flag(self, tmp_path):
        """An empty-user-password AES-256 PDF with EXTRACT denied. Observe-with-
        disclosure: metadata recovered AND permission_flags_bypassed=True."""
        data = _encrypted_pdf(extract_allowed=False)
        p = _write(tmp_path, "extract_denied.pdf", data)
        pdf = _scan_one(p)
        assert pdf["page_count"] == 2
        assert pdf["encrypted"] is True
        assert pdf.get("permission_flags_bypassed") is True, (
            f"extract denied but we extracted; bypass should be true; got {pdf.get('permission_flags_bypassed')!r}"
        )
        assert pdf.get("parser") == "pypdf"

    def test_real_password_pdf_nulls_cleanly(self, tmp_path):
        """A PDF requiring a real (non-empty) user password — we MUST NOT prompt;
        cascade returns None cleanly. (Classic-xref encrypted PDFs may still yield
        page_count from the v1.7 anchor — that's expected. The cascade's job here
        is to not crash, not to magically extract /Info that's truly encrypted.)"""
        data = _encrypted_pdf(extract_allowed=True, user_password="not-empty-pwd")
        p = _write(tmp_path, "real_password.pdf", data)
        pdf = _scan_one(p)
        assert pdf["encrypted"] is True
        # Producer is unrecoverable without the real password — cascade nulls clean.
        assert pdf.get("producer") is None, (
            f"real-password PDF: producer should be null; got {pdf.get('producer')!r}"
        )
        # parser='none' means pypdf's empty-password decrypt failed → short-circuited.
        assert pdf.get("parser") in (None, "none"), (
            f"expected parser=none on failed-decrypt; got {pdf.get('parser')!r}"
        )
        # Never set bypass=True on a PDF we couldn't decrypt.
        assert pdf.get("permission_flags_bypassed") is False

    def test_unencrypted_pdf_bypass_field_false(self, tmp_path):
        """Sanity: an unencrypted PDF should never have bypass=True."""
        p = _write(tmp_path, "plain.pdf", _uncompressed_xref_pdf(npages=2))
        pdf = _scan_one(p)
        assert pdf["encrypted"] is False
        # The field MUST be present (provisional) but always false for non-encrypted
        assert pdf.get("permission_flags_bypassed") is False


# ---------------------------------------------------------------------------
# (B) Uncompressed xref streams
# ---------------------------------------------------------------------------

class TestUncompressedXrefStream:
    def test_uncompressed_xref_recovers_page_count(self, tmp_path):
        """An xref STREAM with no /Filter — v1.11 nulls page_count via _pdf_xref_stream_map's
        Flate-only assumption; v1.12 recovers via the patched no-filter path. The recovery
        runs through the v1.7 structural anchor (which uses _pdf_xref_stream_map), so the
        cascade may not be needed — parser='none' with page_count populated is the win."""
        data = _uncompressed_xref_pdf(npages=5)
        p = _write(tmp_path, "uncompressed_xref.pdf", data)
        pdf = _scan_one(p)
        assert pdf["xref_type"] == "stream"
        assert pdf["page_count"] == 5, (
            f"uncompressed xref-stream should recover page_count=5; got {pdf.get('page_count')!r}"
        )

    def test_uncompressed_xref_oracle_parity_with_pypdf(self, tmp_path):
        """Stdlib path on uncompressed xref MUST agree with pypdf where pypdf gives
        a value. Same oracle gate as v1.8. Calls the instance method via Scanner()."""
        data = _uncompressed_xref_pdf(npages=7)
        p = _write(tmp_path, "uncompressed_xref_oracle.pdf", data)

        # pypdf truth
        with open(p, "rb") as fh:
            reader = pypdf.PdfReader(fh, strict=False)
            pypdf_pages = len(reader.pages)
        assert pypdf_pages == 7  # sanity on the fixture

        # Stdlib truth via the scanner (instance method)
        scanner = Scanner(source_dir=p.parent, config=ScannerConfig(enable_specialists=True))
        stdlib_result = scanner._pdf_via_stdlib(p, whole=data)
        assert stdlib_result is not None, "stdlib MUST recover uncompressed xref stream"
        assert stdlib_result["page_count"] == 7, (
            f"stdlib disagrees with pypdf on uncompressed xref: stdlib={stdlib_result['page_count']!r} pypdf={pypdf_pages!r}"
        )


# ---------------------------------------------------------------------------
# Version bumps (the cheap pin)
# ---------------------------------------------------------------------------

class TestVersionBumps:
    def test_scanner_version_is_1_12_0(self):
        assert SCANNER_VERSION == "1.12.0", f"SCANNER_VERSION should be 1.12.0, got {SCANNER_VERSION!r}"

    def test_schema_version_is_1_9(self):
        # Permission_flags_bypassed is a new provisional field → SCHEMA bump
        assert SCHEMA_VERSION == "1.9", f"SCHEMA_VERSION should be 1.9, got {SCHEMA_VERSION!r}"


# ---------------------------------------------------------------------------
# Corpus invariants (skipped unless corpus is available)
# ---------------------------------------------------------------------------

CORPUS = Path("/srv/projects/pkplab/scanner-corpora/corpora_infra")


@pytest.mark.skipif(not CORPUS.exists(), reason="corpora_infra not available")
class TestCorpusInvariants:
    def test_caltrans_owner_locked_pdfs_recover(self):
        """The 2 Caltrans owner-locked PDFs recover producer + page_count.
        Both have EXTRACT permitted, so permission_flags_bypassed=False."""
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
            # Caltrans PDFs have EXTRACT permitted; bypass should be false
            assert pdf.get("permission_flags_bypassed") is False
