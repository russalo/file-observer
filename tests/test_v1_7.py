"""v1.7.0 — structural-anchor reader (falsify-first).

Follow a container format's own index pointer to the exact region, instead of
reading a window and pattern-matching it. For PDF: startxref → latest trailer →
root catalog → page tree (parsing the classic xref table for object offsets,
following /Prev for incremental updates), and reading the xref-stream dict for
xref-stream PDFs. Pure specialist-extraction change → LOGIC unchanged (1.4.0).

These tests are written BEFORE the implementation and MUST fail against v1.5
(the lesson of v1.4/v1.5/v1.6: the builder's synthetic corpus omits the breaking
case, so build the breaking case first). The synthetic PDFs carry BYTE-ACCURATE
xref tables — the reader has to actually follow offsets, not regex-scan.
"""
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig, SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)

# 20-byte xref entries (10-digit offset, gen, type) — the classic format.
def _xref_in_use(off: int) -> bytes:
    return b"%010d 00000 n \n" % off

def _xref_free() -> bytes:
    return b"0000000000 65535 f \n"


def _classic(*, producer: bytes | None = b"TestProducer 1.0", count: int = 3,
             version: bytes = b"1.4", pad: int = 0) -> bytes:
    """A single-revision classic-xref PDF with a byte-accurate xref table.

    `pad` injects a comment block (valid PDF — `%`…EOL) after the header so the
    objects land at a high byte offset (used to push the page tree past the head
    sample + tail window, forcing the unread-middle scenario)."""
    objs: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count %d >>" % count),
        (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"),
    ]
    info_num = None
    if producer is not None:
        info_num = 4
        objs.append((4, b"<< /Producer (%s) /CreationDate (D:20200102030405) >>" % producer))
    out = bytearray(b"%PDF-" + version + b"\n%\xe2\xe3\xcf\xd3\n")
    if pad:
        out += b"%" + b"X" * pad + b"\n"   # comment filler — pushes object offsets out
    offsets: dict[int, int] = {}
    for num, body in objs:
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref_off = len(out)
    n = len(objs) + 1
    out += b"xref\n0 %d\n" % n + _xref_free()
    for num, _ in objs:
        out += _xref_in_use(offsets[num])
    trailer = b"<< /Size %d /Root 1 0 R" % n
    if info_num:
        trailer += b" /Info %d 0 R" % info_num
    trailer += b" >>"
    out += b"trailer\n" + trailer + b"\nstartxref\n%d\n%%%%EOF" % xref_off
    return bytes(out)


def _incremental(*, orig_count: int = 10, new_count: int = 3,
                 producer: bytes = b"Acme PDF 2.0") -> bytes:
    """A classic PDF then an incremental update that OVERRIDES the page tree to a
    SMALLER count (e.g. pages deleted). The superseded /Count is still physically
    in the file. v1.5's `max(/Count anchored to /Type /Pages)` returns the stale
    LARGER count; the structural reader follows the latest trailer to the root and
    returns the current (smaller) count."""
    base = _classic(producer=producer, count=orig_count)
    rev1_xref = int(base.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    out = bytearray(base)
    out += b"\n"
    obj2_off = len(out)
    out += b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count %d >>\nendobj\n" % new_count
    rev2_xref = len(out)
    # xref subsection: 1 entry starting at object 2 (the overridden page tree).
    out += b"xref\n2 1\n" + _xref_in_use(obj2_off)
    out += (b"trailer\n<< /Size 5 /Root 1 0 R /Info 4 0 R /Prev %d >>\n"
            b"startxref\n%d\n%%%%EOF" % (rev1_xref, rev2_xref))
    return bytes(out)


def _xref_stream(*, producer: bytes = b"ObjStream Producer 3.0", count: int = 7) -> bytes:
    """A PDF whose cross-reference section is an xref STREAM (PDF 1.5+). Content
    objects (catalog/pages/page/info) are regular objects here, so the reader can
    recover /Info (producer) and /Count by resolving the refs from the plaintext
    xref-stream dict. xref_type must be detected as 'stream'."""
    import zlib
    objs: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count %d >>" % count),
        (3, b"<< /Type /Page /Parent 2 0 R >>"),
        (4, b"<< /Producer (%s) >>" % producer),
    ]
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for num, body in objs:
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref_off = len(out)
    body = zlib.compress(b"\x01\x00\x00\x00")  # opaque compressed cross-ref data (v1.8 parses it)
    out += (b"5 0 obj\n<< /Type /XRef /Size 6 /Root 1 0 R /Info 4 0 R "
            b"/W [1 2 1] /Filter /FlateDecode /Length %d >>\nstream\n" % len(body))
    out += body + b"\nendstream\nendobj\n"
    out += b"startxref\n%d\n%%%%EOF" % xref_off
    return bytes(out)


