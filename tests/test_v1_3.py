"""v1.3.0 — pure-Python content-based MIME fallback (no libmagic).

With libmagic forced off, the new in-tree magic-signature sniff must produce
content-based MIME for common formats (instead of extension-only), disambiguate
RIFF into webp/wav/avi WITHOUT a spurious polyglot, and still fall through to
extension for text. See docs/v1.3.0_RFC_Specification.md.
"""
import struct

import pytest

from file_observer.scanner import Scanner, ScannerConfig


def _scan_no_libmagic(directory, name, data: bytes):
    (directory / name).write_bytes(data)
    sc = Scanner(source_dir=directory, config=ScannerConfig())
    sc._magic = None  # force the pure-Python fallback path
    return sc.scan().files[0]


def _riff(marker: bytes) -> bytes:
    return b"RIFF" + struct.pack("<I", 64) + marker + b"\x00" * 48


# representative format per signature family; .dat extension proves it's CONTENT,
# not extension, that classified them
_CASES = {
    "image/png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 40,
    "image/gif": b"GIF89a" + b"\x00" * 40,
    "application/gzip": b"\x1f\x8b\x08" + b"\x00" * 40,
    "application/x-bzip2": b"BZh91AY&SY" + b"\x00" * 40,
    "application/x-xz": b"\xfd7zXZ\x00" + b"\x00" * 40,
    "application/x-7z-compressed": b"7z\xbc\xaf\x27\x1c" + b"\x00" * 40,
    "application/zstd": b"\x28\xb5\x2f\xfd" + b"\x00" * 40,
    "application/vnd.rar": b"Rar!\x1a\x07\x00" + b"\x00" * 40,
    "image/tiff": b"II*\x00" + b"\x00" * 40,
    "image/bmp": b"BM" + b"\x00" * 40,
    "application/vnd.sqlite3": b"SQLite format 3\x00" + b"\x00" * 40,
    "application/vnd.apache.parquet": b"PAR1" + b"\x00" * 40,
    "application/x-elf": b"\x7fELF" + b"\x00" * 40,
    "application/vnd.microsoft.portable-executable": b"MZ" + b"\x00" * 40,
    "video/mp4": b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 40,  # ftyp at offset 4
    "video/x-matroska": b"\x1aE\xdf\xa3" + b"\x00" * 40,
    "audio/mpeg": b"ID3\x03\x00" + b"\x00" * 40,
    "audio/flac": b"fLaC\x00\x00" + b"\x00" * 40,
    "audio/ogg": b"OggS\x00\x02" + b"\x00" * 40,
}


@pytest.mark.parametrize("expected,data", list(_CASES.items()))
def test_magic_signature_fallback_content_mime(tmp_path, expected, data):
    rec = _scan_no_libmagic(tmp_path, "blob.dat", data)
    assert rec.mime_type == expected
    assert rec.signal_provenance["mime_type"]["trigger"] == "magic_signature_fallback"


@pytest.mark.parametrize("marker,expected", [
    (b"WEBP", "image/webp"), (b"WAVE", "audio/wav"), (b"AVI ", "video/x-msvideo")])
def test_riff_disambiguation(tmp_path, marker, expected):
    rec = _scan_no_libmagic(tmp_path, "blob.dat", _riff(marker))
    assert rec.mime_type == expected


def test_riff_no_spurious_polyglot(tmp_path):
    # a WAV must match exactly ONE signature (audio/wav), not also a generic RIFF
    rec = _scan_no_libmagic(tmp_path, "blob.dat", _riff(b"WAVE"))
    assert rec.is_polyglot is False
    assert {s["format"] for s in rec.format_signatures} == {"audio/wav"}


def test_renamed_png_detected_by_content(tmp_path):
    # the headline win: content beats a wrong extension
    rec = _scan_no_libmagic(tmp_path, "image.dat", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    assert rec.mime_type == "image/png"


def test_text_falls_through_to_extension(tmp_path):
    rec = _scan_no_libmagic(tmp_path, "notes.txt", b"just plain text, no magic bytes here\n")
    assert rec.signal_provenance["mime_type"]["trigger"] == "extension_fallback"
    assert rec.mime_type == "text/plain"


def test_determinism_same_bytes_same_mime(tmp_path):
    data = b"\x1f\x8b\x08\x00" + b"\x00" * 40
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir(); d2.mkdir()
    m1 = _scan_no_libmagic(d1, "f.dat", data).mime_type
    m2 = _scan_no_libmagic(d2, "f.dat", data).mime_type
    assert m1 == m2 == "application/gzip"


# --- review fixes (PR #?? / scratch/review/v130) ---

class TestProseTextGate:
    """Short ASCII magic prefixes must NOT misclassify ordinary prose as binary
    (the text-gate on _sniff_mime). These FAILED before the gate."""

    @pytest.mark.parametrize("opening", [
        b"BM25 is a ranking function used in search\n",   # was → image/bmp
        b"MZ is a great band from the 90s\n",              # was → application/vnd.microsoft...
        b"ID3 tags store metadata in mp3 files\n",         # was → audio/mpeg
        b"BZh is not how you spell anything\n",            # was → application/x-bzip2
    ])
    def test_prose_not_misclassified_as_binary(self, tmp_path, opening):
        rec = _scan_no_libmagic(tmp_path, "notes.txt", opening)
        assert rec.signal_provenance["mime_type"]["trigger"] == "extension_fallback"
        assert rec.mime_type == "text/plain"


class TestRiffContainerRetained:
    def test_unknown_riff_still_gets_format_signature(self, tmp_path):
        # ACON (animated cursor) — not webp/wav/avi. riff_container is retained
        # for format_signatures continuity; non-MIME so MIME defers to extension.
        rec = _scan_no_libmagic(tmp_path, "x.dat", _riff(b"ACON"))
        assert {s["format"] for s in rec.format_signatures} == {"riff_container"}
        assert rec.is_polyglot is False

    def test_known_riff_subtype_suppresses_generic(self, tmp_path):
        rec = _scan_no_libmagic(tmp_path, "x.dat", _riff(b"WAVE"))
        assert {s["format"] for s in rec.format_signatures} == {"audio/wav"}
        assert rec.is_polyglot is False


def test_empty_constraints_never_match():
    from file_observer.scanner import Scanner
    assert Scanner._signature_matches(b"anything", ()) is None
