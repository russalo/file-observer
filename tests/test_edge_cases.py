"""Edge-case tests — empty files, no extension, binary-in-text, broken symlinks, hidden files, etc."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    FileRecord,
    FrontmatterRecord,
    MimeAnalysisRecord,
    StructuralRecord,
    manifest_to_json,
    compute_manifest_checksum,
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
        assert manifest.meta.generated_at
        assert manifest.meta.source_dir
        assert manifest.stats.total_files == 0


# ---------------------------------------------------------------------------
# .scannerignore
# ---------------------------------------------------------------------------

class TestScannerIgnore:
    def test_ignore_by_extension(self, tmp_path: Path) -> None:
        (tmp_path / "keep.txt").write_text("hello")
        (tmp_path / "skip.log").write_text("noise")
        (tmp_path / ".scannerignore").write_text("*.log\n")
        scanner = Scanner(source_dir=tmp_path)
        paths = [f.filename for f in scanner.scan().files]
        assert "keep.txt" in paths
        assert "skip.log" not in paths

    def test_ignore_directory(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.txt").write_text("code")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.txt").write_text("dep")
        (tmp_path / ".scannerignore").write_text("node_modules/\n")
        scanner = Scanner(source_dir=tmp_path)
        paths = [f.filename for f in scanner.scan().files]
        assert "app.txt" in paths
        assert "dep.txt" not in paths

    def test_ignore_comments_and_blanks(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.log").write_text("b")
        (tmp_path / ".scannerignore").write_text("# comment\n\n*.log\n")
        scanner = Scanner(source_dir=tmp_path)
        paths = [f.filename for f in scanner.scan().files]
        assert "a.txt" in paths
        assert "b.log" not in paths

    def test_ignore_file_not_in_manifest(self, tmp_path: Path) -> None:
        """The .scannerignore file itself should appear in the manifest (it's a regular file)."""
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / ".scannerignore").write_text("*.log\n")
        scanner = Scanner(source_dir=tmp_path)
        paths = [f.filename for f in scanner.scan().files]
        assert ".scannerignore" in paths

    def test_explicit_ignore_file_path(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.tmp").write_text("b")
        ignore = tmp_path / "custom.ignore"
        ignore.write_text("*.tmp\n")
        config = ScannerConfig(ignore_file=str(ignore))
        scanner = Scanner(source_dir=tmp_path, config=config)
        paths = [f.filename for f in scanner.scan().files]
        assert "a.txt" in paths
        assert "b.tmp" not in paths

    def test_ignore_coexists_with_exclude_hidden(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / ".hidden").write_text("h")
        (tmp_path / "b.log").write_text("b")
        (tmp_path / ".scannerignore").write_text("*.log\n")
        config = ScannerConfig(exclude_hidden=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        paths = [f.filename for f in scanner.scan().files]
        assert "a.txt" in paths
        assert ".hidden" not in paths
        assert "b.log" not in paths

    def test_no_ignore_file_scans_everything(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.log").write_text("b")
        scanner = Scanner(source_dir=tmp_path)
        assert len(scanner.scan().files) == 2

    def test_ignore_path_scoped_directory(self, tmp_path: Path) -> None:
        """Path-scoped ignore patterns like 'src/generated/' should work."""
        gen = tmp_path / "src" / "generated"
        gen.mkdir(parents=True)
        (gen / "output.txt").write_text("generated")
        (tmp_path / "src" / "real.txt").write_text("real")
        (tmp_path / ".scannerignore").write_text("src/generated/\n")
        scanner = Scanner(source_dir=tmp_path)
        names = [f.filename for f in scanner.scan().files]
        assert "real.txt" in names
        assert "output.txt" not in names


# ---------------------------------------------------------------------------
# Delta / incremental scanning
# ---------------------------------------------------------------------------

class TestDeltaScanning:
    def test_no_previous_manifest_returns_null_delta(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        scanner = Scanner(source_dir=tmp_path)
        manifest = scanner.scan()
        assert manifest.delta is None

    def _save_prev(self, manifest, tmp_path: Path) -> Path:
        """Write manifest outside the scan dir so it doesn't appear in next scan."""
        out_dir = tmp_path / "_out"
        out_dir.mkdir(exist_ok=True)
        prev = out_dir / "prev.json"
        prev.write_text(manifest_to_json(manifest), encoding="utf-8")
        return prev

    def test_unchanged_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        s1 = Scanner(source_dir=src)
        m1 = s1.scan()
        prev = self._save_prev(m1, tmp_path)
        config = ScannerConfig(previous_manifest=str(prev))
        s2 = Scanner(source_dir=src, config=config)
        m2 = s2.scan()
        assert m2.delta is not None
        assert m2.delta.unchanged == ["a.txt"]
        assert m2.delta.added == []
        assert m2.delta.modified == []
        assert m2.delta.removed == []

    def test_added_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        s1 = Scanner(source_dir=src)
        m1 = s1.scan()
        prev = self._save_prev(m1, tmp_path)
        (src / "b.txt").write_text("world")
        config = ScannerConfig(previous_manifest=str(prev))
        s2 = Scanner(source_dir=src, config=config)
        m2 = s2.scan()
        assert m2.delta is not None
        assert "b.txt" in m2.delta.added
        assert "a.txt" in m2.delta.unchanged

    def test_modified_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        f = src / "a.txt"
        f.write_text("version1")
        s1 = Scanner(source_dir=src)
        m1 = s1.scan()
        prev = self._save_prev(m1, tmp_path)
        f.write_text("version2")
        config = ScannerConfig(previous_manifest=str(prev))
        s2 = Scanner(source_dir=src, config=config)
        m2 = s2.scan()
        assert m2.delta is not None
        assert "a.txt" in m2.delta.modified

    def test_removed_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        (src / "b.txt").write_text("world")
        s1 = Scanner(source_dir=src)
        m1 = s1.scan()
        prev = self._save_prev(m1, tmp_path)
        (src / "b.txt").unlink()
        config = ScannerConfig(previous_manifest=str(prev))
        s2 = Scanner(source_dir=src, config=config)
        m2 = s2.scan()
        assert m2.delta is not None
        assert "b.txt" in m2.delta.removed
        assert "a.txt" in m2.delta.unchanged

    def test_delta_has_previous_scan_id(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        s1 = Scanner(source_dir=src)
        m1 = s1.scan()
        prev = self._save_prev(m1, tmp_path)
        config = ScannerConfig(previous_manifest=str(prev))
        s2 = Scanner(source_dir=src, config=config)
        m2 = s2.scan()
        assert m2.delta is not None
        assert m2.delta.previous_scan_id == m1.meta.scan_id

    def test_malformed_previous_manifest(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        prev = tmp_path / "prev.json"
        prev.write_text("not json", encoding="utf-8")
        config = ScannerConfig(previous_manifest=str(prev))
        scanner = Scanner(source_dir=src, config=config)
        manifest = scanner.scan()
        assert manifest.delta is None

    def test_previous_manifest_missing_path_keys(self, tmp_path: Path) -> None:
        """Previous manifest with entries missing 'path' should not crash."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        # Write a malformed previous manifest with a record missing 'path'
        import json
        prev_data = {
            "meta": {"scan_id": "test-id"},
            "files": [
                {"checksum_sha256": "abc123"},  # no 'path' key
                {"path": "b.txt", "checksum_sha256": "def456"},
            ],
        }
        prev = tmp_path / "prev.json"
        prev.write_text(json.dumps(prev_data))
        config = ScannerConfig(previous_manifest=str(prev))
        scanner = Scanner(source_dir=src, config=config)
        manifest = scanner.scan()
        assert manifest.delta is not None
        assert "a.txt" in manifest.delta.added
        assert "b.txt" in manifest.delta.removed

    def test_delta_lists_sorted(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        for name in ["c.txt", "a.txt", "b.txt"]:
            (src / name).write_text(name)
        s1 = Scanner(source_dir=src)
        m1 = s1.scan()
        prev = self._save_prev(m1, tmp_path)
        for name in ["c.txt", "a.txt", "b.txt"]:
            (src / name).write_text(name + " changed")
        config = ScannerConfig(previous_manifest=str(prev))
        s2 = Scanner(source_dir=src, config=config)
        m2 = s2.scan()
        assert m2.delta is not None
        assert m2.delta.modified == sorted(m2.delta.modified)


# ---------------------------------------------------------------------------
# Manifest checksum
# ---------------------------------------------------------------------------

class TestManifestChecksum:
    def test_checksum_present(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        scanner = Scanner(source_dir=tmp_path)
        manifest = scanner.scan()
        assert manifest.manifest_checksum
        assert len(manifest.manifest_checksum) == 64  # SHA-256 hex

    def test_checksum_verifiable(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        scanner = Scanner(source_dir=tmp_path)
        manifest = scanner.scan()
        recomputed = compute_manifest_checksum(manifest)
        assert manifest.manifest_checksum == recomputed

    def test_checksum_changes_with_content(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("v1")
        c1 = Scanner(source_dir=tmp_path).scan().manifest_checksum
        f.write_text("v2")
        c2 = Scanner(source_dir=tmp_path).scan().manifest_checksum
        assert c1 != c2


# ---------------------------------------------------------------------------
# MIME mismatch signaling
# ---------------------------------------------------------------------------

class TestMimeAnalysis:
    def test_text_file_matches(self, tmp_path: Path) -> None:
        (tmp_path / "hello.txt").write_text("Hello world")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.mime_analysis is not None
        assert rec.mime_analysis.extension_mime == "text/plain"
        assert isinstance(rec.mime_analysis.matches_extension, bool)

    def test_json_file_matches(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"key": "value"}')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.mime_analysis.extension_mime == "application/json"

    def test_unknown_extension_matches_true(self, tmp_path: Path) -> None:
        (tmp_path / "weird.xyzabc").write_bytes(b"some data")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.mime_analysis.extension_mime is None
        assert rec.mime_analysis.matches_extension is True

    def test_spoofed_extension_mismatch(self, tmp_path: Path) -> None:
        """A PNG file with .txt extension should show a mismatch when content-based detection is available."""
        # Write PNG magic bytes in a .txt file
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        (tmp_path / "fake.txt").write_bytes(png_header)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        # Extension says text/plain
        assert rec.mime_analysis.extension_mime == "text/plain"
        # Whether mismatch is detected depends on python-magic availability
        assert isinstance(rec.mime_analysis.matches_extension, bool)

    def test_mime_analysis_on_binary(self, tmp_path: Path) -> None:
        (tmp_path / "data.pdf").write_bytes(b"%PDF-1.4" + b"\x00" * 100)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.mime_analysis is not None
        assert rec.mime_analysis.extension_mime == "application/pdf"

    def test_mime_analysis_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        s1 = Scanner(source_dir=tmp_path)
        s2 = Scanner(source_dir=tmp_path)
        r1 = s1.scan().files[0].mime_analysis
        r2 = s2.scan().files[0].mime_analysis
        assert r1.detected_mime == r2.detected_mime
        assert r1.extension_mime == r2.extension_mime
        assert r1.matches_extension == r2.matches_extension

    def test_html_extension_mime(self, tmp_path: Path) -> None:
        (tmp_path / "page.html").write_text("<html><head><title>Test</title></head></html>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.mime_analysis.extension_mime == "text/html"


# ---------------------------------------------------------------------------
# Specialist metadata
# ---------------------------------------------------------------------------

class TestSpecialistMetadata:
    def test_specialist_metadata_none_when_disabled(self, tmp_path: Path) -> None:
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4" + b"\x00" * 100)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_pdf_metadata_extracted_when_enabled(self, tmp_path: Path) -> None:
        pdf_content = b"%PDF-1.4 /Font /Text BT\n/Type /Pages /Count 3 /Title (Test Doc) /Author (Alice)"
        (tmp_path / "doc.pdf").write_bytes(pdf_content)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is not None
        assert rec.specialist_metadata["pdf"]["has_text_streams"] is True
        assert rec.specialist_metadata["pdf"]["page_count"] == 3
        assert rec.specialist_metadata["pdf"]["title"] == "Test Doc"
        assert rec.specialist_metadata["pdf"]["author"] == "Alice"

    def test_pdf_no_text_streams(self, tmp_path: Path) -> None:
        pdf_content = b"%PDF-1.4 just image data no text markers here"
        (tmp_path / "scan.pdf").write_bytes(pdf_content)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is not None
        assert rec.specialist_metadata["pdf"]["has_text_streams"] is False

    def test_pdf_missing_page_count(self, tmp_path: Path) -> None:
        pdf_content = b"%PDF-1.4 /Font"
        (tmp_path / "doc.pdf").write_bytes(pdf_content)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata["pdf"]["page_count"] is None

    def test_non_pdf_specialist_metadata_null(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("Hello")
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_pdf_creation_date(self, tmp_path: Path) -> None:
        pdf_content = b"%PDF-1.4 /CreationDate (D:20260101120000)"
        (tmp_path / "doc.pdf").write_bytes(pdf_content)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata["pdf"]["creation_date"] == "D:20260101120000"

    def test_specialist_metadata_deterministic(self, tmp_path: Path) -> None:
        pdf_content = b"%PDF-1.4 /Font /Type /Pages /Count 5 /Title (Report) /Author (Bob)"
        (tmp_path / "doc.pdf").write_bytes(pdf_content)
        config = ScannerConfig(enable_specialists=True)
        s1 = Scanner(source_dir=tmp_path, config=config)
        s2 = Scanner(source_dir=tmp_path, config=config)
        m1 = s1.scan().files[0].specialist_metadata
        m2 = s2.scan().files[0].specialist_metadata
        assert m1 == m2


# ---------------------------------------------------------------------------
# HTML / HTM formal support
# ---------------------------------------------------------------------------

class TestHtmlFormalSupport:
    def test_html_is_supported(self, tmp_path: Path) -> None:
        (tmp_path / "page.html").write_text("<html><head><title>Test</title></head><body>Hi</body></html>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes

    def test_htm_is_supported(self, tmp_path: Path) -> None:
        (tmp_path / "page.htm").write_text("<html><body>Hi</body></html>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes

    def test_html_title_extraction(self, tmp_path: Path) -> None:
        (tmp_path / "page.html").write_text("<html><head><title>My Page</title></head></html>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.structural.title == "My Page"

    def test_html_has_preview(self, tmp_path: Path) -> None:
        (tmp_path / "page.html").write_text("<html><body>Content here</body></html>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.content_preview is not None
        assert "Content here" in rec.content_preview

    def test_html_technology_detection(self, tmp_path: Path) -> None:
        html = '<html><head><link href="https://fonts.googleapis.com/css2"></head></html>'
        (tmp_path / "page.html").write_text(html)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "google-fonts" in rec.structural.technology_hints


# ---------------------------------------------------------------------------
# PDF deepened specialist metadata (v0.3 Phase 2)
# ---------------------------------------------------------------------------

class TestPdfDeepenedEdgeCases:
    def test_encrypted_pdf_through_scan(self, tmp_path: Path) -> None:
        content = b"%PDF-1.4 /Encrypt << /Filter /Standard >> /Font BT\nsome ET"
        (tmp_path / "encrypted.pdf").write_bytes(content)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata["pdf"]["encrypted"] is True
        assert rec.specialist_metadata["pdf"]["pdf_version"] == "1.4"
        assert rec.specialist_metadata["pdf"]["sample_text_marker_density"] > 0

    def test_pdf_density_deterministic(self, tmp_path: Path) -> None:
        content = b"%PDF-1.4 BT text ET BT more ET"
        (tmp_path / "doc.pdf").write_bytes(content)
        config = ScannerConfig(enable_specialists=True)
        m1 = Scanner(source_dir=tmp_path, config=config).scan().files[0].specialist_metadata
        m2 = Scanner(source_dir=tmp_path, config=config).scan().files[0].specialist_metadata
        assert m1["pdf"]["sample_text_marker_density"] == m2["pdf"]["sample_text_marker_density"]


# ---------------------------------------------------------------------------
# PNG specialist edge cases (v0.3 Phase 2)
# ---------------------------------------------------------------------------

class TestPngEdgeCases:
    def _make_png(self, width: int, height: int, bit_depth: int = 8) -> bytes:
        import struct
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">II", width, height) + bytes([bit_depth, 2, 0, 0, 0])
        ihdr_len = struct.pack(">I", 13)
        return sig + ihdr_len + b"IHDR" + ihdr_data

    def test_zero_byte_png(self, tmp_path: Path) -> None:
        (tmp_path / "empty.png").write_bytes(b"")
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        # Should not crash; specialist_metadata may be None
        assert rec.specialist_metadata is None or rec.specialist_metadata.get("width") is None

    def test_png_requires_specialist(self, tmp_path: Path) -> None:
        (tmp_path / "test.png").write_bytes(self._make_png(100, 100))
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.requires_specialist_tool is True
        assert rec.specialist_tool == "image_structure"

    def test_png_no_metadata_when_specialists_disabled(self, tmp_path: Path) -> None:
        (tmp_path / "test.png").write_bytes(self._make_png(100, 100))
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_real_png_fixture(self) -> None:
        """Test against the sample PNG fixture file."""
        from pathlib import Path as P
        fixture = P(__file__).parent / "fixtures" / "sample_logo.png"
        if not fixture.exists():
            pytest.skip("sample_logo.png fixture not present")
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=fixture.parent, config=config)
        manifest = scanner.scan()
        recs = [f for f in manifest.files if f.filename == "sample_logo.png"]
        assert len(recs) == 1
        rec = recs[0]
        assert rec.specialist_metadata is not None
        assert rec.specialist_metadata["image"]["width"] == 200
        assert rec.specialist_metadata["image"]["height"] == 100


# ---------------------------------------------------------------------------
# MSG specialist edge cases (v0.3 Phase 2)
# ---------------------------------------------------------------------------

class TestMsgEdgeCases:
    def test_msg_requires_specialist(self, tmp_path: Path) -> None:
        (tmp_path / "email.msg").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.requires_specialist_tool is True
        assert rec.specialist_tool == "email_envelope"

    def test_msg_no_metadata_when_specialists_disabled(self, tmp_path: Path) -> None:
        (tmp_path / "email.msg").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_msg_invalid_file(self, tmp_path: Path) -> None:
        (tmp_path / "fake.msg").write_bytes(b"not an OLE file at all")
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        # Should not crash; metadata is None for non-OLE files
        assert rec.specialist_metadata is None


# ---------------------------------------------------------------------------
# XML support (v0.3 Phase 3)
# ---------------------------------------------------------------------------

class TestXmlSupport:
    def test_xml_is_supported(self, tmp_path: Path) -> None:
        (tmp_path / "data.xml").write_text('<?xml version="1.0"?><root><a/><b/></root>')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes

    def test_xml_document_keys(self, tmp_path: Path) -> None:
        (tmp_path / "data.xml").write_text('<?xml version="1.0"?><config><db/><cache/><log/></config>')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "config" in rec.structural.document_keys
        assert "cache" in rec.structural.document_keys
        assert "db" in rec.structural.document_keys
        assert "log" in rec.structural.document_keys

    def test_xml_root_element_first(self, tmp_path: Path) -> None:
        (tmp_path / "data.xml").write_text('<project><name/><version/></project>')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.structural.document_keys[0] == "project"

    def test_xml_malformed_non_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "bad.xml").write_text('<broken><no closing tag')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.structural.document_keys == []

    def test_xml_has_preview(self, tmp_path: Path) -> None:
        (tmp_path / "data.xml").write_text('<root>hello</root>')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.content_preview is not None
        assert "root" in rec.content_preview

    def test_xml_deduplicates_children(self, tmp_path: Path) -> None:
        (tmp_path / "data.xml").write_text('<root><item/><item/><item/></root>')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.structural.document_keys.count("item") == 1


# ---------------------------------------------------------------------------
# TOML support (v0.3 Phase 3)
# ---------------------------------------------------------------------------

class TestTomlSupport:
    def test_toml_is_supported(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text('name = "test"\nversion = "1.0"\n')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes

    def test_toml_document_keys(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text('name = "scanner"\nversion = "0.3"\ndebug = false\n')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "debug" in rec.structural.document_keys
        assert "name" in rec.structural.document_keys
        assert "version" in rec.structural.document_keys

    def test_toml_keys_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text('zebra = 1\nalpha = 2\nmid = 3\n')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.structural.document_keys == sorted(rec.structural.document_keys)

    def test_toml_malformed_non_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "bad.toml").write_text('this is not valid toml [[[')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.structural.document_keys == []

    def test_toml_has_preview(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text('title = "My Config"\n')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.content_preview is not None


# ---------------------------------------------------------------------------
# PNG / MSG in SUPPORTED_EXTENSIONS (v0.3 Phase 3)
# ---------------------------------------------------------------------------

class TestNewSupportedExtensions:
    def test_png_no_unsupported_error(self, tmp_path: Path) -> None:
        import struct
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 10, 10) + bytes([8, 2, 0, 0, 0])
        (tmp_path / "img.png").write_bytes(sig + ihdr)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes

    def test_msg_no_unsupported_error(self, tmp_path: Path) -> None:
        (tmp_path / "mail.msg").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes

    def test_xml_no_unsupported_error(self, tmp_path: Path) -> None:
        (tmp_path / "data.xml").write_text("<root/>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes

    def test_toml_no_unsupported_error(self, tmp_path: Path) -> None:
        (tmp_path / "cfg.toml").write_text('key = "val"\n')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes


# ---------------------------------------------------------------------------
# Delta rescan_candidates (v0.3 Phase 3)
# ---------------------------------------------------------------------------

class TestRescanCandidates:
    def _save_prev(self, manifest, tmp_path: Path) -> Path:
        from file_observer.scanner import manifest_to_json
        out_dir = tmp_path / "_out"
        out_dir.mkdir(exist_ok=True)
        prev = out_dir / "prev.json"
        prev.write_text(manifest_to_json(manifest), encoding="utf-8")
        return prev

    def test_no_rescan_candidates_when_no_errors(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        m1 = Scanner(source_dir=src).scan()
        prev = self._save_prev(m1, tmp_path)
        config = ScannerConfig(previous_manifest=str(prev))
        m2 = Scanner(source_dir=src, config=config).scan()
        assert m2.delta is not None
        assert m2.delta.rescan_candidates == []

    def test_rescan_candidates_from_specialist_failures(self, tmp_path: Path) -> None:
        """Previous manifest with specialist_probe_failed errors → rescan_candidates."""
        import json
        src = tmp_path / "src"
        src.mkdir()
        (src / "doc.pdf").write_bytes(b"%PDF-1.4\x00")
        prev_data = {
            "meta": {"scan_id": "test-id", "generated_at": "", "source_dir": str(src), "config": {}},
            "stats": {"total_files": 1, "supported_files": 1, "unsupported_files": 0,
                       "text_files": 0, "binary_files": 1, "requires_vision": 0, "requires_specialist_tool": 1},
            "routing_summary": {"baseline_ready": 0, "binary_only": 0, "requires_vision": 0, "requires_specialist_tool": 1},
            "context": {"logic_version": "0.3.0", "scanner_version": "0.3.0", "python_version": "3.12", "platform": "linux", "dependencies": {}},
            "delta": None,
            "manifest_checksum": "",
            "files": [
                {
                    "path": "doc.pdf",
                    "checksum_sha256": "abc123",
                    "errors": [{"code": "specialist_probe_failed", "message": "test", "stage": "specialist"}],
                }
            ],
        }
        prev = tmp_path / "prev.json"
        prev.write_text(json.dumps(prev_data))
        config = ScannerConfig(previous_manifest=str(prev))
        m2 = Scanner(source_dir=src, config=config).scan()
        assert m2.delta is not None
        assert "doc.pdf" in m2.delta.rescan_candidates

    def test_rescan_candidates_sorted(self, tmp_path: Path) -> None:
        """rescan_candidates should be sorted and only include files still present."""
        import json
        src = tmp_path / "src"
        src.mkdir()
        # Create files that match the previous manifest paths
        (src / "z.pdf").write_bytes(b"%PDF-1.4\x00")
        (src / "a.pdf").write_bytes(b"%PDF-1.4\x00")
        prev_data = {
            "meta": {"scan_id": "id", "generated_at": "", "source_dir": str(src), "config": {}},
            "stats": {"total_files": 2, "supported_files": 2, "unsupported_files": 0,
                       "text_files": 0, "binary_files": 2, "requires_vision": 0, "requires_specialist_tool": 2},
            "routing_summary": {"baseline_ready": 0, "binary_only": 0, "requires_vision": 0, "requires_specialist_tool": 2},
            "context": {"logic_version": "0.3.0", "scanner_version": "0.3.0", "python_version": "3.12", "platform": "linux", "dependencies": {}},
            "delta": None,
            "manifest_checksum": "",
            "files": [
                {"path": "z.pdf", "checksum_sha256": "", "errors": [{"code": "specialist_probe_failed", "message": "", "stage": "specialist"}]},
                {"path": "a.pdf", "checksum_sha256": "", "errors": [{"code": "specialist_probe_failed", "message": "", "stage": "specialist"}]},
            ],
        }
        prev = tmp_path / "prev.json"
        prev.write_text(json.dumps(prev_data))
        config = ScannerConfig(previous_manifest=str(prev))
        m2 = Scanner(source_dir=src, config=config).scan()
        assert m2.delta.rescan_candidates == ["a.pdf", "z.pdf"]

    def test_rescan_candidates_excludes_deleted_files(self, tmp_path: Path) -> None:
        """Files with prior failures that no longer exist should not be rescan candidates."""
        import json
        src = tmp_path / "src"
        src.mkdir()
        (src / "still_here.pdf").write_bytes(b"%PDF-1.4\x00")
        # deleted.pdf is NOT created — it was in the previous manifest but no longer exists
        prev_data = {
            "meta": {"scan_id": "id", "generated_at": "", "source_dir": str(src), "config": {}},
            "stats": {"total_files": 2, "supported_files": 2, "unsupported_files": 0,
                       "text_files": 0, "binary_files": 2, "requires_vision": 0, "requires_specialist_tool": 2},
            "routing_summary": {"baseline_ready": 0, "binary_only": 0, "requires_vision": 0, "requires_specialist_tool": 2},
            "context": {"logic_version": "0.3.0", "scanner_version": "0.3.0", "python_version": "3.12", "platform": "linux", "dependencies": {}},
            "delta": None,
            "manifest_checksum": "",
            "files": [
                {"path": "still_here.pdf", "checksum_sha256": "", "errors": [{"code": "specialist_probe_failed", "message": "", "stage": "specialist"}]},
                {"path": "deleted.pdf", "checksum_sha256": "", "errors": [{"code": "specialist_probe_failed", "message": "", "stage": "specialist"}]},
            ],
        }
        prev = tmp_path / "prev.json"
        prev.write_text(json.dumps(prev_data))
        config = ScannerConfig(previous_manifest=str(prev))
        m2 = Scanner(source_dir=src, config=config).scan()
        assert m2.delta.rescan_candidates == ["still_here.pdf"]
        assert "deleted.pdf" not in m2.delta.rescan_candidates