def _scan_one(tmp_path, name: str, data: bytes):
    (tmp_path / name).write_bytes(data)
    cfg = ScannerConfig(enable_specialists=True)
    m = Scanner(source_dir=tmp_path, config=cfg).scan()
    return [f for f in m.files if f.path.endswith(name)][0]


def _pdf_meta(tmp_path, name, data):
    return _scan_one(tmp_path, name, data).specialist_metadata["pdf"]


def _sc():
    return Scanner(source_dir=Path("."), config=ScannerConfig(enable_specialists=True))


class TestVersions:
    def test_versions(self):
        assert SCANNER_VERSION == "1.7.0"
        assert LOGIC_VERSION == "1.4.0"      # UNCHANGED — index reads are extraction, not routing
        assert SCHEMA_VERSION == "1.6"


class TestClassicXref:
    def test_page_count_and_producer(self, tmp_path):
        meta = _pdf_meta(tmp_path, "a.pdf", _classic(count=3, producer=b"Acme 1.0"))
        assert meta["page_count"] == 3
        assert meta["producer"] == "Acme 1.0"

    def test_xref_type_classic(self, tmp_path):
        meta = _pdf_meta(tmp_path, "a.pdf", _classic())
        assert meta.get("xref_type") == "classic"


class TestIncrementalUpdate:
    """THE precision case: a stale, superseded /Count larger than the current root."""
    def test_root_count_wins_not_stale_max(self, tmp_path):
        meta = _pdf_meta(tmp_path, "a.pdf", _incremental(orig_count=10, new_count=3))
        # v1.5 returns 10 (max /Count over the whole file, incl. the superseded
        # fragment). The structural reader follows the latest trailer → root → 3.
        assert meta["page_count"] == 3
        assert meta["producer"] == "Acme PDF 2.0"


class TestXrefStream:
    def test_detected_and_info_recovered(self, tmp_path):
        meta = _pdf_meta(tmp_path, "a.pdf", _xref_stream(producer=b"XS Producer 3.0", count=7))
        assert meta.get("xref_type") == "stream"
        assert meta["producer"] == "XS Producer 3.0"   # /Info ref read from the plaintext xref-stream dict


class TestBrokenStartxref:
    def test_graceful_fallback_no_raise(self, tmp_path):
        # startxref points to a bogus offset → must NOT raise; falls back to the
        # v1.5 window scan, which still finds /Count and /Producer in this file.
        pdf = _classic(count=4, producer=b"Fallback 1.0")
        pdf = pdf.rsplit(b"startxref\n", 1)[0] + b"startxref\n999999\n%%EOF"
        meta = _pdf_meta(tmp_path, "a.pdf", pdf)
        assert meta["page_count"] == 4
        assert meta["producer"] == "Fallback 1.0"


class TestLinearizedTwoStartxref:
    def test_last_startxref_wins(self, tmp_path):
        # A linearized PDF references a first-page xref early and the main xref at
        # EOF; the reader must use the LAST startxref. Simulate with a decoy
        # `startxref 0` earlier in the body — the trailing one must win.
        pdf = _classic(count=5, producer=b"Linearized 1.0")
        decoy = b"\nstartxref\n0\n"  # earlier, bogus
        head, tail = pdf.split(b"%\xe2\xe3\xcf\xd3\n", 1)
        pdf2 = head + b"%\xe2\xe3\xcf\xd3\n" + decoy + tail
        meta = _pdf_meta(tmp_path, "a.pdf", pdf2)
        assert meta["page_count"] == 5


class TestStructuralAnchorInfra:
    """Review findings (in-house leg): the STRUCTURAL_ANCHORS table must actually
    drive dispatch (not be decorative), and the ≤cap path must read the file once
    (slice the whole-file bytes), not re-open per object."""

    def test_dispatch_is_keyed_off_the_table(self):
        from file_observer.scanner import STRUCTURAL_ANCHORS
        assert STRUCTURAL_ANCHORS["pdf"] == "trailer_pointer"
        sc = _sc()
        whole = _classic(count=3, producer=b"X 1.0")
        # "pdf" → trailer_pointer → the anchor reader resolves from `whole`.
        got = sc._read_structural_index(Path("/nonexistent"), b"", whole, "pdf")
        assert got is not None and got["xref_type"] == "classic" and got["page_count"] == 3
        # formats whose anchor kind has no reader here (eocd/fat) and unknown
        # formats route to nothing — the table is the contract.
        assert sc._read_structural_index(Path("/x"), b"", whole, "zip") is None
        assert sc._read_structural_index(Path("/x"), b"", whole, "bogus") is None

    def test_resolution_reads_no_file_when_whole_present(self):
        # The read-once fix: when the whole-file bytes are supplied, object
        # resolution must slice them and never touch the filesystem. A bogus path
        # that would raise on open still yields correct results → proves no I/O.
        sc = _sc()
        whole = _classic(count=9, producer=b"InMem 2.0")
        anchor = sc._pdf_anchor(Path("/definitely/not/a/real/path.pdf"), b"", whole)
        assert anchor is not None
        assert anchor["page_count"] == 9
        prod = sc._extract_pdf_string(anchor["info_region"], b"/Producer")
        assert prod == "InMem 2.0"


