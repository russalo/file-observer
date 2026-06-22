"""v1.23.2 — corroborated PDF-header MIME sniff (falsify-first).

v1.23.1 bounded `%PDF-` to a 256-byte MIME-sniff window. But 256 is narrower than the scanner's
OWN 1024-byte PDF-header tolerance (`_extract_pdf_metadata` reads `sample[:1024]`), so a real PDF
with a junk/BOM prefix at offset 257–1024 was wrongly dropped on the no-libmagic path (Codex P2 on
the v1.23.1 PR). Offset alone can't separate that from a deep literal (the corpus FP `.py` sits at
offset 864, inside 1024). v1.23.2 widens the window to 1024 AND requires a corroborating
PDF-structure token (`PDF_STRUCTURE_TOKENS`) for the MIME judgment (C1, `_sniff_mime`) — so a
junk-prefixed real PDF is typed while a deep literal with no structure is still rejected.
`scan_signatures` (C2, `enforce_window=False`) stays pure find-anywhere so embedded-PDF polyglots
still register (corroboration is C1-only).

SCANNER 1.23.1→1.23.2; LOGIC 1.12.2→1.12.3; SCHEMA unchanged 1.14.
"""
from __future__ import annotations

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    PDF_HEADER_MAX_OFFSET,
    PDF_STRUCTURE_TOKENS,
)


def _sc(tmp_path):
    return Scanner(source_dir=tmp_path, config=ScannerConfig())


# a minimal but structurally-real PDF head: header + one object carrying /Type + endobj
_PDF_BODY = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"


def test_version_surfaces():
    assert SCANNER_VERSION == "1.23.2", SCANNER_VERSION
    assert LOGIC_VERSION == "1.12.3", LOGIC_VERSION   # MIME-sniff routing change
    assert SCHEMA_VERSION == "1.14", SCHEMA_VERSION    # unchanged
    assert PDF_HEADER_MAX_OFFSET == 1024               # widened from 256 to match sample[:1024]


def test_prefixed_real_pdf_within_1024_now_sniffed(tmp_path):
    # junk/BOM prefix beyond the OLD 256 window but within 1024, then a REAL PDF (has structure).
    sample = b"\xef\xbb\xbf" + b" " * 300 + _PDF_BODY  # %PDF- at offset 303
    assert 256 < sample.find(b"%PDF-") <= 1024
    # WIDENING is load-bearing: pre-v1.23.2 the 256 window returned None here.
    assert _sc(tmp_path)._sniff_mime(sample) == "application/pdf"


def test_deep_literal_without_structure_still_rejected(tmp_path):
    # a `.py`-style file: %PDF- deep (now INSIDE the widened 1024 window) but NO PDF structure.
    sample = b"// a source file\n" + b"x" * 840 + b'f.write(b"%PDF-1.7\\n")\nmore = 1\n'
    pos = sample.find(b"%PDF-")
    assert 256 < pos <= 1024                                  # inside the widened window
    assert not any(t in sample for t in PDF_STRUCTURE_TOKENS)  # no PDF structure present
    # CORROBORATION is load-bearing: widening alone (without it) would WRONGLY type this as pdf.
    assert _sc(tmp_path)._sniff_mime(sample) != "application/pdf"


def test_real_pdf_at_head_still_sniffed(tmp_path):
    assert _sc(tmp_path)._sniff_mime(_PDF_BODY) == "application/pdf"   # regression guard


def test_corroboration_is_c1_only_polyglot_preserved(tmp_path):
    # PNG head + a deep `%PDF-` literal with NO structure. C1 (_sniff_mime) → image/png (head wins);
    # C2 (scan_signatures, find-anywhere, NO corroboration) STILL registers the pdf signature.
    sample = b"\x89PNG\r\n\x1a\n" + b"\x00" * 900 + b"%PDF-1.4\n"
    sc = _sc(tmp_path)
    _, sigs, is_poly = sc.scan_signatures(sample)
    fmts = {s["format"] for s in sigs}
    assert "image/png" in fmts and "application/pdf" in fmts   # C2 find-anywhere, corroboration skipped
    assert is_poly is True
    assert sc._sniff_mime(sample) == "image/png"               # C1: png head wins; deep-no-structure pdf not chosen


def test_embedded_real_pdf_in_polyglot_registers(tmp_path):
    # a real embedded PDF deep in a polyglot (with structure) → C2 registers it; is_polyglot honest.
    sample = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500 + _PDF_BODY
    _, sigs, is_poly = _sc(tmp_path).scan_signatures(sample)
    assert {"image/png", "application/pdf"} <= {s["format"] for s in sigs}
    assert is_poly is True


def test_anchored_signature_beats_windowed_pdf(tmp_path):
    # leg-4 Codex P2 on PR #92: a real GIF89a (offset-0 anchor) carrying an embedded PDF body
    # inside the widened 1024-byte window must sniff as image/gif, NOT application/pdf — the
    # anchored header wins over the windowed `%PDF-`. (Pre-fix this returned application/pdf;
    # in v1.23.1 it fell past the 256 window and matched GIF.)
    sample = b"GIF89a" + b"\x00" * 291 + _PDF_BODY     # GIF89a@0; %PDF- at offset 297, with structure
    sc = _sc(tmp_path)
    assert sc._sniff_mime(sample) == "image/gif"
    # ...and the embedded PDF is still recorded as a polyglot (C2 find-anywhere, anchored-first is C1-only).
    _, sigs, is_poly = sc.scan_signatures(sample)
    assert {"image/gif", "application/pdf"} <= {s["format"] for s in sigs}
    assert is_poly is True
