#!/usr/bin/env python3
"""Generate license-clean, spec-accurate fixtures for coverage gaps (v1.15.1 follow-up).

We can't redistribute ISO/Nokia HEIF conformance files (no clear license), so we
SELF-GENERATE fixtures whose structure is spec-correct (ISO/IEC 23008-12 HEIF + MP4RA
brand registry for the ftyp box; the OLE2/CFB + MS-OLEPS property set for .doc/.xls).
The scanner reads only the ftyp brand / OLE2 SummaryInformation, so these exercise the
exact code path. Outputs go to tests/fixtures/generated/ ; this script is the provenance.
"""
import struct
from pathlib import Path

OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)


# ---- HEIF/AVIF: a spec-correct ftyp box + a minimal padding body --------------
def ftyp_file(major: bytes, compatible: list[bytes]) -> bytes:
    assert len(major) == 4 and all(len(c) == 4 for c in compatible)
    payload = major + b"\x00\x00\x00\x00" + b"".join(compatible)  # major + minor + compat
    box = b"ftyp" + payload
    box = struct.pack(">I", 4 + len(box)) + box                   # prepend size
    # a tiny 'free' box of padding so it reads like a real (if undecodable) file
    free = struct.pack(">I", 16) + b"free" + b"\x00" * 8
    return box + free


HEIF = {
    # major brand, compatible_brands (per MP4RA + ISO 23008-12 / 23000-22 MIAF)
    "image_heic.heic":        (b"heic", [b"heic", b"mif1"]),          # HEVC-coded HEIF (the common iPhone case)
    "heif_mif1_heic.heic":    (b"mif1", [b"mif1", b"heic"]),          # generic HEIF MAJOR, heic-compatible (the codex/v1.16 case)
    "heif_msf1_seq.heic":     (b"msf1", [b"msf1", b"hevc", b"iso8"]), # HEIF image sequence
    "image_avif.avif":        (b"avif", [b"avif", b"mif1", b"miaf"]), # AVIF (AOM AVIF spec)
}
for name, (major, compat) in HEIF.items():
    (OUT / name).write_bytes(ftyp_file(major, compat))
    print(f"wrote {name:24} major={major.decode()} compat={[c.decode() for c in compat]}")


# ---- .xls: a real BIFF8 workbook via xlwt (license-clean, self-authored) ------
import xlwt  # noqa: E402
wb = xlwt.Workbook()
wb.set_owner("File Observer Test")
for s in ("Summary", "Data"):
    ws = wb.add_sheet(s)
    ws.write(0, 0, "header")
    ws.write(1, 0, 42)
(OUT / "generated.xls").parent.mkdir(exist_ok=True)
wb.save(str(OUT / "generated.xls"))
print("wrote generated.xls (BIFF8, 2 sheets, owner set)")


# ---- .doc: a minimal OLE2/CFB with ONLY a SummaryInformation stream ----------
# CFB v3, 512-byte sectors. One regular stream (padded >= mini-cutoff so no mini-FAT).
def _propset(fmtid: bytes, props: list) -> bytes:
    """An MS-OLEPS single-section property set. ``props`` is a list of
    (propid, encoded-value) pairs (use the lpstr/i2/i4 helpers below)."""
    n = len(props)
    table_size = 8 + n * 8
    offsets, blob, off = [], b"", table_size
    for pid, val in props:
        offsets.append((pid, off)); blob += val; off += len(val)
    section = struct.pack("<II", table_size + len(blob), n)
    for pid, o in offsets:
        section += struct.pack("<II", pid, o)
    section += blob
    # property-set header: [WORD bom][WORD ver][DWORD os][CLSID][DWORD numsections][FMTID][DWORD offset]
    header = struct.pack("<HHI", 0xFFFE, 0, 0x00020005) + b"\x00" * 16 + struct.pack("<I", 1)
    header += fmtid + struct.pack("<I", len(header) + 16 + 4)  # offset to section
    return header + section