class TestIncrementalLatestWins:
    """Gemini review (leg 2): the regex-locate path (xref-stream / no offset map)
    must pick the LATEST object copy, and the anchored /Info must not fall back to a
    whole-file scan that resurfaces a superseded value."""

    def test_locate_picks_last_object_copy(self):
        sc = _sc()
        # Two copies of object 2 (incremental append) — the LATER /Count must win.
        whole = (b"%PDF-1.5\n2 0 obj<</Type/Pages/Count 1>>endobj\n"
                 b"%% ... later incremental update ...\n"
                 b"2 0 obj<</Type/Pages/Count 9>>endobj\n")
        region = sc._locate_regular_obj(whole, 2)
        assert sc._pdf_count_from_pages(region) == 9   # latest, not the stale 1

    def test_anchored_info_does_not_resurface_stale_field(self, tmp_path):
        # Byte-accurate classic incremental update: the SUPERSEDED /Info (obj 4 v1)
        # has /Author "Stale"; the LATEST /Info (obj 4 v2) drops it. The anchored
        # region is authoritative → author is None, NOT the stale value a whole-file
        # fallback scan would resurface (the dropped fallback).
        objs = [
            (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
            (2, b"<< /Type /Pages /Kids [3 0 R] /Count 2 >>"),
            (3, b"<< /Type /Page /Parent 2 0 R >>"),
            (4, b"<< /Author (Stale Author) /Producer (P 1.0) >>"),
        ]
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        off: dict[int, int] = {}
        for n, b in objs:
            off[n] = len(out)
            out += b"%d 0 obj\n" % n + b + b"\nendobj\n"
        x1 = len(out)
        out += b"xref\n0 5\n" + _xref_free()
        for n, _ in objs:
            out += _xref_in_use(off[n])
        out += b"trailer\n<< /Size 5 /Root 1 0 R /Info 4 0 R >>\nstartxref\n%d\n%%%%EOF" % x1
        out += b"\n"
        o4 = len(out)
        out += b"4 0 obj\n<< /Producer (P 2.0) >>\nendobj\n"   # override: no /Author
        x2 = len(out)
        out += b"xref\n4 1\n" + _xref_in_use(o4)
        out += (b"trailer\n<< /Size 5 /Root 1 0 R /Info 4 0 R /Prev %d >>\n"
                b"startxref\n%d\n%%%%EOF" % (x1, x2))
        meta = _pdf_meta(tmp_path, "a.pdf", bytes(out))
        assert meta["producer"] == "P 2.0"          # latest /Info
        assert meta["author"] is None               # NOT resurfaced from the stale /Info


class TestLargeBeyondCap:
    def test_anchor_seek_when_whole_file_read_skipped(self, tmp_path, monkeypatch):
        # Force the genuine unread-middle scenario: the page tree / Info sit PAST
        # the 8 KB head sample, the whole-file read is skipped (file > cap), and
        # the tail window is too small to reach them. v1.5 → null; the structural
        # reader follows startxref → xref offsets → seeks to the objects regardless.
        import file_observer.scanner as S
        monkeypatch.setattr(S, "PDF_FULL_READ_CAP", 1024)   # skip whole-file read
        monkeypatch.setattr(S, "PDF_MARKER_BUDGET", 256)     # tiny tail window
        # pad pushes the objects to offset ~9 KB — past the 8 KB head sample, and
        # well before the 256-byte tail (which holds only xref/trailer/startxref).
        pdf = _classic(count=6, producer=b"Big 1.0", pad=9000)
        assert len(pdf) > 8192 + 256                          # genuine unread middle
        meta = _pdf_meta(tmp_path, "a.pdf", pdf)
        assert meta["page_count"] == 6
        assert meta["producer"] == "Big 1.0"
