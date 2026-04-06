"""Edge-case tests — empty files, no extension, binary-in-text, broken symlinks, hidden files, etc."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scanner.scanner import (
    Scanner,
    ScannerConfig,
    FileRecord,
    FrontmatterRecord,
    StructuralRecord,
    manifest_to_json,
)


# ---------------------------------------------------------------------------
# Empty / zero-byte files
# ---------------------------------------------------------------------------

class TestEmptyFiles:
    def test_zero_byte_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        scanner = Scanner(source_dir=tmp_path)
        manifest = scanner.scan()
        assert len(manifest.files) == 1
        rec = manifest.files[0]
        assert rec.size_bytes == 0
        assert rec.checksum_sha256  # still has a hash (SHA-256 of empty = e3b0c...)
        assert rec.is_binary is False  # empty sample -> looks_like_text returns True

    def test_zero_byte_binary_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.png"
        f.write_bytes(b"")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.size_bytes == 0
        assert rec.extension == ".png"


# ---------------------------------------------------------------------------
# Files with no extension
# ---------------------------------------------------------------------------

class TestNoExtension:
    def test_extensionless_file(self, tmp_path: Path) -> None:
        f = tmp_path / "Makefile"
        f.write_text("all:\n\techo hello")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.extension == ""
        assert rec.filename == "Makefile"

    def test_dotfile(self, tmp_path: Path) -> None:
        f = tmp_path / ".gitignore"
        f.write_text("*.pyc\n__pycache__/")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.filename == ".gitignore"


# ---------------------------------------------------------------------------
# Binary content in text-like extensions
# ---------------------------------------------------------------------------

class TestBinaryInTextExtension:
    def test_txt_with_nul_bytes(self, tmp_path: Path) -> None:
        f = tmp_path / "sneaky.txt"
        f.write_bytes(b"Hello\x00World\x00binary")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.is_binary is True
        assert rec.encoding is None
        assert rec.content_preview is None

    def test_md_with_binary_content(self, tmp_path: Path) -> None:
        f = tmp_path / "fake.md"
        f.write_bytes(bytes(range(256)) * 10)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.is_binary is True


# ---------------------------------------------------------------------------
# Hidden file filtering
# ---------------------------------------------------------------------------

class TestHiddenFileFiltering:
    def test_exclude_hidden_false_includes_dotfiles(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden").write_text("secret")
        (tmp_path / "visible.txt").write_text("public")
        config = ScannerConfig()
        config.exclude_hidden = False
        scanner = Scanner(source_dir=tmp_path, config=config)
        names = [f.filename for f in scanner.scan().files]
        assert ".hidden" in names
        assert "visible.txt" in names

    def test_exclude_hidden_true_skips_dotfiles(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden").write_text("secret")
        (tmp_path / "visible.txt").write_text("public")
        config = ScannerConfig()
        config.exclude_hidden = True
        scanner = Scanner(source_dir=tmp_path, config=config)
        names = [f.filename for f in scanner.scan().files]
        assert ".hidden" not in names
        assert "visible.txt" in names

    def test_exclude_hidden_true_skips_dotdirs(self, tmp_path: Path) -> None:
        dotdir = tmp_path / ".git"
        dotdir.mkdir()
        (dotdir / "config").write_text("stuff")
        (tmp_path / "readme.md").write_text("# Hi")
        config = ScannerConfig()
        config.exclude_hidden = True
        scanner = Scanner(source_dir=tmp_path, config=config)
        names = [f.filename for f in scanner.scan().files]
        assert "config" not in names
        assert "readme.md" in names


# ---------------------------------------------------------------------------
# Broken symlinks / permission denied (universal tier protection)
# ---------------------------------------------------------------------------

class TestUniversalTierProtection:
    @pytest.mark.skipif(os.name == "nt", reason="symlinks unreliable on Windows")
    def test_broken_symlink_skipped(self, tmp_path: Path) -> None:
        """Broken symlinks are not yielded by is_file(), so scan should not crash."""
        target = tmp_path / "nonexistent"
        link = tmp_path / "broken_link"
        link.symlink_to(target)
        (tmp_path / "real.txt").write_text("ok")
        scanner = Scanner(source_dir=tmp_path)
        manifest = scanner.scan()
        names = [f.filename for f in manifest.files]
        assert "real.txt" in names
        assert "broken_link" not in names  # is_file() returns False for broken symlinks


# ---------------------------------------------------------------------------
# Sidecar detection
# ---------------------------------------------------------------------------

class TestSidecarEdgeCases:
    def test_sidecar_json_suffix(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("# Report")
        (tmp_path / "report.md.json").write_text("{}")
        scanner = Scanner(source_dir=tmp_path)
        rec = [r for r in scanner.scan().files if r.filename == "report.md"][0]
        assert rec.sidecar_exists is True

    def test_sidecar_stem_json(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b")
        (tmp_path / "data.json").write_text("{}")
        scanner = Scanner(source_dir=tmp_path)
        rec = [r for r in scanner.scan().files if r.filename == "data.csv"][0]
        assert rec.sidecar_exists is True

    def test_no_sidecar(self, tmp_path: Path) -> None:
        f = tmp_path / "alone.txt"
        f.write_text("lonely")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.sidecar_exists is False


# ---------------------------------------------------------------------------
# Large preview truncation
# ---------------------------------------------------------------------------

class TestPreviewBounds:
    def test_preview_capped_at_config(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("x" * 5000)
        config = ScannerConfig()
        config.preview_max_chars = 100
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert len(rec.content_preview) == 100

    def test_default_preview_cap_1000(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("y" * 5000)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert len(rec.content_preview) == 1000


# ---------------------------------------------------------------------------
# Specialist tier
# ---------------------------------------------------------------------------

class TestSpecialistTier:
    def test_specialist_disabled_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text("{invalid json!!")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "json_parse_failed" not in codes

    def test_specialist_enabled_catches_json_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text("{invalid json!!")
        config = ScannerConfig()
        config.enable_specialists = True
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "json_parse_failed" in codes

    def test_specialist_valid_json_no_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        config = ScannerConfig()
        config.enable_specialists = True
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "json_parse_failed" not in codes


# ---------------------------------------------------------------------------
# Directory depth and stage_folder
# ---------------------------------------------------------------------------

class TestPathDerived:
    def test_root_level_file(self, tmp_path: Path) -> None:
        f = tmp_path / "root.txt"
        f.write_text("at root")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.directory_depth == 0
        assert rec.stage_folder == ""

    def test_nested_file(self, tmp_path: Path) -> None:
        sub = tmp_path / "stage1" / "sub"
        sub.mkdir(parents=True)
        f = sub / "deep.txt"
        f.write_text("nested")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.directory_depth == 2
        assert rec.stage_folder == "stage1"

    def test_one_level_deep(self, tmp_path: Path) -> None:
        sub = tmp_path / "inbox"
        sub.mkdir()
        f = sub / "file.md"
        f.write_text("# Hi")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.directory_depth == 1
        assert rec.stage_folder == "inbox"


# ---------------------------------------------------------------------------
# Encoding edge cases
# ---------------------------------------------------------------------------

class TestEncodingEdgeCases:
    def test_utf8_file(self, tmp_path: Path) -> None:
        f = tmp_path / "utf8.txt"
        f.write_text("Hello café", encoding="utf-8")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.encoding is not None
        assert "café" in rec.content_preview

    def test_latin1_file(self, tmp_path: Path) -> None:
        f = tmp_path / "latin.txt"
        f.write_bytes("Stra\xdfe".encode("latin-1"))
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.encoding is not None

    def test_binary_encoding_null(self, tmp_path: Path) -> None:
        f = tmp_path / "bin.dat"
        f.write_bytes(b"\x00\x01\x02\x03" * 100)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.encoding is None


# ---------------------------------------------------------------------------
# Error model
# ---------------------------------------------------------------------------

class TestErrorModel:
    def test_errors_always_list(self, tmp_path: Path) -> None:
        f = tmp_path / "ok.txt"
        f.write_text("fine")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert isinstance(rec.errors, list)

    def test_unsupported_extension_error(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.bmp"
        f.write_bytes(b"BM" + b"\x00" * 100)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" in codes

    def test_supported_extension_no_unsupported_error(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("# Hello")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes


# ---------------------------------------------------------------------------
# Full scan of an empty directory
# ---------------------------------------------------------------------------

class TestEmptyDirectory:
    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        scanner = Scanner(source_dir=tmp_path)
        manifest = scanner.scan()
        assert manifest.files == []
        assert manifest.generated_at
        assert manifest.source_dir