def _lpstr(s: str) -> bytes:
    b = s.encode("cp1252") + b"\x00"
    return struct.pack("<I", 30) + struct.pack("<I", len(b)) + b  # VT_LPSTR


def _i2(v: int) -> bytes:
    return struct.pack("<I", 2) + struct.pack("<h", v) + b"\x00\x00"  # VT_I2


def _i4(v: int) -> bytes:
    return struct.pack("<I", 3) + struct.pack("<i", v)  # VT_I4


def _summaryinformation_propset(title: str, author: str, app: str | None = None) -> bytes:
    FMTID = bytes.fromhex("e0859ff2f94f6810ab9108002b27b3d9")  # SummaryInformation FMTID
    props = [(1, _i2(1252)), (2, _lpstr(title)), (4, _lpstr(author))]  # CodePage, Title, Author
    if app is not None:
        props.append((18, _lpstr(app)))  # PIDSI_APPNAME (0x12) — creating app
    return _propset(FMTID, props)


def _docsummaryinformation_propset(slide_count: int) -> bytes:
    FMTID = bytes.fromhex("02d5cdd59c2e1b1093970800 2b2cf9ae".replace(" ", ""))  # DocumentSummaryInformation FMTID
    props = [(1, _i2(1252)), (7, _i4(slide_count))]  # CodePage, PIDDSI_SLIDECOUNT (0x07, VT_I4)
    return _propset(FMTID, props)


def _minimal_ole2(streams: list) -> bytes:
    """Minimal CFB v3 (512-byte sectors) holding ``streams`` = list of
    (name, data). Each stream is padded to >= 4096 so it is a MAJOR (non-mini)
    stream — the simplest possible layout (no mini-FAT). Entries are linked as a
    right-leaning chain under Root.child (olefile's in-order walk visits all)."""
    SECTOR = 512
    ENDOFCHAIN, FREESECT, FATSECT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD
    padded = [(name, data + b"\x00" * (4096 - len(data)) if len(data) < 4096 else data)
              for name, data in streams]
    # layout: sector 0 = FAT; sector 1 = directory; sectors 2.. = streams (contiguous)
    fat = [FREESECT] * 128
    fat[0] = FATSECT          # the FAT sector
    fat[1] = ENDOFCHAIN       # directory (1 sector — entries fit in 512B; see assert below)
    layout, nxt = [], 2
    for name, data in padded:
        nsec = (len(data) + SECTOR - 1) // SECTOR
        start = nxt
        for i in range(nsec):
            s = start + i
            fat[s] = ENDOFCHAIN if i == nsec - 1 else s + 1
        layout.append((name, start, len(data)))
        nxt += nsec
    fat_bytes = b"".join(struct.pack("<I", e) for e in fat)

    def dirent(name: str, etype: int, start: int, size: int,
               left: int = -1, right: int = -1, child: int = -1) -> bytes:
        nb = name.encode("utf-16-le") + b"\x00\x00"
        nb = nb[:64].ljust(64, b"\x00")
        e = nb + struct.pack("<H", min(len(name) * 2 + 2, 64))
        e += struct.pack("<B", etype) + struct.pack("<B", 1)            # type, color=black
        e += struct.pack("<iii", left, right, child)                    # left,right,child sids
        e += b"\x00" * 16 + struct.pack("<I", 0)                        # CLSID, state
        e += b"\x00" * 8 + b"\x00" * 8                                  # ctime, mtime
        e += struct.pack("<I", start if start >= 0 else 0)             # starting sector (4)
        e += struct.pack("<Q", size)                                    # stream size (8) — must be 8 bytes
        assert len(e) == 128, len(e)
        return e

    n = len(layout)
    entries = [dirent("Root Entry", 5, ENDOFCHAIN, 0, child=1)]      # child -> dir index 1
    for i, (name, start, size) in enumerate(layout):
        right = (i + 2) if i < n - 1 else -1   # chain to the next stream's dir index
        entries.append(dirent(name, 2, start, size, right=right))
    while (len(entries) * 128) % SECTOR != 0:   # pad to a whole sector with empty entries
        entries.append(dirent("", 0, -1, 0))
    directory = b"".join(entries)
    assert len(directory) == SECTOR, "fixture keeps the directory to one sector (<=4 entries)"
    # header
    h = bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 16
    h += struct.pack("<HHHH", 0x003E, 0x0003, 0xFFFE, 0x0009)           # minor, major(v3), bom, sectorshift=512
    h += struct.pack("<H", 0x0006) + b"\x00" * 6                        # minisectorshift=64, reserved
    h += struct.pack("<I", 0)                                           # #dir sectors (0 for v3)
    h += struct.pack("<I", 1)                                           # #FAT sectors
    h += struct.pack("<I", 1)                                           # first dir sector
    h += struct.pack("<I", 0)                                           # transaction sig
    h += struct.pack("<I", 4096)                                        # mini-stream cutoff
    h += struct.pack("<I", ENDOFCHAIN) + struct.pack("<I", 0)           # first mini-FAT, #mini-FAT
    h += struct.pack("<I", ENDOFCHAIN) + struct.pack("<I", 0)           # first DIFAT, #DIFAT
    difat = [0] + [FREESECT] * 108                                     # FAT is at sector 0
    h += b"".join(struct.pack("<I", e) for e in difat)
    assert len(h) == SECTOR, len(h)
    return h + fat_bytes + directory + b"".join(d for _, d in padded)


