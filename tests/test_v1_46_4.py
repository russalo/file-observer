"""v1.46.4 (patch) — recognize macOS-universal metadata by magic (MacBook Neo APFS shakedown finding).

.DS_Store (Bud1) and ._* (AppleDouble) appear in nearly every macOS directory; libmagic types both
application/octet-stream, so the v1.22 recognition gate flagged them `unsupported_extension` on every
Mac corpus scan (error-record spray). A magic match IS a positive content ID, so they now count as
identified even when libmagic shrugs — while a genuine unknown binary STILL flags (the control).

Falsify-first vs 1.46.3. Recognition change → unsupported_extension flips + format_signatures gains
the label → LOGIC 1.24.2→1.24.3; SCHEMA frozen.
"""
from __future__ import annotations

from pathlib import Path

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
)

DSSTORE = b"\x00\x00\x00\x01Bud1" + b"\x00" * 64          # Bud1 (.DS_Store)
APPLEDOUBLE = b"\x00\x05\x16\x07" + b"\x00" * 60          # AppleDouble (._*)


def _rec(tmp_path: Path, name: str, data: bytes):
    (tmp_path / name).write_bytes(data)
    m = Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan()
    return m, next(f for f in m.files if f.path == name)


def _unsupported(f) -> bool:
    return any(e.code == "unsupported_extension" for e in (f.errors or []))


def test_dsstore_recognized(tmp_path: Path):
    m, f = _rec(tmp_path, ".DS_Store", DSSTORE)
    assert not _unsupported(f), ".DS_Store must be recognized (was unsupported_extension)"
    assert any(x["format"] == "application/x-apple-dsstore" for x in (f.format_signatures or []))
    assert m.quality.error_files == 0


def test_appledouble_recognized(tmp_path: Path):
    # a no-extension AppleDouble (._foo) is the case that WAS flagged (an extensioned ._x.txt has a
    # supported extension already); it must now be recognized by magic.
    m, f = _rec(tmp_path, "._foo", APPLEDOUBLE)
    assert not _unsupported(f)
    assert any(x["format"] == "application/applefile" for x in (f.format_signatures or []))
    assert m.quality.error_files == 0   # quality-clean: no OTHER error record regressed the fix


def test_recognition_deterministic_across_workers(tmp_path: Path):
    # the new recognition-gate arm must be worker-invariant (serial vs process pool → same manifest).
    (tmp_path / ".DS_Store").write_bytes(DSSTORE)
    (tmp_path / "._foo").write_bytes(APPLEDOUBLE)
    (tmp_path / "normal.txt").write_text("hello\n", encoding="utf-8")
    c1 = Scanner(tmp_path, ScannerConfig(enable_specialists=True, workers=1)).scan().manifest_checksum
    c2 = Scanner(tmp_path, ScannerConfig(enable_specialists=True, workers=2)).scan().manifest_checksum
    assert c1 == c2


def test_genuine_unknown_still_flags(tmp_path: Path):
    # CONTROL: the fix must NOT over-broaden — a real unidentified binary still flags unsupported.
    _m, f = _rec(tmp_path, "mystery.xyz", b"\x01\x02\x03\x04not a known format\n")
    assert _unsupported(f), "a genuine unknown binary must STILL flag unsupported_extension"
