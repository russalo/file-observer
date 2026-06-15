"""v1.17.0 — video capture-metadata (container/track half).

A new `video_structure` specialist reads MP4/MOV/M4V container metadata from the ISOBMFF
box tree (`moov`/`mvhd`/`trak`/`tkhd`/`hdlr`/`stsd`), stdlib + `struct`, no library:
`codec` / `duration_s` / `width` / `height` / `creation_date`. `moov` is read by scanning
top-level boxes and seeking past `mdat` (it's usually at the tail — measured 61/62 real
.mov), bounded by MOOV_MAX_BYTES.

The container/track fields were oracle-validated against `exiftool` on 62 real .mov
(61/61 exact parity on codec + dims + creation_date). The Apple QuickTime keys
(make/model) + GPS-presence are GATED on a real iPhone-.mov corpus (the conformance files
carry none) and land as an additive follow-up — not in this release.

Fixture: tests/fixtures/generated/video_h264.mov (self-authored, moov-at-tail).
"""
from __future__ import annotations

from pathlib import Path

import pytest

import file_observer.scanner as fo
from file_observer.scanner import (
    Scanner, ScannerConfig,
    SPECIALIST_TOOLS, SPECIALIST_NAMESPACE, SPECIALIST_FIELDS,
    SPECIALIST_MIME_GUARD, SUPPORTED_EXTENSIONS,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)

GEN = Path(__file__).parent / "fixtures" / "generated"
MOV = GEN / "video_h264.mov"
VIDEO_EXTS = (".mp4", ".mov", ".m4v")


def test_release_version_surfaces():
    # v1.17.0 is the newest release — exact current-version pins.
    assert SCANNER_VERSION == "1.17.0", f"got {SCANNER_VERSION!r}"
    assert LOGIC_VERSION == "1.7.0", f"LOGIC: {LOGIC_VERSION!r}"     # new extraction surface
    assert SCHEMA_VERSION == "1.11", f"SCHEMA: {SCHEMA_VERSION!r}"   # additive video namespace


# --------------------------------------------------------------------------- registries
class TestRegistries:
    @pytest.mark.parametrize("ext", VIDEO_EXTS)
    def test_routed_to_video_specialist(self, ext):
        assert SPECIALIST_TOOLS[ext] == "video_structure"
        assert SPECIALIST_NAMESPACE[ext] == "video"
        assert ext in SUPPORTED_EXTENSIONS

    def test_video_fields_declared(self):
        assert SPECIALIST_FIELDS["video"] == [
            "codec", "duration_s", "width", "height", "creation_date"]

    def test_video_mime_guard(self):
        assert {"video/mp4", "video/quicktime"} <= SPECIALIST_MIME_GUARD["video"]


# --------------------------------------------------------------------------- extraction
class TestExtraction:
    @pytest.fixture(scope="class")
    def meta(self):
        sc = Scanner(source_dir=GEN, config=ScannerConfig(enable_specialists=True))
        return sc.extract_specialist_metadata(MOV, ".mov", MOV.read_bytes()[:8192])

    def test_codec(self, meta):
        assert meta["codec"] == "avc1"

    def test_dimensions(self, meta):
        assert (meta["width"], meta["height"]) == (1920, 1080)

    def test_duration_float_seconds(self, meta):
        assert meta["duration_s"] == 5.0   # 3000 / 600

    def test_creation_date_iso_utc(self, meta):
        # QuickTime epoch (1904) → ISO 8601 UTC
        assert meta["creation_date"] == "2019-12-03T15:47:23Z"

    def test_moov_at_tail_is_found(self, meta):
        # the fixture puts moov AFTER mdat — extraction proves the tail-scan works
        assert meta["codec"] is not None


# --------------------------------------------------------------------------- full scan
class TestThroughScan:
    def test_scan_routes_and_extracts(self, tmp_path):
        (tmp_path / "clip.mov").write_bytes(MOV.read_bytes())
        m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        rec = next(f for f in m.files if f.filename == "clip.mov")
        assert rec.specialist_tool == "video_structure"
        assert rec.specialist_metadata["video"]["codec"] == "avc1"
        assert rec.requires_specialist_tool is True

    def test_provenance_declares_deviation(self, tmp_path):
        # moov is read beyond the 8 KB sample → declared deviation, not bounded_sample
        (tmp_path / "clip.mov").write_bytes(MOV.read_bytes())
        m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        rec = next(f for f in m.files if f.filename == "clip.mov")
        prov = rec.signal_provenance["specialist_metadata.video.codec"]
        assert prov["trigger"] == "bounded_deviation"
        assert prov["detail"]["reason"] == "moov_box_beyond_sample"