doc = _minimal_ole2([("\x05SummaryInformation",
                      _summaryinformation_propset("File Observer Test Doc", "File Observer Test"))])
(OUT / "generated.doc").write_bytes(doc)
print(f"wrote generated.doc (minimal OLE2 + SummaryInformation, {len(doc)} bytes)")


# ---- v1.25: a minimal OLE2/CFB .ppt (legacy PowerPoint) ----------------------
# SummaryInformation (title/author/application 0x12) + DocumentSummaryInformation
# (PIDDSI_SLIDECOUNT 0x07). The scanner reads exactly those property ids — no real
# PowerPoint stream is needed to exercise the v1.25 _extract_ppt_metadata path.
ppt = _minimal_ole2([
    ("\x05SummaryInformation",
     _summaryinformation_propset("File Observer Test Deck", "File Observer Test",
                                 app="Microsoft PowerPoint")),
    ("\x05DocumentSummaryInformation", _docsummaryinformation_propset(7)),
])
(OUT / "generated.ppt").write_bytes(ppt)
print(f"wrote generated.ppt (minimal OLE2 + Summary/DocumentSummary, {len(ppt)} bytes)")

# ---- v1.25.1: a minimal OLE2/CFB .msg (Outlook message) ----------------------
# Two MAPI substorage streams (PR_SUBJECT 0x0037 + PR_SENDER_NAME 0x0C1A, both the
# Unicode `001F` variant = UTF-16LE) — the streams the `.msg` email specialist reads.
# Exercises the v1.25.1 OLE2 full-file-deviation provenance path for the `email` namespace.
msg = _minimal_ole2([
    ("__substg1.0_0037001F", "File Observer Test Subject".encode("utf-16-le")),
    ("__substg1.0_0C1A001F", "File Observer Test Sender".encode("utf-16-le")),
])
(OUT / "generated.msg").write_bytes(msg)
print(f"wrote generated.msg (minimal OLE2 + MAPI substg streams, {len(msg)} bytes)")

