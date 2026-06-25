"""v1.23.3 — bzip2 dual-magic MIME sniff + the `_OneOf` byte-alternation matcher (falsify-first).

FO's bzip2 signature required the compressed-BLOCK magic ("1AY&SY" = 0x314159265359) at offset 4,
so a data-less bzip2 (`bz2.compress(b"")`) — which carries the END-OF-STREAM magic (0x177245385090)
at offset 4 instead — was a false-negative (sniffed None). v1.23.3 accepts EITHER magic at offset 4
via a new `_OneOf` alternation matcher, plus the block-size level digit '1'-'9' at offset 3:
  - normal bzip2 (block magic @4) -> application/x-bzip2
  - empty  bzip2 (EOS magic @4)   -> application/x-bzip2   (was None — THE FIX)
  - prose "BZh9 is the max..."     -> rejected (the offset-4 6-byte magic carries prose-rejection;
                                      offset-3-digit ALONE would FP here — the puresniff catch)
  - invalid level "BZhX1AY&SY"     -> rejected (offset-3 digit guard)
Reconciled 0/0 with the puresniff clean-room replica. SCANNER 1.23.2->1.23.3; LOGIC 1.12.3->1.12.4;
SCHEMA unchanged 1.14.
"""
from __future__ import annotations

import bz2
import tempfile
from pathlib import Path

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    _OneOf,
)


def _sc():
    return Scanner(source_dir=Path(tempfile.gettempdir()), config=ScannerConfig())


def test_version_surfaces():
    assert tuple(map(int, SCANNER_VERSION.split("."))) >= (1, 23, 3), SCANNER_VERSION  # floor
    assert tuple(map(int, LOGIC_VERSION.split("."))) >= (1, 12, 4), LOGIC_VERSION  # floor
    assert tuple(map(int, SCHEMA_VERSION.split("."))) >= (1, 14), SCHEMA_VERSION  # floor (superseded per-release pin; later minors raise SCHEMA)


def test_empty_bzip2_now_recognized():
    raw = bz2.compress(b"", 9)                       # data-less → end-of-stream magic at offset 4
    assert raw[4:10] == b"\x17rE8P\x90"              # ground: EOS magic, NOT the block magic
    assert _sc()._sniff_mime(raw) == "application/x-bzip2"   # THE FIX: was None pre-v1.23.3


def test_normal_bzip2_still_recognized():
    raw = bz2.compress(b"hello world" * 100, 9)
    assert raw[4:10] == b"1AY&SY"                    # block magic
    assert _sc()._sniff_mime(raw) == "application/x-bzip2"


def test_bzip2_digit_prose_rejected():
    # the digit-prose FP the puresniff replica caught: offset-3-digit ALONE would mis-type these;
    # the offset-4 6-byte magic requirement rejects them.
    assert _sc()._sniff_mime(b"BZh9 is the max bzip2 compression level") != "application/x-bzip2"
    assert _sc()._sniff_mime(b"BZh1 selects a 100kB block") != "application/x-bzip2"


def test_bzip2_invalid_level_rejected():
    # BZh + non-digit level byte + a real block magic → rejected by the offset-3 digit guard.
    assert _sc()._sniff_mime(b"BZhX1AY&SY" + b"\x00" * 8) != "application/x-bzip2"


def test_oneof_matcher_alternation():
    # _OneOf in the PATTERN slot at a fixed int offset matches ANY option, else None.
    cons = ((0, b"AB"), (2, _OneOf(b"XX", b"YY")))
    assert Scanner._signature_matches(b"ABXX..", cons) is not None
    assert Scanner._signature_matches(b"ABYY..", cons) is not None
    assert Scanner._signature_matches(b"ABZZ..", cons) is None


def test_bzip2_full_scan_deterministic():
    d = Path(tempfile.mkdtemp())
    (d / "empty.bz2").write_bytes(bz2.compress(b"", 9))
    m1 = Scanner(source_dir=d, config=ScannerConfig()).scan()
    m2 = Scanner(source_dir=d, config=ScannerConfig()).scan()
    assert m1.manifest_checksum == m2.manifest_checksum
