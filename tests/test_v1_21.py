"""v1.21.0 — content-aware recognition (RFC §6 = Option B).

`unsupported_extension` no longer fires when a file's CONTENT is text (`text/*` or a known
structured-text application type) — even if its extension isn't in SUPPORTED_EXTENSIONS.
The diagnostic now means "couldn't identify it", not "extension not in our list". From the
candidate scan (~9k corpus files were recognized text being mislabeled). Recognition only —
no new extraction; the text baseline output is unchanged.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import file_observer.scanner as fo
from file_observer.scanner import (
    Scanner, ScannerConfig, _is_recognized_text, ERR_UNSUPPORTED_EXTENSION,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)


def test_release_version_surfaces():
    # v1.21 floor — the exact current-version pin now lives in the newest release test (test_v1_22).
    def _v(s): return tuple(int(p) for p in s.split("."))
    assert _v(SCANNER_VERSION) >= (1, 21, 0), f"SCANNER regressed below v1.21: {SCANNER_VERSION!r}"
    assert _v(LOGIC_VERSION) >= (1, 11, 0), f"LOGIC regressed below 1.11.0: {LOGIC_VERSION!r}"
    assert _v(SCHEMA_VERSION) >= (1, 13), f"SCHEMA regressed below 1.13: {SCHEMA_VERSION!r}"


class TestPredicate:
    @pytest.mark.parametrize("mt", [
        "text/plain", "text/x-script.python", "text/x-java", "text/x-c",
        "application/json", "application/javascript", "application/xml",
        "application/yaml", "image/svg+xml", "inode/x-empty",
    ])
    def test_recognized_text(self, mt):
        assert _is_recognized_text(mt) is True

    @pytest.mark.parametrize("mt", [
        None, "", "application/octet-stream", "image/png", "video/mp4",
        "application/pdf", "image/x-tga",
    ])
    def test_not_text(self, mt):
        assert _is_recognized_text(mt) is False


def _scan(tmp_path, files):
    for name, data in files.items():
        p = tmp_path / name
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return Scanner(source_dir=tmp_path, config=ScannerConfig()).scan()


class TestRecognition:
    def _unsup(self, rec):
        return any(e.code == ERR_UNSUPPORTED_EXTENSION for e in rec.errors)

    @pytest.mark.requires_libmagic   # leans on libmagic typing .py/.ini/.svg as text/*
    def test_source_config_svg_recognized(self, tmp_path):
        m = _scan(tmp_path, {
            "app.py": "import os\ndef f():\n    return 1\n",
            "conf.ini": "[s]\nk=v\n",
            "vec.svg": '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>\n',
        })
        for f in m.files:
            assert not self._unsup(f), f"{f.filename} wrongly flagged unsupported"
        assert m.stats.supported_files == 3
        assert m.stats.unsupported_files == 0

    def test_genuine_binary_still_unsupported(self, tmp_path):
        # NUL-heavy bytes with an unknown extension → octet-stream, not text → still flagged
        m = _scan(tmp_path, {"blob.xyz": b"\x00\x01\x02\x03" * 64})
        rec = next(f for f in m.files if f.filename == "blob.xyz")
        assert self._unsup(rec)            # genuinely unidentified → diagnostic stays
        assert m.stats.unsupported_files == 1

    def test_text_baseline_unchanged(self, tmp_path):
        # recognition is the ONLY change — the text file still gets its baseline observations
        m = _scan(tmp_path, {"app.py": "import os\nx = 1\n"})
        rec = m.files[0]
        assert rec.is_binary is False
        assert rec.content_preview is not None      # baseline still ran
        assert "import os" in rec.content_preview   # actual content observed, unchanged

    @pytest.mark.requires_libmagic   # `inode/x-empty` is a libmagic-specific type
    def test_empty_file_recognized(self, tmp_path):
        # an empty file is positively identified (inode/x-empty), not "unidentifiable"
        m = _scan(tmp_path, {"__init__.py": b"", "py.typed": b""})
        for f in m.files:
            assert f.mime_type == "inode/x-empty"
            assert not self._unsup(f), f"{f.filename} (empty) wrongly flagged unsupported"
        assert m.stats.unsupported_files == 0

    @pytest.mark.requires_libmagic   # UTF-16 → text/plain is a libmagic identification
    def test_utf16_text_recognized_via_bom(self, tmp_path):
        # UTF-16 text interleaves NULs → fails the printable ratio, but the BOM arm rescues it
        # (mirrors detect_binary's BOM short-circuit) so a UTF-16 .foo is recognized like UTF-8.
        (tmp_path / "notes.foo").write_bytes("hello unicode world\n".encode("utf-16"))
        rec = Scanner(source_dir=tmp_path, config=ScannerConfig()).scan().files[0]
        assert rec.mime_type.startswith("text/")
        assert not self._unsup(rec)

    def test_extension_fallback_mime_not_recognized(self, tmp_path):
        # recognition must rest on OBSERVED CONTENT: a MIME that came from the extension
        # fallback (mimetypes; no libmagic + no content signature) does NOT recognize — else
        # the flag depends on the platform mimetypes DB and contradicts RFC §6.2a. [leg-4 Codex]
        (tmp_path / "app.py").write_text("import os\nx = 1\n")
        sc = Scanner(source_dir=tmp_path, config=ScannerConfig())
        sc._magic = None                      # force the no-libmagic path
        rec = sc.scan().files[0]
        assert rec.mime_type.startswith("text/")                       # mimetypes says text...
        assert rec.signal_provenance["mime_type"]["trigger"] == "extension_fallback"  # ...by ext
        assert self._unsup(rec)               # so NOT content-recognized on the fallback

    def test_read_failure_not_recognized(self, tmp_path, monkeypatch):
        # a read-failed file has NO observed content — an extension/empty-sample text MIME must
        # not flip it to "recognized"; it's degraded, flagged, and not counted supported. [leg-2]
        (tmp_path / "code.c").write_text("int main(){ return 0; }\n")   # .c unlisted, text OS-MIME
        real = fo.Scanner.read_sample
        def boom(self, path):
            if path.name == "code.c":
                raise OSError("simulated read failure")
            return real(self, path)
        monkeypatch.setattr(fo.Scanner, "read_sample", boom)
        m = Scanner(source_dir=tmp_path, config=ScannerConfig()).scan()
        rec = next(f for f in m.files if f.filename == "code.c")
        assert any(e.code == "universal_read_failed" for e in rec.errors)
        assert self._unsup(rec)                # read-failure + unlisted ext → still flagged
        assert m.stats.supported_files == 0    # and not counted supported

    @pytest.mark.requires_libmagic   # the "lie" (text/plain on NUL bytes) is libmagic's
    def test_binary_veto_on_lying_mime(self, tmp_path):
        # libmagic can call NUL-bearing bytes `text/plain`; is_binary must veto recognition
        m = _scan(tmp_path, {"photo.bmp": b"BM" + b"\x00" * 100})
        rec = m.files[0]
        assert rec.mime_type == "text/plain"   # the lie
        assert rec.is_binary is True           # but the bytes are binary
        assert self._unsup(rec)                # → still flagged, not falsely recognized

    def test_listed_extension_still_supported(self, tmp_path):
        # a SUPPORTED_EXTENSIONS file (e.g. .md) is recognized as before (by extension)
        m = _scan(tmp_path, {"r.md": "# Title\n\ntext\n"})
        assert not self._unsup(m.files[0])


class TestDeterminism:
    def test_workers_byte_identical(self, tmp_path):
        files = {f"f{i}.py": f"x = {i}\n" for i in range(6)}
        files["b.bin"] = b"\x00" * 200
        for n, d in files.items():
            (tmp_path / n).write_bytes(d if isinstance(d, bytes) else d.encode())
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig()).scan()
        m4 = Scanner(source_dir=tmp_path, config=ScannerConfig(workers=4)).scan()
        assert m1.manifest_checksum == m4.manifest_checksum