# Round-trip verification — the scanner's own olefile path must read both streams.
try:
    import olefile as _ole  # noqa: E402
    o = _ole.OleFileIO(str(OUT / "generated.ppt"))
    _s = o.getproperties("\x05SummaryInformation")
    _d = o.getproperties("\x05DocumentSummaryInformation")
    o.close()
    def _s2t(v):  # olefile returns VT_LPSTR raw (bytes) — the scanner decodes cp1252
        return v.decode("cp1252").rstrip("\x00") if isinstance(v, bytes) else v
    assert _s2t(_s.get(2)) == "File Observer Test Deck", _s.get(2)
    assert _s2t(_s.get(4)) == "File Observer Test", _s.get(4)
    assert _s2t(_s.get(18)) == "Microsoft PowerPoint", _s.get(18)
    assert _d.get(7) == 7, _d.get(7)
    print("  round-trip OK: olefile reads title/author/application + slide_count=7")
except ImportError:
    print("  (olefile not installed — skipped round-trip verification)")


# ---- v1.16: EXIF-bearing JPEG + HEIC (CIPA DC-008 TIFF/IFD; ISO 14496-12 meta/iloc) --
# Self-authored EXIF blocks — no third-party photo (license-clean). The scanner reads
# Make/Model/Orientation/DateTimeOriginal + GPS-IFD presence + EXIF pixel dimensions;
# these fixtures exercise exactly that path. Round-trip verified against the scanner's
# own parser at authoring time.
def _exif_tiff(make, model, dt_original, orientation, px, py, with_gps):
    """Little-endian TIFF: IFD0 (Make/Model/Orientation/DateTime + Exif ptr [+ GPS ptr])
    → Exif sub-IFD (DateTimeOriginal + PixelX/YDimension) [→ empty GPS IFD]."""
    bo = "<"
    def asc(s): return s.encode("ascii") + b"\x00"
    make_b, model_b, dto_b, dt_main = asc(make), asc(model), asc(dt_original), asc("2024:01:01 00:00:00")
    n0 = 6 if with_gps else 5
    ifd0_size = 2 + 12 * n0 + 4
    base = 8 + ifd0_size
    make_ptr, model_ptr = base, base + len(make_b)
    dt_ptr = model_ptr + len(model_b)
    exif_off = base + len(make_b) + len(model_b) + len(dt_main)
    ifdE_size = 2 + 12 * 3 + 4
    dto_ptr = exif_off + ifdE_size
    gps_off = dto_ptr + len(dto_b)

    def E(tag, typ, count, payload):
        if len(payload) <= 4:
            payload = payload + b"\x00" * (4 - len(payload))
        return struct.pack(bo + "HHI", tag, typ, count) + payload

    out = bytearray(b"II" + struct.pack(bo + "HI", 42, 8))
    out += struct.pack(bo + "H", n0)
    e0 = [
        (0x010F, 2, len(make_b), struct.pack(bo + "I", make_ptr)),
        (0x0110, 2, len(model_b), struct.pack(bo + "I", model_ptr)),
        (0x0112, 3, 1, struct.pack(bo + "H", orientation)),
        (0x0132, 2, len(dt_main), struct.pack(bo + "I", dt_ptr)),
        (0x8769, 4, 1, struct.pack(bo + "I", exif_off)),
    ]
    if with_gps:
        e0.append((0x8825, 4, 1, struct.pack(bo + "I", gps_off)))
    for tag, typ, count, payload in sorted(e0):
        out += E(tag, typ, count, payload)
    out += struct.pack(bo + "I", 0) + make_b + model_b + dt_main
    out += struct.pack(bo + "H", 3)
    for tag, typ, count, payload in sorted([
        (0x9003, 2, len(dto_b), struct.pack(bo + "I", dto_ptr)),
        (0xA002, 4, 1, struct.pack(bo + "I", px)),
        (0xA003, 4, 1, struct.pack(bo + "I", py)),
    ]):
        out += E(tag, typ, count, payload)
    out += struct.pack(bo + "I", 0) + dto_b
    if with_gps:
        out += struct.pack(bo + "H", 0) + struct.pack(bo + "I", 0)   # empty GPS IFD (presence is the signal)
    return bytes(out)


