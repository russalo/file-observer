"""Capture-metadata adversarial hardening guard (in-house red-team, 2026-06-22).

The v1.16–1.20 capture-metadata arc (image EXIF for JPEG/HEIC, video ISOBMFF container +
QuickTime keys) added the largest untrusted-binary-parsing surface since the PDF arc, but
unlike the PDF arc it never got a dedicated consolidated adversarial pass — only per-release
review catches (v1.16 iloc-count DoS, v1.17 mvhd 2^64 / pre-1970 overflow, v1.18 iinf-order +
truncation guards). This suite codifies the never-crash / stay-bounded / deterministic contract
for those parsers against a battery of hostile inputs, so a future change that drops a bound is
caught. No defect was found when this was written (the per-release discipline held); this guards
it from here.

NOTE (decorrelation): this is the IN-HOUSE leg — adversarial inputs of the author's own
construction. The genuinely decorrelated pass is the bestiary adversarial-corpus fuzzer (its own
project/lane). A clean run here is reassuring, not proof; bestiary is the higher-confidence leg.

Test-only — no behavior/version/schema change.
"""
from __future__ import annotations

import struct
import tempfile
from pathlib import Path

import pytest

import file_observer.scanner as S
from file_observer.scanner import Scanner, ScannerConfig


def _box(typ: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + typ + payload


# ---- direct-parser adversarial vectors: (label, callable) ----
# each must NOT raise and MUST be deterministic; a true hang trips pytest-timeout (120s net).
_PARSER_VECTORS = [
    ("exif_65535_entry_truncated",
     lambda: S._parse_exif_tiff(b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 65535))),
    ("exif_ifd0_offset_max",
     lambda: S._parse_exif_tiff(b"II*\x00" + struct.pack("<I", 0xFFFFFFFF))),
    ("exif_huge_cnt_oob_valoff",
     lambda: S._parse_exif_tiff(b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
                                + struct.pack("<HHI", 0x010F, 2, 0xFFFFFFFF) + struct.pack("<I", 0xFFFFFFF0))),
    ("exif_sub_ifd_ptr_oob",
     lambda: S._parse_exif_tiff(b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
                                + struct.pack("<HHI", 0x8769, 4, 1) + struct.pack("<I", 0xFFFFFF00))),
    ("jpeg_app1_seglen_zero_loop",
     lambda: S._exif_tiff_from_jpeg(b"\xff\xd8" + b"\xff\xe1\x00\x00" * 200 + b"\xff\xda")),
    ("jpeg_app1_seglen_huge",
     lambda: S._exif_tiff_from_jpeg(b"\xff\xd8\xff\xe1\xff\xffExif\x00\x00")),
    ("isobmff_size_zero",
     lambda: list(S._iter_isobmff(b"\x00\x00\x00\x00moov" + b"\x00" * 8))),
    ("isobmff_size_two_tiny",
     lambda: list(S._iter_isobmff(b"\x00\x00\x00\x02moov" + b"\x00" * 8))),
    ("isobmff_64bit_size_2pow63",
     lambda: list(S._iter_isobmff(b"\x00\x00\x00\x01moov" + struct.pack(">Q", 2 ** 63) + b"\x00" * 8))),
    ("isobmff_10k_nested_zero_size",
     lambda: list(S._iter_isobmff((b"\x00\x00\x00\x08free") * 10000))),
    ("moov_huge_msize",
     lambda: S._parse_moov(b"\xff\xff\xff\xffmoov" + b"\x00" * 32)),
    ("moov_truncated",
     lambda: S._parse_moov(b"\x00\x00\x00\x40moovmvhd")),
    ("mvhd_v1_created_2pow64_overflow",
     lambda: S._parse_mvhd(b"\x00\x00\x00\x28mvhd" + bytes([1]) + b"\x00\x00\x00" + b"\xff" * 8
                           + b"\x00" * 4 + b"\x00\x00\x00\x01" + b"\xff" * 8, 0)),
    ("mvhd_v0_created_dur_huge",
     lambda: S._parse_mvhd(b"\x00\x00\x00\x18mvhd\x00\x00\x00\x00" + struct.pack(">III", 1, 1, 0xFFFFFFFE), 0)),
    ("tkhd_truncated",
     lambda: S._parse_tkhd_dims(b"\x00\x00\x00\x5ctkhd\x00" + b"\x00" * 200, 0)),
    ("qt_keys_huge_key_count", None),  # built below (needs a constructed moov buffer)
]


def _qt_keys_huge():
    keys = b"\x00\x00\x10\x00keys\x00\x00\x00\x00" + struct.pack(">I", 0x7FFFFFFF)
    metab = b"hdlr" + keys + b"\x00\x00\x00\x08ilst"
    moovbuf = struct.pack(">I", len(metab) + 16) + b"meta" + b"\x00\x00\x00\x00" + metab
    return S._qt_keys(moovbuf, 0, len(moovbuf))


@pytest.mark.parametrize("label,fn", [(l, f) for l, f in _PARSER_VECTORS if f is not None])
def test_parser_vector_never_crashes_and_deterministic(label, fn):
    r1 = fn()           # must not raise
    r2 = fn()
    assert r1 == r2, f"{label}: non-deterministic"


def test_qt_keys_huge_count_bounded():
    r1, r2 = _qt_keys_huge(), _qt_keys_huge()   # huge n must be bounded by the box, not the count
    assert r1 == r2


# ---- integration: hostile files through the full Scanner (specialists ON) ----
def _hostile_files() -> dict[str, bytes]:
    mvhd = _box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">III", 0, 1000, 5000) + b"\x00" * 80)
    return {
        # moov AT TAIL after a big mdat — exercises the seek-past-mdat read + MOOV_MAX_BYTES
        "tail_moov.mp4": _box(b"ftyp", b"isom") + _box(b"mdat", b"\x00" * 200000) + _box(b"moov", mvhd),
        # 20k nested boxes — iterative walk, must not blow the stack or hang
        "nested.mov": _box(b"ftyp", b"qt  ") + _box(b"moov", _box(b"free") * 20000),
        # HEIC meta/iloc with truncated extents (hostile iloc path)
        "hostile.heic": _box(b"ftyp", b"heic") + _box(b"meta", b"\x00\x00\x00\x00"
                             + _box(b"iinf", b"\x00\x00\x00\x00") + _box(b"iloc", b"\xff" * 40)),
        # JPEG with a 64KB APP1 claiming Exif then garbage
        "bomb.jpg": (b"\xff\xd8\xff\xe1\xff\xfeExif\x00\x00II*\x00" + struct.pack("<I", 8)
                     + struct.pack("<H", 65535) + b"\x00" * 60000 + b"\xff\xda"),
        # huge mdat, no moov → honest null, no crash
        "nomoov.mp4": _box(b"ftyp", b"isom") + _box(b"mdat", b"\xab" * 500000),
    }


# Parametrize on the short NAME only — NOT the bytes. pytest renders param values into the
# test-ID, and on Windows a >32767-char ID blows the env-var limit at setup (matrix-caught).
_HOSTILE = _hostile_files()


@pytest.mark.parametrize("name", list(_HOSTILE))
def test_hostile_file_through_full_scanner(name):
    data = _HOSTILE[name]
    d = Path(tempfile.mkdtemp())
    (d / name).write_bytes(data)
    cfg = ScannerConfig(enable_specialists=True)
    m1 = Scanner(source_dir=d, config=cfg).scan()   # must not crash or hang
    m2 = Scanner(source_dir=d, config=cfg).scan()
    assert m1.manifest_checksum == m2.manifest_checksum, f"{name}: non-deterministic manifest"