# --------------------------------------------------------------------------- robustness
class TestRobustness:
    @pytest.fixture
    def scanner(self, tmp_path_factory):
        return Scanner(source_dir=tmp_path_factory.mktemp("v117"),
                       config=ScannerConfig(enable_specialists=True))

    @pytest.mark.parametrize("garbage", [b"", b"\x00\x00\x00\x08ftyp", b"not a video", b"\x00" * 80])
    def test_garbage_never_crashes(self, scanner, garbage, tmp_path):
        p = tmp_path / "g.mov"
        p.write_bytes(garbage)
        meta = scanner._extract_video_metadata(p, garbage)
        assert meta is not None and meta["codec"] is None   # honest null, no crash

    def test_no_moov_returns_nulls(self, scanner, tmp_path):
        # ftyp + mdat only, no moov
        import struct
        def box(t, b): return struct.pack(">I", 8 + len(b)) + t + b
        p = tmp_path / "nomoov.mov"
        p.write_bytes(box(b"ftyp", b"qt  " + b"\x00" * 8) + box(b"mdat", b"\x00" * 32))
        meta = scanner._extract_video_metadata(p, b"")
        assert meta["codec"] is None and meta["creation_date"] is None

    def test_oversize_moov_rejected(self, scanner, tmp_path):
        # a moov claiming > MOOV_MAX_BYTES must be refused (bounded), not read
        import struct
        big = struct.pack(">I", scanner.MOOV_MAX_BYTES + 1) + b"moov" + b"\x00" * 16
        p = tmp_path / "huge.mov"
        p.write_bytes(struct.pack(">I", 16) + b"ftyp" + b"qt  " + b"\x00" * 4 + big)
        assert scanner._read_moov(p) is None

    def test_v1_mvhd_unset_duration_is_null(self):
        # leg-1 #1: a version-1 mvhd with the 64-bit "unset" duration sentinel
        # (0xFFFFFFFFFFFFFFFF) must yield duration_s=None, NOT a ~3e16 garbage value.
        import struct
        # mvhd v1: vf(4)=01.. + created(8) + mod(8) + timescale(4) + duration(8) + tail
        body = (b"\x01\x00\x00\x00" + struct.pack(">Q", 3658232843) + struct.pack(">Q", 0)
                + struct.pack(">I", 600) + struct.pack(">Q", 0xFFFFFFFFFFFFFFFF) + b"\x00" * 20)
        mvhd = struct.pack(">I", 8 + len(body)) + b"mvhd" + body
        out = fo._parse_mvhd(mvhd, 0)
        assert out["duration_s"] is None              # not 3.07e16
        assert out["creation_date"] == "2019-12-03T15:47:23Z"   # v1 created still parsed

    def test_truncated_mvhd_is_null_not_wrong(self):
        # leg-4/Gemini: a truncated mvhd (version byte present, duration slice short) must
        # yield None — NOT a wrong value from int.from_bytes silently accepting fewer bytes.
        import struct
        # v0 mvhd header + only created+mod+timescale, duration slice truncated
        body = b"\x00\x00\x00\x00" + struct.pack(">III", 3658232843, 0, 600)  # missing duration
        mvhd = struct.pack(">I", 8 + len(body)) + b"mvhd" + body
        out = fo._parse_mvhd(mvhd, 0)
        assert out["duration_s"] is None      # bounds guard bailed; no short-slice garbage
        assert out["creation_date"] is None    # whole branch bailed (o+28 > len)

    def test_pre_1970_creation_date_platform_independent(self):
        # leg-1 #2: a 1904-epoch creation time before 1970 (negative POSIX ts) must
        # convert via timedelta, identically on every platform (no fromtimestamp).
        import struct
        # created = 1000s after 1904-01-01 → 1904-01-01T00:16:40Z (well before 1970)
        body = b"\x00\x00\x00\x00" + struct.pack(">IIII", 1000, 0, 600, 600) + b"\x00" * 80
        mvhd = struct.pack(">I", 8 + len(body)) + b"mvhd" + body
        out = fo._parse_mvhd(mvhd, 0)
        assert out["creation_date"] == "1904-01-01T00:16:40Z"

    def test_truncated_moov_no_crash(self, scanner, tmp_path):
        # moov header claims a size but body is truncated
        import struct
        def box(t, b): return struct.pack(">I", 8 + len(b)) + t + b
        ftyp = box(b"ftyp", b"qt  " + b"\x00" * 8)
        moov_hdr = struct.pack(">I", 4096) + b"moov" + b"\x00" * 20  # claims 4096, has ~28
        p = tmp_path / "trunc.mov"
        p.write_bytes(ftyp + moov_hdr)
        meta = scanner._extract_video_metadata(p, b"")
        assert meta["codec"] is None   # no crash


# --------------------------------------------------------------------------- determinism
class TestDeterminism:
    def test_workers_byte_identical(self, tmp_path):
        for n in ("a", "b", "c"):
            (tmp_path / f"{n}.mov").write_bytes(MOV.read_bytes())
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        m4 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.manifest_checksum == m4.manifest_checksum