def _jpeg_with_exif(tiff, width, height, with_xmp=False):
    comp = b"\x01\x11\x00"
    sof = b"\xff\xc0" + struct.pack(">H", 2 + 1 + 2 + 2 + len(comp)) + b"\x08" + struct.pack(">HH", height, width) + comp
    out = bytearray(b"\xff\xd8")
    app1 = b"Exif\x00\x00" + tiff
    out += b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1
    if with_xmp:
        xmp = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>"
        out += b"\xff\xe1" + struct.pack(">H", len(xmp) + 2) + xmp
    return bytes(out + sof + b"\xff\xd9")


def _heif_with_exif(tiff, major=b"heic"):
    def box(typ, body): return struct.pack(">I", 8 + len(body)) + typ + body
    ftyp = struct.pack(">I", 4 + 4 + 4 + 4 + 8) + b"ftyp" + major + b"\x00\x00\x00\x00" + major + b"mif1"
    infe = box(b"infe", b"\x02\x00\x00\x00" + struct.pack(">HH", 1, 0) + b"Exif" + b"\x00")
    iinf = box(b"iinf", b"\x00\x00\x00\x00" + struct.pack(">H", 1) + infe)
    exif_payload = struct.pack(">I", 0) + tiff
    def iloc(off):
        body = b"\x01\x00\x00\x00" + bytes([0x44, 0x00]) + struct.pack(">HHHH", 1, 1, 0, 0)
        body += struct.pack(">H", 1) + struct.pack(">II", off, len(exif_payload))
        return box(b"iloc", body)
    meta = box(b"meta", b"\x00\x00\x00\x00" + iinf + iloc(0))
    off = len(ftyp) + len(meta) + 8
    meta = box(b"meta", b"\x00\x00\x00\x00" + iinf + iloc(off))
    return ftyp + meta + box(b"mdat", exif_payload)


for name, data in {
    "exif_camera_gps.jpg": _jpeg_with_exif(_exif_tiff("Canon", "Canon EOS 5D", "2023:07:04 12:30:00", 1, 5616, 3744, True), 5616, 3744, with_xmp=True),
    "exif_camera_nogps.jpg": _jpeg_with_exif(_exif_tiff("NIKON", "NIKON D850", "2022:11:02 09:15:42", 6, 8256, 5504, False), 8256, 5504),
    "exif_phone_gps.heic": _heif_with_exif(_exif_tiff("Apple", "iPhone 15 Pro", "2024:05:01 18:22:10", 6, 4032, 3024, True)),
}.items():
    (OUT / name).write_bytes(data)
    print(f"wrote {name:24} EXIF fixture ({len(data)} bytes)")


