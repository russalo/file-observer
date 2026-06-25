"""v1.24.0 — office extraction (Candidate B, phase 1): OOXML presentations
(.pptx) + ODF text/sheet/presentation (.odt/.ods/.odp). Falsify-first.

Reuses the docx/xlsx ZIP+XML machinery. New `presentation` namespace
(slide_count/title/author/application); .odt feeds `document`, .ods feeds
`spreadsheet`. `requires_specialist_tool` flips False→True for these types
(routing change → LOGIC 1.12.4→1.13.0). SCANNER 1.23.3→1.24.0; SCHEMA 1.14→1.15.

Fixtures are built in-test (zip+xml) — no committed binaries (they'd rot).
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
)


# ---- fixture builders ----------------------------------------------------

def _write_zip(path: Path, entries: dict[str, bytes], mimetype: str | None = None) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        if mimetype is not None:  # ODF: mimetype entry first + STORED (spec)
            zf.writestr(zipfile.ZipInfo("mimetype"), mimetype, compress_type=zipfile.ZIP_STORED)
        for name, data in entries.items():
            zf.writestr(name, data)


def _pptx(path: Path, *, title="Q3 Deck", creator="Alice", app="Microsoft PowerPoint", slides=12) -> None:
    core = (
        '<?xml version="1.0"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title>{title}</dc:title><dc:creator>{creator}</dc:creator>'
        '</cp:coreProperties>'
    ).encode()
    appxml = (
        '<?xml version="1.0"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        f'<Application>{app}</Application><Slides>{slides}</Slides>'
        '</Properties>'
    ).encode()
    _write_zip(path, {
        "[Content_Types].xml": b'<?xml version="1.0"?><Types/>',
        "docProps/core.xml": core,
        "docProps/app.xml": appxml,
        "ppt/slides/slide1.xml": b"<p:sld/>",
        "ppt/slides/slide2.xml": b"<p:sld/>",
    })


_ODF_META = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
    ' xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"><office:meta>'
    '<dc:title>{title}</dc:title><dc:creator>{creator}</dc:creator>'
    '<meta:generator>{gen}</meta:generator>'
    '<meta:document-statistic meta:word-count="{wc}"/>'
    '</office:meta></office:document-meta>'
)


def _odt(path: Path, *, title="My Notes", creator="Bob", gen="LibreOffice/7.4", wc=250) -> None:
    meta = _ODF_META.format(title=title, creator=creator, gen=gen, wc=wc).encode()
    _write_zip(path, {"meta.xml": meta, "content.xml": b"<office:document-content/>"},
               mimetype="application/vnd.oasis.opendocument.text")


def _ods(path: Path, *, sheets=("Sheet1", "Data"), gen="LibreOffice/7.4") -> None:
    meta = _ODF_META.format(title="Book", creator="Carol", gen=gen, wc=0).encode()
    tables = "".join(f'<table:table table:name="{s}"/>' for s in sheets)
    content = (
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">'
        f'<office:body><office:spreadsheet>{tables}</office:spreadsheet></office:body>'
        '</office:document-content>'
    ).encode()
    _write_zip(path, {"meta.xml": meta, "content.xml": content},
               mimetype="application/vnd.oasis.opendocument.spreadsheet")


def _odp(path: Path, *, pages=3, gen="Impress/7.4") -> None:
    meta = _ODF_META.format(title="Pitch", creator="Dave", gen=gen, wc=0).encode()
    drawpages = "<draw:page/>" * pages
    content = (
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
        ' xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0">'
        f'<office:body><office:presentation>{drawpages}</office:presentation></office:body>'
        '</office:document-content>'
    ).encode()
    _write_zip(path, {"meta.xml": meta, "content.xml": content},
               mimetype="application/vnd.oasis.opendocument.presentation")


def _scan_one(d: Path):
    m = Scanner(source_dir=d, config=ScannerConfig(enable_specialists=True)).scan()
    return m.files[0]


# ---- tests ---------------------------------------------------------------

def test_pptx_presentation(tmp_path):
    _pptx(tmp_path / "deck.pptx")
    rec = _scan_one(tmp_path)
    assert rec.requires_specialist_tool is True
    p = rec.specialist_metadata["presentation"]
    assert p == {"slide_count": 12, "title": "Q3 Deck", "author": "Alice",
                 "application": "Microsoft PowerPoint"}


def test_pptx_slide_count_fallback_to_parts(tmp_path):
    # no <Slides> in app.xml → count ppt/slides/slideN.xml (2 here)
    p = tmp_path / "deck.pptx"
    _write_zip(p, {
        "[Content_Types].xml": b'<?xml version="1.0"?><Types/>',
        "ppt/slides/slide1.xml": b"<p:sld/>",
        "ppt/slides/slide2.xml": b"<p:sld/>",
    })
    rec = _scan_one(tmp_path)
    assert rec.specialist_metadata["presentation"]["slide_count"] == 2


def test_odp_presentation(tmp_path):
    _odp(tmp_path / "pitch.odp", pages=3)
    rec = _scan_one(tmp_path)
    p = rec.specialist_metadata["presentation"]
    assert p["slide_count"] == 3
    assert p["title"] == "Pitch" and p["author"] == "Dave"
    assert p["application"] == "Impress/7.4"


def test_odt_document(tmp_path):
    _odt(tmp_path / "notes.odt")
    rec = _scan_one(tmp_path)
    d = rec.specialist_metadata["document"]
    assert d["title"] == "My Notes" and d["author"] == "Bob"
    assert d["word_count"] == 250 and d["application"] == "LibreOffice/7.4"


def test_ods_spreadsheet(tmp_path):
    _ods(tmp_path / "book.ods", sheets=("Sheet1", "Data"))
    rec = _scan_one(tmp_path)
    s = rec.specialist_metadata["spreadsheet"]
    assert s["sheet_names"] == ["Sheet1", "Data"]
    assert s["format"] == "odf"
    assert s["application"] == "LibreOffice/7.4"


def test_requires_specialist_tool_flips(tmp_path):
    _pptx(tmp_path / "a.pptx"); _odt(tmp_path / "b.odt")
    _ods(tmp_path / "c.ods"); _odp(tmp_path / "d.odp")
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    for rec in m.files:
        assert rec.requires_specialist_tool is True, rec.path


def test_office_honest_null(tmp_path):
    # a valid zip with NO metadata parts → fields null, no crash, no fabricated value
    p = tmp_path / "bare.pptx"
    _write_zip(p, {"[Content_Types].xml": b'<?xml version="1.0"?><Types/>'})
    rec = _scan_one(tmp_path)
    pm = rec.specialist_metadata["presentation"]
    assert pm["title"] is None and pm["author"] is None and pm["application"] is None
    assert pm["slide_count"] == 0  # no <Slides>; counted 0 slide parts → honest 0 (not null)


def test_corrupt_office_never_crashes(tmp_path):
    # not a zip at all → specialist returns None, scan still completes (never-crash)
    (tmp_path / "broken.pptx").write_bytes(b"PK\x03\x04 not really a zip " + b"\x00" * 50)
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    assert len(m.files) == 1
    sm = m.files[0].specialist_metadata
    assert sm is None or sm.get("presentation") is None  # never-crash: no fabricated metadata


def test_determinism(tmp_path):
    _pptx(tmp_path / "deck.pptx"); _odt(tmp_path / "n.odt")
    a = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    b = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    assert a.manifest_checksum == b.manifest_checksum


def test_version_surfaces(tmp_path):
    # falsify-first: fails until the version bump lands.
    assert SCANNER_VERSION == "1.24.0", SCANNER_VERSION
    assert LOGIC_VERSION == "1.13.0", LOGIC_VERSION   # requires_specialist_tool routing change
    assert SCHEMA_VERSION == "1.15", SCHEMA_VERSION    # new `presentation` namespace


# ---- v1.24 image slice: .jp2 / .tiff -------------------------------------

def _jp2(path: Path, *, width=800, height=600) -> None:
    import struct
    sig = struct.pack(">I", 12) + b"jP  " + b"\x0d\x0a\x87\x0a"
    ftyp = struct.pack(">I", 20) + b"ftyp" + b"jp2 " + struct.pack(">I", 0) + b"jp2 "
    ihdr_payload = struct.pack(">II", height, width) + struct.pack(">H", 3) + b"\x07\x07\x00\x00"
    ihdr = struct.pack(">I", 8 + len(ihdr_payload)) + b"ihdr" + ihdr_payload
    jp2h = struct.pack(">I", 8 + len(ihdr)) + b"jp2h" + ihdr
    path.write_bytes(sig + ftyp + jp2h)


def _tiff(path: Path, *, width=1024, height=768, make="Canon", model="EOS") -> None:
    import struct
    bo = "<"
    n = 5
    blob_base = 8 + (2 + n * 12 + 4)
    blobs = b""
    def ascii_entry(tag, s):
        nonlocal blobs
        data = s.encode() + b"\x00"
        if len(data) <= 4:
            return (tag, 2, len(data), data + b"\x00" * (4 - len(data)))
        off = blob_base + len(blobs)
        blobs += data
        return (tag, 2, len(data), struct.pack(bo + "I", off))
    ents = [
        (256, 4, 1, struct.pack(bo + "I", width)),
        (257, 4, 1, struct.pack(bo + "I", height)),
        ascii_entry(271, make),
        ascii_entry(272, model),
        (274, 3, 1, struct.pack(bo + "H", 1) + b"\x00\x00"),
    ]
    ents.sort(key=lambda e: e[0])
    ifd = struct.pack(bo + "H", n)
    for tag, typ, cnt, val in ents:
        ifd += struct.pack(bo + "HHI", tag, typ, cnt) + val
    ifd += struct.pack(bo + "I", 0)
    header = b"II" + struct.pack(bo + "H", 42) + struct.pack(bo + "I", 8)
    path.write_bytes(header + ifd + blobs)


def test_jp2_dimensions(tmp_path):
    _jp2(tmp_path / "scan.jp2", width=800, height=600)
    rec = _scan_one(tmp_path)
    assert rec.requires_specialist_tool is True
    img = rec.specialist_metadata["image"]
    assert img["width"] == 800 and img["height"] == 600
    assert img.get("make") is None and "xmp_present" in img  # v1.24 fix: uniform image key surface


def test_tiff_dimensions_and_exif(tmp_path):
    _tiff(tmp_path / "scan.tiff", width=1024, height=768, make="Canon", model="EOS")
    rec = _scan_one(tmp_path)
    img = rec.specialist_metadata["image"]
    assert img["width"] == 1024 and img["height"] == 768
    assert img["make"] == "Canon" and img["model"] == "EOS"


def test_tif_extension_routes(tmp_path):
    _tiff(tmp_path / "scan.tif", width=320, height=240)
    rec = _scan_one(tmp_path)
    assert rec.specialist_metadata["image"]["width"] == 320


def test_jp2_truncated_no_crash(tmp_path):
    (tmp_path / "broken.jp2").write_bytes(b"\x00\x00\x00\x0cjP  \x0d\x0a\x87\x0a" + b"\xff" * 20)
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    assert len(m.files) == 1
    sm = m.files[0].specialist_metadata
    img = sm.get("image") if sm else None
    assert img is None or img.get("width") is None

def test_jp2_magic_signature_sniffs(tmp_path):
    # v1.24 review fix: jp2 must sniff on the no-libmagic path (symmetric with tiff)
    import struct
    sc = Scanner(source_dir=tmp_path, config=ScannerConfig())
    sig = struct.pack(">I", 12) + b"jP  " + b"\x0d\x0a\x87\x0a" + struct.pack(">I", 20) + b"ftyp" + b"jp2 "
    assert sc._sniff_mime(sig) == "image/jp2"
