"""v1.22 — content-aware recognition for BINARY (falsify-first).

v1.22 completes the v1.21 arc: `unsupported_extension` no longer fires when a file's
CONTENT is positively identified — text (v1.21) OR binary (v1.22). It fires ONLY when
content detection genuinely failed: octet-stream, an extension-fallback MIME (both content
tiers failed), or unreadable. Recognition-only — NO new extraction, NO new field, byte-
identical specialist output. LOGIC 1.11.0→1.12.0; SCHEMA unchanged (1.13).

The falsifiable contracts (write the adversarial cases first; try to break the premise):
  - a positively-identified BINARY (real content MIME) is recognized, counted supported;
  - genuinely-unidentified (octet-stream) still fires the diagnostic;
  - an extension-fallback MIME still fires (recognition rests on CONTENT, not /etc/mime.types);
  - text behavior is byte-identical to v1.21 (the lying-text/plain veto is untouched);
  - recognition != extraction (a recognized binary gets no specialist, no metadata);
  - workers=1-vs-N byte-identical.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_EXTENSIONS,
    ERR_UNSUPPORTED_EXTENSION,
)

UNLISTED = ".zzz"   # an extension deliberately NOT in SUPPORTED_EXTENSIONS


def _scan_one(path: Path, no_magic: bool = False):
    cfg = ScannerConfig(enable_specialists=True)
    sc = Scanner(source_dir=path.parent, config=cfg)
    if no_magic:
        sc._magic = None  # force the pure-Python sniff / extension-fallback path
    m = sc.scan()
    return m, next(r for r in m.files if r.filename == path.name)


def _flagged(rec) -> bool:
    return any(e.code == ERR_UNSUPPORTED_EXTENSION for e in (rec.errors or []))


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    return buf.getvalue()


def test_version_surfaces():
    assert SCANNER_VERSION == "1.22.0", f"got {SCANNER_VERSION!r}"
    assert LOGIC_VERSION == "1.12.0", f"LOGIC: {LOGIC_VERSION!r}"   # recognition routing change
    assert SCHEMA_VERSION == "1.13", f"SCHEMA: {SCHEMA_VERSION!r}"  # unchanged — no new field


def test_unlisted_ext_is_actually_unlisted():
    assert UNLISTED not in SUPPORTED_EXTENSIONS  # guard: the gate is only meaningful if unlisted


class TestBinaryRecognized:
    def test_identified_binary_not_flagged(self, tmp_path):
        # a real ZIP (libmagic -> application/zip, a content signature match) with an UNLISTED ext
        f = tmp_path / f"archive{UNLISTED}"
        f.write_bytes(_zip_bytes())
        _, rec = _scan_one(f)
        assert rec.mime_type == "application/zip", f"precondition: libmagic IDs zip (got {rec.mime_type})"
        assert not _flagged(rec), "v1.22: an identified binary must NOT be unsupported_extension"

    def test_identified_binary_counts_supported(self, tmp_path):
        (tmp_path / f"a{UNLISTED}").write_bytes(_zip_bytes())
        m, _ = _scan_one(tmp_path / f"a{UNLISTED}")
        # one file, identified -> supported, none unsupported
        assert m.stats.unsupported_files == 0
        assert m.stats.supported_files == m.stats.total_files

    def test_recognition_is_not_extraction(self, tmp_path):
        # a recognized binary gets NO specialist + NO new metadata (recognition != extraction)
        f = tmp_path / f"clip{UNLISTED}"
        f.write_bytes(_zip_bytes())
        _, rec = _scan_one(f)
        assert rec.requires_specialist_tool is False
        assert rec.specialist_tool is None
        # zip-as-unlisted is recognized but not extracted: no specialist namespace populated
        assert not (rec.specialist_metadata or {})


class TestStillFlagged:
    def test_octet_stream_still_flagged(self, tmp_path):
        # NUL-heavy bytes with no signature -> octet-stream -> genuinely unidentified
        f = tmp_path / f"blob{UNLISTED}"
        f.write_bytes(b"\x00\x01\x02\x03" * 64 + b"\xff" * 64)
        _, rec = _scan_one(f)
        assert rec.mime_type == "application/octet-stream", f"precondition (got {rec.mime_type})"
        assert _flagged(rec), "octet-stream must still fire unsupported_extension"

    def test_extension_fallback_still_flagged(self, tmp_path):
        # no-libmagic path: content sniff can't match, MIME comes ONLY from the extension
        # (/etc/mime.types) -> recognition must rest on CONTENT, so it STAYS flagged (§6.2a).
        f = tmp_path / "fake.avi"   # .avi maps to video/x-msvideo via mimetypes
        f.write_bytes(b"not-actually-an-avi-no-RIFF-signature-here" * 8)
        _, rec = _scan_one(f, no_magic=True)
        trig = (rec.signal_provenance or {}).get("mime_type", {}).get("trigger")
        assert trig == "extension_fallback", f"precondition: extension-fallback MIME (got {trig})"
        assert _flagged(rec), "an extension-fallback MIME must NOT recognize (content rests on content)"


class TestTextUnchangedFromV121:
    @pytest.mark.requires_libmagic   # typing UNLISTED-extension prose as text/* needs libmagic; on
    # the no-libmagic path the pure-Python sniff matches only BINARY signatures, so signatureless
    # text with an unlisted extension falls to octet-stream and stays flagged (the documented §6.2a
    # gap, unchanged by v1.22). The binary cases above need no marker — zip has a PK sniff signature.
    def test_recognized_text_still_recognized(self, tmp_path):
        f = tmp_path / f"notes{UNLISTED}"
        f.write_text("This is ordinary readable English prose, recognized as text.\n" * 5)
        _, rec = _scan_one(f)
        assert rec.mime_type.startswith("text/")
        assert not _flagged(rec), "recognized text stays recognized (v1.21 behavior preserved)"


class TestDeterminism:
    def test_workers_byte_identical(self, tmp_path):
        (tmp_path / f"a{UNLISTED}").write_bytes(_zip_bytes())
        (tmp_path / f"b{UNLISTED}").write_bytes(b"\x00\xff" * 100)
        (tmp_path / f"c.txt").write_text("hello\n")
        a = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=1)).scan()
        b = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert a.manifest_checksum == b.manifest_checksum