# ---- v1.17: minimal ISOBMFF .mov (moov at the TAIL, after mdat) ----------------
# Self-authored QuickTime container exercising the video_structure parse:
# moov{mvhd, trak{tkhd, mdia{hdlr(vide), minf{stbl{stsd(codec)}}}}}. Placed AFTER mdat
# so it tests the tail-scan (real .mov put moov at the end — measured 61/62). Round-trip
# verified; container-half fields only (codec/duration/dims/creation_date).
def _mov_with_moov_at_tail(codec=b"avc1", w=1920, h=1080,
                           created=3658232843, timescale=600, duration=3000):
    def box(typ, body): return struct.pack(">I", 8 + len(body)) + typ + body
    mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", created, created, timescale, duration) + b"\x00" * 80)
    tkhd = box(b"tkhd", b"\x00\x00\x00\x07" + b"\x00" * 72 + struct.pack(">II", w << 16, h << 16))
    hdlr = box(b"hdlr", b"\x00" * 8 + b"vide" + b"\x00" * 13)
    stsd = box(b"stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + box(codec, b"\x00" * 8))
    stbl = box(b"stbl", stsd)
    minf = box(b"minf", stbl)
    mdia = box(b"mdia", hdlr + minf)
    trak = box(b"trak", tkhd + mdia)
    moov = box(b"moov", mvhd + trak)
    ftyp = box(b"ftyp", b"qt  " + b"\x00\x00\x00\x00" + b"qt  ")
    mdat = box(b"mdat", b"\x00" * 64)
    return ftyp + mdat + moov


(OUT / "video_h264.mov").write_bytes(_mov_with_moov_at_tail())
print(f"wrote video_h264.mov           minimal ISOBMFF (moov-at-tail) fixture")


# ---- v1.18: ISOBMFF .mov with Apple QuickTime keys (make/model) + GPS-presence ----
# Self-authored QuickTime metadata: moov→meta(NOT a FullBox)→{hdlr, keys, ilst}. `keys`
# is the ordered key table (`mdta` namespace); `ilst` items are typed by 1-based index
# into it; each item's `data` box holds the value. Exercises the v1.18 make/model +
# gps_present/gps_source + geotagged path. License-clean; the GPS string is fabricated
# (NOT real coordinates — real geotagged clips stay local-gitignored).
def _mov_with_qt_keys(make=b"TestMake", model=b"TestPhone X",
                      iso6709=b"+12.3456-098.7654+010.000/", iso_meta=False):
    # iso_meta=True → wrap the meta body in a 4-byte version/flags (the ISO `.mp4`
    # FullBox form, children at +12) instead of the QuickTime `.mov` form (children at +8).
    def box(typ, body): return struct.pack(">I", 8 + len(body)) + typ + body
    mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 3658232843, 0, 600, 3000) + b"\x00" * 80)
    tkhd = box(b"tkhd", b"\x00\x00\x00\x07" + b"\x00" * 72 + struct.pack(">II", 1920 << 16, 1080 << 16))
    stsd = box(b"stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + box(b"avc1", b"\x00" * 8))
    mdia = box(b"mdia", box(b"hdlr", b"\x00" * 8 + b"vide" + b"\x00" * 13) + box(b"minf", box(b"stbl", stsd)))
    trak = box(b"trak", tkhd + mdia)
    keystrs, vals = [b"com.apple.quicktime.make", b"com.apple.quicktime.model",
                     b"com.apple.quicktime.creationdate"], [make, model, b"2024-01-01T00:00:00-0800"]
    if iso6709:
        keystrs.append(b"com.apple.quicktime.location.ISO6709"); vals.append(iso6709)
    keys_body = b"\x00\x00\x00\x00" + struct.pack(">I", len(keystrs))
    for k in keystrs:
        keys_body += struct.pack(">I", 8 + len(k)) + b"mdta" + k
    ilst_body = b""
    for i, v in enumerate(vals, start=1):
        data = box(b"data", struct.pack(">II", 1, 0) + v)
        ilst_body += struct.pack(">I", 8 + len(data)) + struct.pack(">I", i) + data
    meta_body = box(b"hdlr", b"\x00" * 8 + b"mdir" + b"\x00" * 13) + box(b"keys", keys_body) + box(b"ilst", ilst_body)
    if iso_meta:
        meta_body = b"\x00\x00\x00\x00" + meta_body   # ISO FullBox version/flags → children at +12
    meta = box(b"meta", meta_body)
    moov = box(b"moov", mvhd + trak + meta)
    ftyp = box(b"ftyp", b"qt  " + b"\x00\x00\x00\x00" + b"qt  ")
    return ftyp + box(b"mdat", b"\x00" * 64) + moov


(OUT / "video_qt_gps.mov").write_bytes(_mov_with_qt_keys())
(OUT / "video_qt_nogps.mov").write_bytes(_mov_with_qt_keys(iso6709=None))
(OUT / "video_qt_iso_mp4.mp4").write_bytes(_mov_with_qt_keys(iso_meta=True))   # ISO FullBox meta (.mp4 form)
print("wrote video_qt_gps.mov + video_qt_nogps.mov + video_qt_iso_mp4.mp4  (Apple QuickTime keys, both meta forms)")
