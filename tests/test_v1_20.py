"""v1.20.0 — video QuickTime creation date (`video.creation_date_qt`).

The `video_structure` specialist surfaces `com.apple.quicktime.creationdate` (the capture
moment WITH timezone) as a NEW field, SEPARATE from v1.17's `creation_date` (mvhd, UTC,
file-finalization). Observe-don't-reconcile: both are reported, neither overrides the other
(the AirDrop finding showed they genuinely disagree — mvhd is file-write, the key is the
shutter moment).

Validated against `exiftool` on the real iPhone corpus (gitignored); a synthetic fixture
(`video_qt_gps.mov`, fabricated key) exercises it in CI.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import file_observer.scanner as fo
from file_observer.scanner import (
    Scanner, ScannerConfig, SPECIALIST_FIELDS,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)

GEN = Path(__file__).parent / "fixtures" / "generated"
GPS = GEN / "video_qt_gps.mov"
VID = Path(__file__).parent.parent / "scratch" / "v1_18_corpus" / "video"


def test_release_version_surfaces():
    def _v(x): return tuple(int(p) for p in x.split("."))
    assert _v(SCANNER_VERSION) >= (1, 20, 0), f"SCANNER regressed: {SCANNER_VERSION!r}"
    assert _v(LOGIC_VERSION) >= (1, 10, 0), f"LOGIC regressed: {LOGIC_VERSION!r}"
    assert _v(SCHEMA_VERSION) >= (1, 13), f"SCHEMA regressed: {SCHEMA_VERSION!r}"


def _extract(path):
    sc = Scanner(source_dir=path.parent, config=ScannerConfig(enable_specialists=True))
    with open(path, "rb") as fh:        # read only the 8 KB head, not the whole clip (leg-4)
        sample = fh.read(8192)
    return sc.extract_specialist_metadata(path, path.suffix.lower(), sample)


class TestField:
    def test_field_registered(self):
        assert "creation_date_qt" in SPECIALIST_FIELDS["video"]

    def test_extracted_from_key(self):
        m = _extract(GPS)
        assert m["creation_date_qt"] == "2024-01-01T00:00:00-0800"   # the fabricated fixture key

    def test_separate_from_mvhd_creation_date(self):
        # the two are DISTINCT fields, never merged (observe-don't-reconcile)
        m = _extract(GPS)
        assert m["creation_date"] is not None          # v1.17 mvhd field still set
        assert m["creation_date_qt"] is not None        # v1.20 key field set
        assert m["creation_date"] != m["creation_date_qt"]   # different sources, different values

    def test_v17_creation_date_unchanged(self):
        # v1.17's creation_date must be exactly the mvhd-derived UTC value, untouched
        m = _extract(GPS)
        assert m["creation_date"].endswith("Z")         # mvhd → UTC

    def test_timezone_preserved_as_is(self):
        # the key carries an offset — surfaced raw (not normalized to UTC)
        m = _extract(GPS)
        assert "-0800" in m["creation_date_qt"]


class TestAbsent:
    def test_no_key_yields_none(self):
        # a moov with make/model keys but NO creationdate key → creation_date_qt is None
        import struct
        def box(t, b): return struct.pack(">I", 8 + len(b)) + t + b
        ks = [b"com.apple.quicktime.make"]
        kb = b"\x00\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">I", 8 + len(ks[0])) + b"mdta" + ks[0]
        data = box(b"data", struct.pack(">II", 1, 0) + b"TestMake")
        ilst = struct.pack(">I", 8 + len(data)) + struct.pack(">I", 1) + data
        meta = box(b"meta", box(b"keys", kb) + box(b"ilst", ilst))
        mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 3658232843, 0, 600, 3000) + b"\x00" * 80)
        moov = box(b"moov", mvhd + meta)
        out = fo._parse_moov(moov)
        assert out["make"] == "TestMake"
        assert out["creation_date_qt"] is None
        assert out["creation_date"] is not None   # mvhd still parsed


class TestDeterminism:
    def test_workers_byte_identical(self, tmp_path):
        (tmp_path / "v.mov").write_bytes(GPS.read_bytes())
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        m4 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.manifest_checksum == m4.manifest_checksum


class TestRealCorpus:
    @pytest.mark.skipif(not (VID / "iphone11_gps.MOV").exists(),
                        reason="real iPhone corpus is local-gitignored")
    @pytest.mark.parametrize("name,expected_qt", [
        ("iphone11_gps.MOV", "2026-06-16T05:25:55-0700"),
        ("iphone16promax_gps.MOV", "2026-06-15T18:23:28-0700"),
    ])
    def test_real_clip_qt_matches_exiftool(self, name, expected_qt):
        m = _extract(VID / name)
        assert m["creation_date_qt"] == expected_qt          # matches exiftool Keys CreationDate
        assert m["creation_date"] != m["creation_date_qt"]   # mvhd genuinely differs
