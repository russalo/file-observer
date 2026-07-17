"""v1.46.5 (patch) — never-crash: a numeric-typed EXIF make/model no longer aborts the scan.

bestiary soak #165 (decorrelated, spec-derived): an EXIF make/model tag with a NUMERIC TIFF type
(SHORT/LONG, not ASCII) made fo store an int; `_build_summary` then did `.strip()` on it →
unhandled AttributeError that aborted the WHOLE scan (corpus-level: one bad .jpg crashed a whole dir),
with NO per-file ErrorRecord — a never-crash breach.

Two-layer fix (falsify-first vs 1.46.4):
  ROOT CAUSE — `_parse_exif_tiff` type-gates: make/model/datetime are ASCII (TIFF type 2) by spec, so a
                numeric-typed tag → None, never an int (orientation stays the one numeric SHORT field).
  DEFENSE     — `_build_summary` only lets string make/model contribute to a device label, so the
                AGGREGATE path can never abort on an unexpected non-string in specialist_metadata.
LOGIC 1.24.3→1.24.4 (a value changes only on a malformed EXIF file → NO-DRIFT on real corpora); SCHEMA frozen.
"""
from __future__ import annotations

import struct
from pathlib import Path

from file_observer.scanner import (
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
    _parse_exif_tiff,
)


def _tiff(tag: int, typ: int, value_bytes: bytes) -> bytes:
    # minimal little-endian TIFF/EXIF: header + IFD0 with one entry (value inline, padded to 4 bytes)
    entry = struct.pack("<HHI", tag, typ, 1) + (value_bytes + b"\x00\x00\x00\x00")[:4]
    ifd = struct.pack("<H", 1) + entry + struct.pack("<I", 0)
    return b"II" + struct.pack("<H", 42) + struct.pack("<I", 8) + ifd


def _jpeg_numeric_make() -> bytes:
    tiff = _tiff(0x010F, 3, struct.pack("<H", 1234))          # make (0x010F) as SHORT — the malformed case
    app1_payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(app1_payload) + 2) + app1_payload
    sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", 4, 4) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + app1 + sof + b"\xff\xd9"


def test_numeric_make_not_stored_as_int():
    exif = _parse_exif_tiff(_tiff(0x010F, 3, struct.pack("<H", 1234)))  # make as SHORT
    assert exif is None or exif.get("make") is None, "make must be str|None, never an int"


def test_ascii_make_still_extracted():
    exif = _parse_exif_tiff(_tiff(0x010F, 2, b"AB"))                    # make as ASCII (type 2)
    assert exif and isinstance(exif.get("make"), str)                  # ASCII path unbroken


def test_orientation_still_numeric():
    exif = _parse_exif_tiff(_tiff(0x0112, 3, struct.pack("<H", 6)))    # orientation as SHORT
    assert exif and exif.get("orientation") == 6                      # the legit numeric field survives


def test_scan_survives_numeric_make_jpeg_corpus(tmp_path: Path):
    # the corpus-level never-crash: a bad .jpg + good files → the WHOLE scan must complete, all files
    # observed, NO whole-scan abort (bestiary #165 crashed the dir before this fix).
    d = tmp_path
    (d / "bad.jpg").write_bytes(_jpeg_numeric_make())
    (d / "good1.txt").write_text("hello\n", encoding="utf-8")
    (d / "good2.md").write_text("# ok\n", encoding="utf-8")
    m = Scanner(d, ScannerConfig(enable_specialists=True)).scan()      # must NOT raise
    paths = {f.path for f in m.files}
    assert paths == {"bad.jpg", "good1.txt", "good2.md"}
    bad = next(f for f in m.files if f.path == "bad.jpg")
    img = (bad.specialist_metadata or {}).get("image") or {}
    assert not isinstance(img.get("make"), int)                        # never an int
    assert isinstance(m.summary, str)                                  # the summary built (didn't abort)


def test_version_axes():
    assert SCANNER_VERSION == "1.46.5"
    assert LOGIC_VERSION == "1.24.4"   # malformed-EXIF value change (NO-DRIFT on real corpora)
    assert SCHEMA_VERSION == "1.23"
