"""v1.25.0 — Audio (.mp3) + legacy presentation (.ppt) extraction (Candidate B, phase 2).

Falsify-first: written to FAIL against v1.24.0, pass once v1.25.0 lands.

- `.mp3` → new `audio` namespace: ID3v2 tags (title/artist/album/year) + a bounded
  MPEG frame-header parse (format/bitrate/duration_s; Xing VBR or CBR estimate).
- `.ppt` → extends `presentation` via OLE2 SummaryInformation +
  DocumentSummaryInformation (title/author/application/slide_count).

The `.mp3` parser is the lone net-new untrusted-binary surface — never-crash /
bounded / deterministic is asserted here (the v1.8.1 discipline) and extended in
tests/test_capture_metadata_hardening.py.
"""
import struct
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig, SPECIALIST_TOOLS,
    SPECIALIST_NAMESPACE, SPECIALIST_FIELDS, SPECIALIST_MIME_GUARD,
    PROVISIONAL_SPECIALIST_FIELDS, SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
    olefile,
)

GENERATED = Path(__file__).parent / "fixtures" / "generated"


# ---- MP3 fixture builders (raw bytes — license-clean, spec-accurate) ----------

def _mpeg1_layer3_header() -> bytes:
    # 0xFF 0xFB 0x90 0x00 = sync + MPEG1 + Layer III + no-CRC; bitrate idx 9 (128 kbps),
    # sample-rate idx 0 (44100 Hz), no padding; channel mode stereo.
    return b"\xff\xfb\x90\x00"


def _id3v2(title=None, artist=None, album=None, year=None) -> bytes:
    """A minimal ID3v2.3 tag (plain 32-bit frame sizes; UTF-8 text frames)."""
    def frame(fid: bytes, text: str) -> bytes:
        payload = b"\x03" + text.encode("utf-8")  # encoding byte 3 = UTF-8
        return fid + struct.pack(">I", len(payload)) + b"\x00\x00" + payload
    body = b""
    if title:  body += frame(b"TIT2", title)
    if artist: body += frame(b"TPE1", artist)
    if album:  body += frame(b"TALB", album)
    if year:   body += frame(b"TYER", year)
    size = len(body)
    ss = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    return b"ID3\x03\x00\x00" + ss + body


def _cbr_mp3(audio_bytes: int = 16000, **tags) -> bytes:
    """CBR: ID3 tag + a 128 kbps frame padded to `audio_bytes`. With 16000 audio
    bytes, duration = 16000*8/(128*1000) = 1.0 s exactly."""
    frame = _mpeg1_layer3_header() + b"\x00" * (audio_bytes - 4)
    return _id3v2(**tags) + frame


def _vbr_mp3(frame_count: int = 1000, **tags) -> bytes:
    """VBR: a Xing header at offset 36 (MPEG1, non-mono) declaring `frame_count`.
    duration = frame_count*1152/44100."""
    pre = _mpeg1_layer3_header() + b"\x00" * (36 - 4)
    xing = b"Xing" + struct.pack(">I", 0x01) + struct.pack(">I", frame_count)  # flags=frames
    return _id3v2(**tags) + pre + xing + b"\x00" * 256


def _scan_one(tmp_path: Path, name: str, data: bytes):
    (tmp_path / name).write_bytes(data)
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    return next(f for f in m.files if f.filename == name)


# ---- wiring -------------------------------------------------------------------

def test_extensions_registered():
    # Routing lives in SPECIALIST_TOOLS/NAMESPACE (drives requires_specialist_tool);
    # SUPPORTED_EXTENSIONS is intentionally NOT extended (content-recognized, v1.24 precedent).
    assert SPECIALIST_TOOLS[".mp3"] == "audio_structure"
    assert SPECIALIST_TOOLS[".ppt"] == "presentation_structure"
    assert SPECIALIST_NAMESPACE[".mp3"] == "audio"
    assert SPECIALIST_NAMESPACE[".ppt"] == "presentation"


def test_audio_namespace_surface():
    fields = set(SPECIALIST_FIELDS["audio"])
    assert {"format", "bitrate", "duration_s", "title", "artist", "album", "year"} <= fields
    # the whole audio namespace is provisional on arrival
    for f in ("format", "bitrate", "duration_s", "title", "artist", "album", "year"):
        assert ("audio", f) in PROVISIONAL_SPECIALIST_FIELDS


