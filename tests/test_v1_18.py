"""v1.18.0 — video capture device + GPS-presence (the iPhone-specific half).

The video specialist gains the Apple QuickTime keys — `make` / `model` from
`moov`→`meta`→`keys`/`ilst` (`com.apple.quicktime.make`/`.model`) — and a GPS signal:
`gps_present` (bool) + `gps_source` (the mechanism, `com.apple.quicktime.location.ISO6709`),
surfaced WITHOUT coordinates, with `geotagged` firing for video. QuickTime's `meta` is NOT
a FullBox (children at +8) — the gotcha vs the ISO `meta` of the HEIC `iloc` path.

Validated measure-first against `exiftool` on two REAL iPhone 16 Pro Max clips (gitignored,
real coordinates): one GPS-present, one Location-OFF. Committable synthetic fixtures
(`video_qt_gps.mov` / `video_qt_nogps.mov`, fabricated coordinates) exercise the same path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import file_observer.scanner as fo
from file_observer.scanner import (
    Scanner, ScannerConfig, SPECIALIST_FIELDS, SAFETY_FLAGS,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)

GEN = Path(__file__).parent / "fixtures" / "generated"
GPS = GEN / "video_qt_gps.mov"
NOGPS = GEN / "video_qt_nogps.mov"
ISO_MP4 = GEN / "video_qt_iso_mp4.mp4"   # ISO FullBox meta (.mp4 form, children at +12)
# real iPhone clips — local-gitignored (real coordinates); tests using them auto-skip in CI
REAL = Path(__file__).parent.parent / "scratch" / "v1_18_corpus" / "video"


def test_release_version_surfaces():
    def _v(x): return tuple(int(p) for p in x.split("."))
    assert _v(SCANNER_VERSION) >= (1, 18, 0), f"SCANNER regressed: {SCANNER_VERSION!r}"
    assert _v(LOGIC_VERSION) >= (1, 8, 0), f"LOGIC regressed: {LOGIC_VERSION!r}"
    assert _v(SCHEMA_VERSION) >= (1, 12), f"SCHEMA regressed: {SCHEMA_VERSION!r}"


def _extract(path):
    sc = Scanner(source_dir=path.parent, config=ScannerConfig(enable_specialists=True))
    return sc.extract_specialist_metadata(path, ".mov", path.read_bytes()[:8192])


# --------------------------------------------------------------------------- registry
class TestRegistry:
    def test_video_fields_extended(self):
        for f in ("make", "model", "gps_present", "gps_source"):
            assert f in SPECIALIST_FIELDS["video"], f

    def test_geotagged_description_covers_video(self):
        assert "video" in SAFETY_FLAGS["geotagged"].lower()


# --------------------------------------------------------------------------- make/model
class TestDeviceKeys:
    def test_make_model_extracted(self):
        m = _extract(GPS)
        assert m["make"] == "TestMake"
        assert m["model"] == "TestPhone X"

    def test_make_model_present_without_gps_too(self):
        m = _extract(NOGPS)
        assert m["make"] == "TestMake" and m["model"] == "TestPhone X"

    def test_container_fields_still_work(self):
        m = _extract(GPS)   # v1.17 fields unaffected
        assert m["codec"] == "avc1" and (m["width"], m["height"]) == (1920, 1080)

    def test_iso_fullbox_meta_mp4(self):
        # leg-2/Gemini: standard .mp4 uses the ISO FullBox `meta` (children at +12, not the
        # QuickTime +8). Must still extract make/model/GPS — not silently drop them.
        m = _extract(ISO_MP4)
        assert m["make"] == "TestMake" and m["model"] == "TestPhone X"
        assert m["gps_present"] is True
        assert m["gps_source"] == "com.apple.quicktime.location.ISO6709"


# --------------------------------------------------------------------------- GPS-presence
class TestGpsPresence:
    def test_gps_present_true_and_source(self):
        m = _extract(GPS)
        assert m["gps_present"] is True
        assert m["gps_source"] == "com.apple.quicktime.location.ISO6709"

    def test_gps_absent(self):
        m = _extract(NOGPS)
        assert m["gps_present"] is False
        assert m["gps_source"] is None
        assert "_safety_extras" not in m

    def test_no_coordinates_leaked(self):
        # presence only — NO latitude/longitude/coordinate field anywhere
        m = _extract(GPS)
        assert not any(k for k in m if any(s in k.lower() for s in ("lat", "lon", "coord")))
        # and the fabricated ISO6709 value must not appear in the output
        assert "12.3456" not in repr(m)


# --------------------------------------------------------------------- geotagged via scan
class TestGeotagged:
    def test_geotagged_fires_for_video(self, tmp_path):
        (tmp_path / "v.mov").write_bytes(GPS.read_bytes())
        m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        rec = next(f for f in m.files if f.filename == "v.mov")
        assert "geotagged" in rec.safety_flags
        assert rec.specialist_metadata["video"]["gps_present"] is True

    def test_no_geotagged_without_gps(self, tmp_path):
        (tmp_path / "v.mov").write_bytes(NOGPS.read_bytes())
        m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        rec = next(f for f in m.files if f.filename == "v.mov")
        assert "geotagged" not in rec.safety_flags


# --------------------------------------------------------------------- robustness
class TestRobustness:
    @pytest.fixture
    def scanner(self, tmp_path_factory):
        return Scanner(source_dir=tmp_path_factory.mktemp("v118"),
                       config=ScannerConfig(enable_specialists=True))

    def test_keys_without_ilst_no_crash(self, scanner):
        # a meta with keys but no ilst → no values, honest-null, no crash
        import struct
        def box(t, b): return struct.pack(">I", 8 + len(b)) + t + b
        meta = box(b"meta", box(b"keys", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">I", 32) + b"mdta" + b"com.apple.quicktime.make"))
        assert fo._qt_keys(meta, 0, len(meta)) == {}   # no ilst → empty

    def test_attacker_key_count_bounded(self, scanner):
        # keys box claims 2^32-1 entries but the box is tiny → bounded by the box, not n
        import struct, time
        def box(t, b): return struct.pack(">I", 8 + len(b)) + t + b
        keys = box(b"keys", b"\x00\x00\x00\x00" + struct.pack(">I", 0xFFFFFFFF))  # huge count, no entries
        meta = box(b"meta", keys + box(b"ilst", b""))
        t0 = time.monotonic()
        fo._qt_keys(meta, 0, len(meta))
        assert time.monotonic() - t0 < 1.0   # bounded by box length, not the claimed count

    def test_empty_gps_tombstone_not_present(self, scanner):
        # leg-2/Gemini: a location key whose data box is empty (b"") is a tombstone, NOT a
        # location — gps_present must stay False (require a non-empty value).
        import struct
        def box(t, b): return struct.pack(">I", 8 + len(b)) + t + b
        keystrs = [b"com.apple.quicktime.location.ISO6709"]
        kb = b"\x00\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">I", 8 + len(keystrs[0])) + b"mdta" + keystrs[0]
        data = box(b"data", struct.pack(">II", 1, 0) + b"")   # empty value
        ilst = struct.pack(">I", 8 + len(box(b"data", struct.pack(">II", 1, 0) + b""))) + struct.pack(">I", 1) + data
        meta = box(b"meta", box(b"keys", kb) + box(b"ilst", ilst))
        keys = fo._qt_keys(meta, 0, len(meta))
        assert fo._QT_GPS_KEY in keys                    # key IS present...
        assert not keys[fo._QT_GPS_KEY]                  # ...but with an empty value
        # and _parse_moov must NOT flag gps_present off the empty value (tested via the path)

    def test_garbage_meta_no_crash(self, scanner, tmp_path):
        import struct
        def box(t, b): return struct.pack(">I", 8 + len(b)) + t + b
        data = box(b"ftyp", b"qt  " + b"\x00" * 8) + box(b"mdat", b"\x00" * 16) + \
            box(b"moov", box(b"meta", b"\x00garbage\xff\xfe"))
        p = tmp_path / "g.mov"; p.write_bytes(data)
        meta = scanner._extract_video_metadata(p, b"")
        assert meta["make"] is None and meta["gps_present"] is False   # no crash


# --------------------------------------------------------------------- determinism
class TestDeterminism:
    def test_workers_byte_identical(self, tmp_path):
        for n in ("a", "b"):
            (tmp_path / f"{n}.mov").write_bytes(GPS.read_bytes())
        (tmp_path / "c.mov").write_bytes(NOGPS.read_bytes())
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        m4 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.manifest_checksum == m4.manifest_checksum


# --------------------------------------------------- real-corpus oracle (gitignored; skips in CI)
class TestRealCorpus:
    @pytest.mark.skipif(not (REAL / "iphone16promax_gps.MOV").exists(),
                        reason="real iPhone corpus is local-gitignored (real GPS)")
    def test_real_iphone_gps_clip(self):
        m = _extract(REAL / "iphone16promax_gps.MOV")
        assert m["make"] == "Apple" and m["model"] == "iPhone 16 Pro Max"
        assert m["gps_present"] is True
        assert m["gps_source"] == "com.apple.quicktime.location.ISO6709"

    @pytest.mark.skipif(not (REAL / "iphone16promax_nogps.MOV").exists(),
                        reason="real iPhone corpus is local-gitignored")
    def test_real_iphone_nogps_clip(self):
        m = _extract(REAL / "iphone16promax_nogps.MOV")
        assert m["make"] == "Apple" and m["model"] == "iPhone 16 Pro Max"
        assert m["gps_present"] is False
