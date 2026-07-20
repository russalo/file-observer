"""v1.23.1 — PDF-header FP fix via the C1/C2 split (falsify-first).

The find-anywhere `%PDF-` magic rule (loose since v1.3, surfaced by puresniff's clean-room
sweep) typed any file containing `%PDF-` *anywhere* in its first 8 KB as `application/pdf`.
Fix (Option C): bound `%PDF-` to a 256-byte header window in the MIME sniff (C1, `_sniff_mime`)
via the `_Within` sentinel — a stray deep literal no longer types `application/pdf` — while
`scan_signatures` (C2) keeps find-anywhere so a real embedded PDF still registers its
`format_signature` and `is_polyglot` stays honest. Sharpen the MIME judgment WITHOUT
suppressing the polyglot observation.

LOGIC 1.12.1→1.12.2 (MIME-sniff routing change); SCANNER 1.23.0→1.23.1; SCHEMA unchanged 1.14.
"""
from __future__ import annotations


from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
)


def _sc(tmp_path):
    return Scanner(source_dir=tmp_path, config=ScannerConfig())


def test_version_surfaces():
    # floors — v1.23.2+ supersede this release (widened the window to 1024 + added corroboration)
    assert tuple(map(int, SCANNER_VERSION.split("."))) >= (1, 23, 1), f"got {SCANNER_VERSION!r}"
    assert tuple(map(int, LOGIC_VERSION.split("."))) >= (1, 12, 2), f"LOGIC: {LOGIC_VERSION!r}"
    assert tuple(map(int, SCHEMA_VERSION.split("."))) >= (1, 14), SCHEMA_VERSION  # floor (superseded per-release pin; later minors raise SCHEMA)


def test_deep_stray_pdf_literal_not_typed_pdf(tmp_path):
    # C1 FP fix: a `%PDF-` deep in a source/text file must NOT type it application/pdf.
    sample = b"// a source file\n" + b"x" * 900 + b"%PDF-1.4 mentioned in a string literal\n"
    # v1.23.2: this literal now falls inside the widened 1024-byte window but is rejected for
    # lacking PDF structure (corroboration) — either way, not pdf.
    assert not any(t in sample for t in (b" 0 obj", b"endobj", b"/Type", b"xref", b"trailer", b"%%EOF"))
    assert _sc(tmp_path)._sniff_mime(sample) != "application/pdf", \
        "a structureless stray %PDF- must not be typed application/pdf"


def test_deep_pdf_literal_still_in_format_signatures(tmp_path):
    # C2 preserved: the same deep `%PDF-` MUST still register (find-anywhere) so polyglot stays honest.
    sample = b"// a source file\n" + b"x" * 900 + b"%PDF-1.4\n"
    _, sigs, _ = _sc(tmp_path).scan_signatures(sample)
    assert any(s["format"] == "application/pdf" for s in sigs), \
        "C2 (format_signatures) must keep find-anywhere — a deep PDF literal still registers"


def test_real_pdf_at_head_still_sniffed(tmp_path):
    sample = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n"
    assert _sc(tmp_path)._sniff_mime(sample) == "application/pdf"


def test_pdf_with_small_leading_offset_still_sniffed(tmp_path):
    # real PDFs tolerate a few leading bytes (BOM/whitespace/junk) before %PDF- — within the window
    sample = b"\xef\xbb\xbf" + b" " * 100 + b"%PDF-1.5\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"   # offset 103, with structure
    assert _sc(tmp_path)._sniff_mime(sample) == "application/pdf"


def test_polyglot_observation_preserved(tmp_path):
    # a PNG head + a real embedded PDF deep in the body → is_polyglot stays True (C2 finds both),
    # and the MIME sniff picks the head signature (PNG), not the deep PDF.
    sample = b"\x89PNG\r\n\x1a\n" + b"\x00" * 900 + b"%PDF-1.4\n"
    sc = _sc(tmp_path)
    _, sigs, is_poly = sc.scan_signatures(sample)
    fmts = {s["format"] for s in sigs}
    assert "image/png" in fmts and "application/pdf" in fmts
    assert is_poly is True, "a deep-embedded PDF must keep is_polyglot honest (C2 find-anywhere)"
    assert sc._sniff_mime(sample) == "image/png"
