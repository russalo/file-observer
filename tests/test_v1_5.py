"""v1.5.0 — PDF specialist head+tail read + requires_vision fix (falsify-first).

The PDF specialist read only the 8 KB head, so page_count/producer (which live in
the trailer at the file END) were null for ~all real PDFs, and detect_requires_vision
mis-flagged born-digital PDFs whose content streams are compressed (no plaintext
BT/Font in the head) as needing vision. v1.5 reads head + a bounded tail.

These cases are written to FAIL on the v1.4 head-only code: the key fixtures put
the metadata ONLY in the tail (after >8 KB of marker-free filler). Synthetic byte
PDFs — no external libs, CI-safe.
"""
from pathlib import Path


from file_observer.scanner import (
    Scanner, ScannerConfig, LOGIC_VERSION, SCHEMA_VERSION,
)

HEAD = 8192
FILLER = b"%" + b" marker-free filler line\n" * 600   # ~15 KB, no PDF markers


def _sc():
    return Scanner(Path("."), ScannerConfig())


def _write(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p, data[:HEAD]


# born-digital, everything in the head
BORN_SMALL = (
    b"%PDF-1.7\n"
    b"1 0 obj <</Type/Catalog/Pages 2 0 R>> endobj\n"
    b"2 0 obj <</Type/Pages/Kids[3 0 R]/Count 12>> endobj\n"
    b"3 0 obj <</Type/Page/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>> endobj\n"
    b"4 0 obj <</Type/Font/Subtype/Type1/BaseFont/Helvetica>> endobj\n"
    b"5 0 obj <</Length 40>> stream\nBT /F1 12 Tf (Standard Spec) Tj ET\nendstream endobj\n"
    b"trailer <</Root 1 0 R/Info 6 0 R>>\n"
    b"6 0 obj <</Producer(Adobe PDF Library 15.0)/Title(City Standard Details)>> endobj\n"
    b"%%EOF\n"
)

# born-digital, but the head is >8 KB of marker-free filler; ALL markers in the TAIL.
# This is the case the head-only v1.4 code fails (the real-corpus pattern).
BORN_TAIL = (
    b"%PDF-1.6\n" + FILLER +
    b"\n2 0 obj <</Type/Pages/Kids[3 0 R]/Count 487>> endobj\n"
    b"4 0 obj <</Type/Font/Subtype/Type1>> endobj\n"
    b"5 0 obj << >> stream\nBT (born digital text) Tj ET\nendstream endobj\n"
    b"trailer <</Root 1 0 R/Info 6 0 R>>\n"
    b"6 0 obj <</Producer(TeX Live poppler)/Title(State DOT Standard Specifications)>> endobj\n"
    b"%%EOF\n"
)

# scanned / image-only: image XObjects, NO /Font or BT anywhere.
SCANNED = (
    b"%PDF-1.4\n" + FILLER +
    b"\n2 0 obj <</Type/Pages/Kids[3 0 R]/Count 3>> endobj\n"
    b"4 0 obj <</Type/XObject/Subtype/Image/Filter/DCTDecode/Width 1700/Height 2200>> "
    b"stream\n\xff\xd8\xff\xe0JFIFscanned-bytes\xff\xd9\nendstream endobj\n"
    b"trailer <</Root 1 0 R/Info 6 0 R>>\n"
    b"6 0 obj <</Producer(HP Digital Sending Device)>> endobj\n"
    b"%%EOF\n"
)

# residual: no plaintext markers anywhere (simulates PDF 1.5+ object-stream
# compression of xref/Info/Font) — page_count null, vision conservative.
OPAQUE = b"%PDF-1.5\n" + FILLER + FILLER + b"\n%%EOF\n"


class TestVersionSurfaces:
    def test_schema_invariant(self):
        # v1.5's stable invariant — provisional pdf.text_detected exists from
        # schema 1.4 on, and PDF requires_vision routing landed at LOGIC 1.4.0.
        # (Global versions move each release; exact values pinned in test_packaging.
        # Tuple compare — string ">=" breaks at 1.10.)
        assert tuple(int(x) for x in SCHEMA_VERSION.split(".")) >= (1, 4)
        assert tuple(int(x) for x in LOGIC_VERSION.split(".")) >= (1, 4, 0)


class TestMetadataFromTail:
    def test_small_born_digital(self, tmp_path):
        p, head = _write(tmp_path, "small.pdf", BORN_SMALL)
        m = _sc()._extract_pdf_metadata(p, head, 131072)
        assert m["page_count"] == 12
        assert m["producer"] == "Adobe PDF Library 15.0"
        assert m["title"] == "City Standard Details"
        assert m["text_detected"] is True

    def test_metadata_only_in_tail(self, tmp_path):
        # THE falsify case: head is >8 KB marker-free filler; metadata only in tail.
        p, head = _write(tmp_path, "tail.pdf", BORN_TAIL)
        assert b"/Count" not in head and b"/Producer" not in head  # head truly empty
        m = _sc()._extract_pdf_metadata(p, head, 131072)
        assert m["page_count"] == 487           # read from the tail
        assert m["producer"] == "TeX Live poppler"
        assert m["text_detected"] is True

    def test_page_count_is_root_max(self, tmp_path):
        # multiple /Count present (intermediate page-tree nodes) → take the max (root total)
        data = (b"%PDF-1.7\n2 0 obj<</Type/Pages/Count 200>>endobj\n"
                b"7 0 obj<</Type/Pages/Count 50>>endobj\n"
                b"4 0 obj<</Font<</F1 1 0 R>>>>endobj\nBT x ET\ntrailer<</Info 6 0 R>>\n"
                b"6 0 obj<</Producer(x)>>endobj\n%%EOF")
        p, head = _write(tmp_path, "multi.pdf", data)
        assert _sc()._extract_pdf_metadata(p, head, 131072)["page_count"] == 200

    def test_hex_string_producer(self, tmp_path):
        data = (b"%PDF-1.7\n2 0 obj<</Type/Pages/Count 5>>endobj\n/Font x\nBT y ET\n"
                b"trailer<</Info 6 0 R>>\n6 0 obj<</Producer<41646F6265>>>>endobj\n%%EOF")
        p, head = _write(tmp_path, "hex.pdf", data)
        m = _sc()._extract_pdf_metadata(p, head, 131072)
        assert m["producer"] == "Adobe"   # hex <41646F6265> decoded


class TestRequiresVision:
    def _vision(self, tmp_path, name, data):
        p, head = _write(tmp_path, name, data)
        v, prov = _sc().detect_requires_vision(p, head, "application/pdf", ".pdf", True)
        return v

    def test_born_digital_tail_not_vision(self, tmp_path):
        # the 310-false-positive class: text PDF, markers only in tail → NOT vision
        assert self._vision(tmp_path, "bd.pdf", BORN_TAIL) is False

    def test_scanned_is_vision(self, tmp_path):
        # image-only, no /Font/BT → vision
        assert self._vision(tmp_path, "scan.pdf", SCANNED) is True

    def test_small_born_digital_not_vision(self, tmp_path):
        assert self._vision(tmp_path, "sm.pdf", BORN_SMALL) is False

    def test_image_mime_always_vision(self, tmp_path):
        p, head = _write(tmp_path, "x.png", b"\x89PNG\r\n\x1a\n")
        v, _ = _sc().detect_requires_vision(p, head, "image/png", ".png", True)
        assert v is True


class TestReviewFixes:
    """In-house review (2026-06-02): correctness bugs in the first v1.5 cut."""

    def test_outlines_count_not_page_count(self, tmp_path):
        # /Count is not unique to /Pages — /Outlines (bookmarks) use it too. A
        # 10-page PDF with 240 bookmarks must report page_count 10, not 240.
        data = (b"%PDF-1.7\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 10>>endobj\n"
                b"9 0 obj<</Type/Outlines/Count 240>>endobj\n/Font x\nBT y ET\n"
                b"trailer<</Root 1 0 R>>\n%%EOF")
        p, head = _write(tmp_path, "bm.pdf", data)
        assert _sc()._extract_pdf_metadata(p, head, 131072)["page_count"] == 10

    def test_escaped_paren_title(self, tmp_path):
        data = (b"%PDF-1.7\n2 0 obj<</Type/Pages/Count 3>>endobj\n/Font\nBT\n"
                b"6 0 obj<</Title(Annual Report \\(final\\) 2026)>>endobj\n%%EOF")
        p, head = _write(tmp_path, "esc.pdf", data)
        assert _sc()._extract_pdf_metadata(p, head, 131072)["title"] == "Annual Report (final) 2026"

    def test_root_count_in_unread_middle(self, tmp_path):
        # root /Pages /Count sits beyond the 8KB head and before the 128KB tail —
        # the whole-file read (specialist) must still find it (not undercount/null).
        data = (b"%PDF-1.6\n" + b"x" * 9000 +
                b"\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 350>>endobj\n" +
                b"y" * 200000 + b"\n/Font\nBT\ntrailer<</Root 1 0 R>>\n%%EOF")
        p, head = _write(tmp_path, "big.pdf", data)
        assert _sc()._extract_pdf_metadata(p, head, 131072)["page_count"] == 350

    def test_pdf_version_leading_bom(self, tmp_path):
        data = (b"\xef\xbb\xbf   %PDF-1.7\n/Font\nBT\n"
                b"2 0 obj<</Type/Pages/Count 2>>endobj\n%%EOF")
        p, head = _write(tmp_path, "bom.pdf", data)
        assert _sc()._extract_pdf_metadata(p, head, 131072)["pdf_version"] == "1.7"

    def test_encrypted_info_not_garbage(self, tmp_path):
        # encrypted PDFs encrypt /Info strings — don't emit ciphertext as producer.
        data = (b"%PDF-1.6\n/Encrypt 5 0 R\n2 0 obj<</Type/Pages/Count 4>>endobj\n"
                b"6 0 obj<</Producer(\x01\x9f\xc3garbage)>>endobj\n%%EOF")
        p, head = _write(tmp_path, "enc.pdf", data)
        m = _sc()._extract_pdf_metadata(p, head, 131072)
        assert m["encrypted"] is True
        assert m["producer"] is None

    def test_flat_page_tree_big_kids(self, tmp_path):
        # Gemini: a flat page tree's /Kids array pushes /Count far past /Type/Pages;
        # the page-count search must follow the enclosing dict, not a fixed window.
        kids = b" ".join(f"{i} 0 R".encode() for i in range(3, 103))  # ~800 bytes
        data = (b"%PDF-1.7\n2 0 obj<</Type/Pages/Kids[" + kids +
                b"]/Count 100>>endobj\n/Font\nBT\ntrailer<</Root 1 0 R>>\n%%EOF")
        p, head = _write(tmp_path, "flat.pdf", data)
        assert _sc()._extract_pdf_metadata(p, head, 131072)["page_count"] == 100

    def test_nested_dict_in_pages_object(self, tmp_path):
        # Gemini/Codex: a nested /Resources<<…>> in the /Pages object made the
        # first `>>` close the wrong dict; page-count search must span to `endobj`.
        data = (b"%PDF-1.7\n2 0 obj<</Type/Pages/Resources<</Font<</F1 4 0 R>>>>"
                b"/Kids[3 0 R]/Count 88>>endobj\n/Font\nBT\n%%EOF")
        p, head = _write(tmp_path, "nested.pdf", data)
        assert _sc()._extract_pdf_metadata(p, head, 131072)["page_count"] == 88

    def test_balanced_parens_title(self, tmp_path):
        # Codex: balanced UNESCAPED inner parens in a literal string.
        data = (b"%PDF-1.7\n2 0 obj<</Type/Pages/Count 3>>endobj\n/Font\nBT\n"
                b"6 0 obj<</Title(Report (v2) Final)>>endobj\n%%EOF")
        p, head = _write(tmp_path, "bal.pdf", data)
        assert _sc()._extract_pdf_metadata(p, head, 131072)["title"] == "Report (v2) Final"

    def test_odd_length_hex_string(self, tmp_path):
        # Gemini: ISO 32000 §7.3.4.3 — odd-length hex pads a trailing 0.
        data = (b"%PDF-1.7\n2 0 obj<</Type/Pages/Count 1>>endobj\n/Font\nBT\n"
                b"6 0 obj<</Producer<41646F62655>>endobj\n%%EOF")  # 'Adobe' + odd nibble
        p, head = _write(tmp_path, "oddhex.pdf", data)
        prod = _sc()._extract_pdf_metadata(p, head, 131072)["producer"]
        assert prod is not None and prod.startswith("Adobe")

    def test_jbig2_scan_is_vision(self, tmp_path):
        data = (b"%PDF-1.5\n2 0 obj<</Type/Pages/Count 1>>endobj\n"
                b"4 0 obj<</Subtype/Image/Filter/JBIG2Decode>>stream\n\x00\nendstream endobj\n%%EOF")
        p, head = _write(tmp_path, "jb.pdf", data)
        v, _ = _sc().detect_requires_vision(p, head, "application/pdf", ".pdf", True)
        assert v is True


class TestDocumentedResidual:
    def test_object_stream_opaque(self, tmp_path):
        # no plaintext markers (simulated object-stream compression): metadata null;
        # requires_vision stays conservative (no text AND no image markers → not vision,
        # erring away from false 'needs vision' on an unreadable-but-likely-text PDF).
        p, head = _write(tmp_path, "opaque.pdf", OPAQUE)
        m = _sc()._extract_pdf_metadata(p, head, 131072)
        assert m["page_count"] is None
        assert m["producer"] is None
        assert m["text_detected"] is False
