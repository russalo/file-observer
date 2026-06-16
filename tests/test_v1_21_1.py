"""v1.21.1 — PDF-header false-positive fix (HISTORY-only patch).

The find-anywhere `%PDF-` magic rule (offset None) matched the literal `%PDF-`
ANYWHERE in the first 8 KB, so source/text files that merely *contain* it deep in
the file (.java/.py/.md/.xls — measured at offset >=864) were misclassified
`application/pdf` in `format_signatures` and the no-libmagic `_sniff_mime` tier.
v1.21.1 bounds the rule to the first `PDF_HEADER_MAX_OFFSET` (256) bytes via the
`_Within` sentinel. Measured on the corpus: 1015/1015 real PDFs preserved (max real
header offset 174), FPs 10->2 (the 2 offset-29 `.tsd` residuals are undecidable by
bytes — a %PDF-1.x at byte 29 is indistinguishable from a PDF with 29 leading junk
bytes — and accepted). Surfaced by puresniff's FP sweep.
"""
from __future__ import annotations

from pathlib import Path

from file_observer.scanner import (
    Scanner, ScannerConfig, PDF_HEADER_MAX_OFFSET,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)


def test_release_version_surfaces():
    def _v(x): return tuple(int(p) for p in x.split("."))
    assert _v(SCANNER_VERSION) >= (1, 21, 1), f"SCANNER: {SCANNER_VERSION!r}"
    assert _v(LOGIC_VERSION) >= (1, 11, 1), f"LOGIC: {LOGIC_VERSION!r}"      # MIME-tier change
    assert _v(SCHEMA_VERSION) >= (1, 13), f"SCHEMA: {SCHEMA_VERSION!r}"       # unchanged


def _sc():
    return Scanner(source_dir=Path("."), config=ScannerConfig())


class TestRealPdfPreserved:
    """Bounded window must not lose a single real PDF (max corpus offset = 174)."""

    def test_offset_zero(self):
        assert _sc()._sniff_mime(b"%PDF-1.7\n1 0 obj") == "application/pdf"

    def test_offset_within_window_leading_junk(self):
        # real PDFs tolerate leading whitespace/BOM/junk (corpus tail to offset 174)
        for off in (1, 8, 28, 174, PDF_HEADER_MAX_OFFSET):
            head = b"\x00" * off + b"%PDF-1.4"
            assert _sc()._sniff_mime(head) == "application/pdf", f"lost a PDF at offset {off}"


class TestDeepLiteralRejected:
    """A literal %PDF- beyond the window is no longer application/pdf (the FP class)."""

    def test_sniff_rejects_deep_literal(self):
        head = b"x" * 900 + b"%PDF-1.4"          # the >=864 FP population
        assert _sc()._sniff_mime(head) is None

    def test_format_signatures_drops_deep_pdf(self):
        # a .java-like file with %PDF- deep in it emits NO application/pdf signature
        head = b"// source\n" + b"y" * 900 + b'String s = "%PDF-1.4";\n'
        _file_sig, sigs, is_poly = _sc().scan_signatures(head)
        assert "application/pdf" not in [s["format"] for s in sigs]

    def test_boundary_just_past_window(self):
        # offset 257 (one past the window) must be rejected; 256 accepted
        assert _sc()._sniff_mime(b"z" * (PDF_HEADER_MAX_OFFSET + 1) + b"%PDF-1.4") is None
        assert _sc()._sniff_mime(b"z" * PDF_HEADER_MAX_OFFSET + b"%PDF-1.4") == "application/pdf"


class TestAcceptedResidual:
    """An early literal (offset < window) stays application/pdf — undecidable by bytes."""

    def test_early_literal_still_matches(self):
        # the offset-29 .tsd residual: indistinguishable from a PDF with 29 leading bytes
        assert _sc()._sniff_mime(b"q" * 29 + b"%PDF-1.4") == "application/pdf"


class TestDeterminism:
    def test_workers_byte_identical(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        (tmp_path / "b.java").write_bytes(b"y" * 900 + b'"%PDF-1.4"')
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig()).scan()
        m4 = Scanner(source_dir=tmp_path, config=ScannerConfig(workers=4)).scan()
        assert m1.manifest_checksum == m4.manifest_checksum
