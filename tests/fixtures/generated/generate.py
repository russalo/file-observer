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
def _summaryinformation_propset(title: str, author: str) -> bytes:
    FMTID = bytes.fromhex("e0859ff2f94f6810ab9108002b27b3d9")  # SummaryInformation FMTID
    def lpstr(s: str) -> bytes:
        b = s.encode("cp1252") + b"\x00"
        return struct.pack("<I", 30) + struct.pack("<I", len(b)) + b  # VT_LPSTR
    def i2(v: int) -> bytes:
        return struct.pack("<I", 2) + struct.pack("<h", v) + b"\x00\x00"  # VT_I2
    props = [(1, i2(1252)), (2, lpstr(title)), (4, lpstr(author))]  # CodePage, Title, Author
    # section: [dword bytesize][dword numprops][ (propid, offset) * n ][ values ]
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
    header += FMTID + struct.pack("<I", len(header) + 16 + 4)  # offset to section
    return header + section


def _minimal_ole2(stream_name: str, data: bytes) -> bytes:
    SECTOR = 512
    ENDOFCHAIN, FREESECT, FATSECT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD
    # pad stream to >= 4096 so it's a major (non-mini) stream → simplest layout
    if len(data) < 4096:
        data = data + b"\x00" * (4096 - len(data))
    n_stream_sectors = (len(data) + SECTOR - 1) // SECTOR
    # layout: sector 0 = FAT; sector 1 = directory; sectors 2.. = stream
    first_stream = 2
    total_sectors = 2 + n_stream_sectors
    fat = [FREESECT] * 128
    fat[0] = FATSECT          # the FAT sector
    fat[1] = ENDOFCHAIN       # directory (1 sector)
    for i in range(n_stream_sectors):
        s = first_stream + i
        fat[s] = ENDOFCHAIN if i == n_stream_sectors - 1 else s + 1
    fat_bytes = b"".join(struct.pack("<I", e) for e in fat)
    # directory: Root Entry (storage) + SummaryInformation (stream) + 2 empty
    def dirent(name: str, etype: int, start: int, size: int, child: int = FREESECT) -> bytes:
        nb = name.encode("utf-16-le") + b"\x00\x00"
        nb = nb[:64].ljust(64, b"\x00")
        e = nb + struct.pack("<H", min(len(name) * 2 + 2, 64))
        e += struct.pack("<B", etype) + struct.pack("<B", 1)            # type, color=black
        e += struct.pack("<iii", -1, -1, child if child != FREESECT else -1)  # left,right,child
        e += b"\x00" * 16 + struct.pack("<I", 0)                        # CLSID, state
        e += b"\x00" * 8 + b"\x00" * 8                                  # ctime, mtime
        e += struct.pack("<I", start if start != FREESECT else 0)       # starting sector (4)
        e += struct.pack("<Q", size)                                    # stream size (8) — must be 8 bytes
        assert len(e) == 128, len(e)
        return e
    root = dirent("Root Entry", 5, ENDOFCHAIN, 0, child=1)
    summ = dirent("\x05SummaryInformation", 2, first_stream, len(data))
    empty = dirent("", 0, FREESECT, 0)
    directory = (root + summ + empty + empty).ljust(SECTOR, b"\x00")
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
    return h + fat_bytes + directory + data


doc = _minimal_ole2("\x05SummaryInformation",
                    _summaryinformation_propset("File Observer Test Doc", "File Observer Test"))
(OUT / "generated.doc").write_bytes(doc)
print(f"wrote generated.doc (minimal OLE2 + SummaryInformation, {len(doc)} bytes)")
