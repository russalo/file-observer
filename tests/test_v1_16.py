"""v1.16.0 — image capture-metadata.

The image specialist gains EXIF for JPEG and HEIC: make / model / orientation /
datetime_original + a GPS-PRESENCE signal (not coordinates) surfaced both as
`image.gps_present` and as the `geotagged` safety_flag, plus `xmp_present`. HEIC image
dimensions come from EXIF PixelX/YDimension (authoritative — the `ispe` box on tiled
iPhone HEICs is a 512px tile, deliberately NOT used). Observe-don't-interpret: each
source is reported, GPS is presence-only, no MWG reconciliation.

Fixtures are self-authored + license-clean (tests/fixtures/generated/, built by
generate.py): exif_camera_gps.jpg (GPS+XMP), exif_camera_nogps.jpg, exif_phone_gps.heic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import file_observer.scanner as fo
from file_observer.scanner import (
    Scanner, ScannerConfig,
    SPECIALIST_TOOLS, SPECIALIST_NAMESPACE, SPECIALIST_FIELDS,
    SPECIALIST_MIME_GUARD, SAFETY_FLAGS,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)

GEN = Path(__file__).parent / "fixtures" / "generated"
IMAGE_EXTS = (".heic", ".heif", ".avif")


def test_release_version_surfaces():
    # v1.16 floor — the exact current-version pin lives in the newest release test.
    def _v(s): return tuple(int(p) for p in s.split("."))
    assert _v(SCANNER_VERSION) >= (1, 16, 0), f"SCANNER regressed below 1.16.0: {SCANNER_VERSION!r}"
    assert _v(LOGIC_VERSION) >= (1, 6, 0), f"LOGIC regressed below 1.6.0: {LOGIC_VERSION!r}"
    assert _v(SCHEMA_VERSION) >= (1, 10), f"SCHEMA regressed below 1.10: {SCHEMA_VERSION!r}"


# --------------------------------------------------------------------------- registries
class TestRegistries:
    @pytest.mark.parametrize("ext", IMAGE_EXTS)
    def test_routed_to_image_specialist(self, ext):
        assert SPECIALIST_TOOLS[ext] == "image_structure"
        assert SPECIALIST_NAMESPACE[ext] == "image"

    def test_image_fields_declared(self):
        for f in ("make", "model", "orientation", "datetime_original",
                  "gps_present", "xmp_present"):
            assert f in SPECIALIST_FIELDS["image"], f

    def test_image_mime_guard_has_heif_family(self):
        assert {"image/heic", "image/heif", "image/avif"} <= SPECIALIST_MIME_GUARD["image"]

    def test_geotagged_in_safety_flags_registry(self):
        assert "geotagged" in SAFETY_FLAGS


# --------------------------------------------------------------------------- JPEG EXIF
class TestJpegExif:
    @pytest.fixture(scope="class")
    def gps(self):
        return _extract(GEN / "exif_camera_gps.jpg")

    @pytest.fixture(scope="class")
    def nogps(self):
        return _extract(GEN / "exif_camera_nogps.jpg")

    def test_make_model_datetime(self, gps):
        assert gps["make"] == "Canon"
        assert gps["model"] == "Canon EOS 5D"
        assert gps["datetime_original"] == "2023:07:04 12:30:00"

    def test_orientation(self, nogps):
        assert nogps["orientation"] == 6

    def test_dimensions_from_sof(self, gps):
        # JPEG keeps its authoritative SOF dims (not overridden by EXIF pixel dims)
        assert (gps["width"], gps["height"]) == (5616, 3744)

    def test_gps_present_true(self, gps):
        assert gps["gps_present"] is True

    def test_gps_present_false(self, nogps):
        assert nogps["gps_present"] is False
        assert "_safety_extras" not in nogps

    def test_xmp_present(self, gps, nogps):
        assert gps["xmp_present"] is True
        assert nogps["xmp_present"] is False

    def test_gps_is_presence_not_coordinates(self, gps):
        # privacy: we surface presence only — NO latitude/longitude keys exist
        assert not any("lat" in k.lower() or "lon" in k.lower() or "coord" in k.lower()
                       for k in gps)


# --------------------------------------------------------------------------- HEIC EXIF
class TestHeicExif:
    @pytest.fixture(scope="class")
    def heic(self):
        return _extract(GEN / "exif_phone_gps.heic")

    def test_make_model(self, heic):
        assert heic["make"] == "Apple"
        assert heic["model"] == "iPhone 15 Pro"

    def test_dimensions_from_exif_pixel_dims(self, heic):
        # authoritative full-image dims (NOT the 512px ispe tile)
        assert (heic["width"], heic["height"]) == (4032, 3024)

    def test_gps_present(self, heic):
        assert heic["gps_present"] is True

    def test_datetime_original(self, heic):
        assert heic["datetime_original"] == "2024:05:01 18:22:10"

    def test_meta_child_order_independent(self):
        # leg-4/Codex: ISO 14496-12 doesn't mandate iinf-before-iloc. Rebuild the
        # fixture's meta box with iinf/iloc swapped (offsets unchanged) → EXIF must
        # still resolve. We reparse the committed fixture and reorder its meta children.
        import struct
        data = bytearray((GEN / "exif_phone_gps.heic").read_bytes())
        # locate meta box and its iinf/iloc children, swap them, re-extract
        meta_off = next(o for t, o, s in fo._iter_isobmff(bytes(data)) if t == "meta")
        msize = struct.unpack(">I", bytes(data[meta_off:meta_off+4]))[0]
        kids = {t: (o, s) for t, o, s in fo._iter_isobmff(bytes(data), meta_off+12, meta_off+msize)}
        (io, isz), (lo, lsz) = kids["iinf"], kids["iloc"]
        assert io < lo  # fixture has iinf first
        iinf_b, iloc_b = bytes(data[io:io+isz]), bytes(data[lo:lo+lsz])
        swapped = bytes(data[:io]) + iloc_b + iinf_b + bytes(data[lo+lsz:])
        tiff = fo._heif_exif_tiff(swapped)
        assert tiff is not None
        assert fo._parse_exif_tiff(tiff)["make"] == "Apple"


# --------------------------------------------------------------------- geotagged in scan
class TestGeotaggedSafetyFlag:
    def test_geotagged_surfaces_in_safety_flags(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes((GEN / "exif_camera_gps.jpg").read_bytes())
        rec = _scan_one(tmp_path, "p.jpg")
        assert "geotagged" in rec.safety_flags

    def test_no_geotagged_without_gps(self, tmp_path):
        (tmp_path / "p.jpg").write_bytes((GEN / "exif_camera_nogps.jpg").read_bytes())
        rec = _scan_one(tmp_path, "p.jpg")
        assert "geotagged" not in rec.safety_flags

    def test_heic_geotagged(self, tmp_path):
        (tmp_path / "p.heic").write_bytes((GEN / "exif_phone_gps.heic").read_bytes())
        rec = _scan_one(tmp_path, "p.heic")
        assert "geotagged" in rec.safety_flags
        assert rec.specialist_metadata["image"]["make"] == "Apple"


# --------------------------------------------------------------------- robustness
class TestRobustness:
    def test_no_exif_jpeg_fields_are_none(self, scanner):
        # plain SOF-only JPEG (no APP1) — dims present, EXIF fields None, never crash
        import struct
        comp = b"\x01\x11\x00"
        data = (b"\xff\xd8" +
                b"\xff\xc0" + struct.pack(">H", 2 + 1 + 2 + 2 + len(comp)) + b"\x08" +
                struct.pack(">HH", 480, 640) + comp + b"\xff\xd9")
        meta = scanner._extract_jpeg_metadata(_tmpfile(data, ".jpg"), data)
        assert meta["width"] == 640 and meta["height"] == 480
        assert meta["make"] is None and meta["gps_present"] is False
        assert "_safety_extras" not in meta

    @pytest.mark.parametrize("garbage", [b"", b"\xff\xd8", b"not a jpeg", b"\x00" * 50])
    def test_garbage_never_crashes(self, scanner, garbage):
        p = _tmpfile(garbage, ".jpg")
        assert scanner._extract_jpeg_metadata(p, garbage) is not None  # returns a dict
        h = _tmpfile(garbage, ".heic")
        # HEIC garbage → dict with None fields, no exception
        assert scanner._extract_heic_metadata(h, garbage) is not None

    def test_iloc_count_is_bounded_no_dos(self):
        # leg-1 finding #1: a crafted iloc with item_count = 0xFFFFFFFF must NOT spin
        # (CPU-bound loops are not catchable by try/except). Bounded by the buffer →
        # returns near-instantly. Build a ~40-byte HEIC naming an 'Exif' item + a
        # version-2 iloc claiming 2^32-1 items.
        import struct, time
        def box(typ, body): return struct.pack(">I", 8 + len(body)) + typ + body
        ftyp = struct.pack(">I", 24) + b"ftypheic" + b"\x00\x00\x00\x00" + b"heicmif1"
        infe = box(b"infe", b"\x02\x00\x00\x00" + struct.pack(">HH", 1, 0) + b"Exif" + b"\x00")
        iinf = box(b"iinf", b"\x00\x00\x00\x00" + struct.pack(">H", 1) + infe)
        iloc = box(b"iloc", b"\x02\x00\x00\x00" + bytes([0x44, 0x00]) + struct.pack(">I", 0xFFFFFFFF))
        craft = ftyp + box(b"meta", b"\x00\x00\x00\x00" + iinf + iloc)
        t0 = time.monotonic()
        assert fo._heif_exif_tiff(craft) is None
        assert time.monotonic() - t0 < 1.0   # bounded, not a 4.3-billion-iteration spin

    def test_iloc_zero_size_fields_bounded(self):
        # leg-2/Gemini: offsz==lensz==0 makes each extent 0 bytes wide, so the inner
        # loop wouldn't advance `p` — must bail, not spin ecount times per item.
        import struct, time
        def box(typ, body): return struct.pack(">I", 8 + len(body)) + typ + body
        ftyp = struct.pack(">I", 24) + b"ftypheic" + b"\x00\x00\x00\x00" + b"heicmif1"
        infe = box(b"infe", b"\x02\x00\x00\x00" + struct.pack(">HH", 1, 0) + b"Exif" + b"\x00")
        iinf = box(b"iinf", b"\x00\x00\x00\x00" + struct.pack(">H", 1) + infe)
        # iloc v1: offsz|lensz = 0x00 (both zero), base|index = 0x00, item_count=2,
        # one item with extent_count=0xFFFF
        body = b"\x01\x00\x00\x00" + bytes([0x00, 0x00]) + struct.pack(">H", 2)
        body += struct.pack(">HHH", 1, 0, 0) + struct.pack(">H", 0xFFFF)
        iloc = box(b"iloc", body)
        craft = ftyp + box(b"meta", b"\x00\x00\x00\x00" + iinf + iloc)
        t0 = time.monotonic()
        assert fo._heif_exif_tiff(craft) is None
        assert time.monotonic() - t0 < 1.0

    def test_jpeg_dims_stop_at_sos_no_false_match(self, scanner):
        # leg-2/Gemini: a stray 0xFFC0 in post-SOS entropy data must NOT be read as a SOF
        # frame. Real SOF (320x240) precedes SOS; the fake SOF after SOS must be ignored.
        import struct
        comp = b"\x01\x11\x00"
        real_sof = b"\xff\xc0" + struct.pack(">H", 2 + 1 + 2 + 2 + len(comp)) + b"\x08" + struct.pack(">HH", 240, 320) + comp
        sos = b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        fake_sof = b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", 9999, 9999) + comp  # inside "scan data"
        data = b"\xff\xd8" + real_sof + sos + b"\x12\x34" + fake_sof + b"\xff\xd9"
        width, height = scanner._jpeg_dimensions(data)
        assert (width, height) == (320, 240)   # the real SOF, never the post-SOS fake

    def test_truncated_heic_meta_no_crash(self, scanner):
        # ftyp present, meta box header but truncated body
        data = (b"\x00\x00\x00\x14ftypheic\x00\x00\x00\x00heicmif1"
                b"\x00\x00\x00\x20meta\x00\x00\x00\x00")  # claims more than present
        p = _tmpfile(data, ".heic")
        m = scanner._extract_heic_metadata(p, data)
        assert m["make"] is None  # no EXIF located, no crash

    def test_bounded_head_read(self, scanner, tmp_path):
        # EXIF beyond the 1 MiB cap is not read (bounded-observation). Take a real
        # EXIF fixture and push its APP1 past 1 MiB with APP0 filler segments inserted
        # right after the SOI → EXIF falls outside the head read → fields None.
        import struct
        orig = (GEN / "exif_camera_gps.jpg").read_bytes()
        assert orig[:2] == b"\xff\xd8"
        filler = b"\xff\xe0" + struct.pack(">H", 0xFFFF) + b"\x00" * (0xFFFF - 2)
        body = b"\xff\xd8" + filler * 32 + orig[2:]   # ~2 MiB of filler before the APP1
        p = tmp_path / "big.jpg"
        p.write_bytes(body)
        meta = scanner._extract_jpeg_metadata(p, body[:8192])
        assert meta["make"] is None  # EXIF past the cap is honestly unobserved


# --------------------------------------------------------------------- determinism
class TestDeterminism:
    def test_workers_byte_identical(self, tmp_path):
        for n in ("a", "b", "c"):
            (tmp_path / f"{n}.jpg").write_bytes((GEN / "exif_camera_gps.jpg").read_bytes())
        (tmp_path / "p.heic").write_bytes((GEN / "exif_phone_gps.heic").read_bytes())
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        m4 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.manifest_checksum == m4.manifest_checksum


# --------------------------------------------------------------------- helpers / fixtures
@pytest.fixture
def scanner(tmp_path_factory):
    return Scanner(source_dir=tmp_path_factory.mktemp("v116"),
                   config=ScannerConfig(enable_specialists=True))


def _extract(path: Path) -> dict:
    sc = Scanner(source_dir=path.parent, config=ScannerConfig(enable_specialists=True))
    ext = path.suffix.lower()
    return sc.extract_specialist_metadata(path, ext, path.read_bytes()[:8192])


def _scan_one(dirpath: Path, name: str):
    m = Scanner(source_dir=dirpath, config=ScannerConfig(enable_specialists=True)).scan()
    return next(f for f in m.files if f.filename == name)


_TMP: list[Path] = []


def _tmpfile(data: bytes, suffix: str) -> Path:
    import tempfile
    fd, name = tempfile.mkstemp(suffix=suffix)
    import os
    os.write(fd, data)
    os.close(fd)
    p = Path(name)
    _TMP.append(p)
    return p


def teardown_module(module):
    for p in _TMP:
        try:
            p.unlink()
        except OSError:
            pass