def test_audio_mime_guard_is_tight():
    assert SPECIALIST_MIME_GUARD["audio"] == {"audio/mpeg"}  # decision §9.3: TIGHT


# ---- .mp3 extraction ----------------------------------------------------------

def test_mp3_cbr_tags_and_properties(tmp_path):
    rec = _scan_one(tmp_path, "song.mp3", _cbr_mp3(
        title="Test Title", artist="Test Artist", album="Test Album", year="2024"))
    assert rec.requires_specialist_tool is True
    a = rec.specialist_metadata["audio"]
    assert a["title"] == "Test Title"
    assert a["artist"] == "Test Artist"
    assert a["album"] == "Test Album"
    assert a["year"] == "2024"
    assert a["format"] == "mp3"
    assert a["bitrate"] == 128
    assert a["duration_s"] == 1.0


def test_mp3_vbr_xing_duration(tmp_path):
    rec = _scan_one(tmp_path, "vbr.mp3", _vbr_mp3(frame_count=1000, title="V"))
    a = rec.specialist_metadata["audio"]
    assert a["format"] == "mp3"
    assert a["duration_s"] == round(1000 * 1152 / 44100, 2)  # 26.12 — Xing, not CBR


def test_mp3_no_tags_still_reads_frame(tmp_path):
    # no ID3 tag — extension MIME (audio/mpeg) carries it; frame still parses.
    rec = _scan_one(tmp_path, "bare.mp3", _cbr_mp3())
    a = rec.specialist_metadata["audio"]
    assert a["format"] == "mp3" and a["bitrate"] == 128
    assert a["title"] is None  # honest null — no tag present


def test_mp3_garbage_is_honest_null_not_crash(tmp_path):
    # text-typed garbage with an .mp3 name → tight guard skips it; scan completes.
    rec = _scan_one(tmp_path, "fake.mp3", b"not audio at all, just prose " * 50)
    sm = rec.specialist_metadata
    assert sm is None or sm.get("audio") is None or sm["audio"]["format"] is None


def test_mp3_lying_id3_size_never_crashes(tmp_path):
    # ID3 header claims a huge tag size but the file is tiny — must not over-read / hang.
    hostile = b"ID3\x03\x00\x00\x7f\x7f\x7f\x7f" + b"\x00" * 32
    rec = _scan_one(tmp_path, "hostile.mp3", hostile)
    assert rec is not None  # scan completed, no raise


# ---- .ppt extraction (OLE2) ---------------------------------------------------

@pytest.mark.skipif(olefile is None, reason="olefile not installed")
def test_ppt_ole2_metadata(tmp_path):
    fixture = GENERATED / "generated.ppt"
    assert fixture.exists(), "run tests/fixtures/generated/generate.py"
    rec = _scan_one(tmp_path, "deck.ppt", fixture.read_bytes())
    assert rec.requires_specialist_tool is True
    p = rec.specialist_metadata["presentation"]
    assert p["title"] == "File Observer Test Deck"
    assert p["author"] == "File Observer Test"
    assert p["application"] == "Microsoft PowerPoint"
    assert p["slide_count"] == 7


# ---- determinism --------------------------------------------------------------

def test_workers_byte_identical(tmp_path):
    (tmp_path / "a.mp3").write_bytes(_cbr_mp3(title="A"))
    (tmp_path / "b.mp3").write_bytes(_vbr_mp3(title="B"))
    if olefile is not None and (GENERATED / "generated.ppt").exists():
        (tmp_path / "c.ppt").write_bytes((GENERATED / "generated.ppt").read_bytes())
    cfg1 = ScannerConfig(enable_specialists=True, workers=1)
    cfg2 = ScannerConfig(enable_specialists=True, workers=2)
    m1 = Scanner(source_dir=tmp_path, config=cfg1).scan()
    m2 = Scanner(source_dir=tmp_path, config=cfg2).scan()
    assert m1.manifest_checksum == m2.manifest_checksum


# ---- version surfaces (exact pins — falsify-first, fails until the bump) -------

def test_version_surfaces():
    assert SCANNER_VERSION == "1.25.0"
    assert LOGIC_VERSION == "1.14.0"
    assert SCHEMA_VERSION == "1.16"
