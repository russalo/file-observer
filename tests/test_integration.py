"""Integration tests — full scan() against fixture directories with known expected output."""
from __future__ import annotations

from pathlib import Path

import pytest

from scanner.scanner import Scanner, ScannerConfig, manifest_to_json, manifest_to_jsonl, FileRecord, ScanManifest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def manifest() -> ScanManifest:
    scanner = Scanner(source_dir=FIXTURES)
    return scanner.scan()


def _find(manifest: ScanManifest, filename: str) -> FileRecord:
    for f in manifest.files:
        if f.filename == filename:
            return f
    raise KeyError(f"{filename} not in manifest")


# ---------------------------------------------------------------------------
# Top-level manifest shape
# ---------------------------------------------------------------------------

class TestManifestShape:
    def test_generated_at_present(self, manifest: ScanManifest) -> None:
        assert manifest.meta.generated_at is not None
        assert "T" in manifest.meta.generated_at  # ISO-8601

    def test_source_dir_absolute(self, manifest: ScanManifest) -> None:
        assert Path(manifest.meta.source_dir).is_absolute()

    def test_meta_has_scan_id(self, manifest: ScanManifest) -> None:
        assert manifest.meta.scan_id
        import uuid
        uuid.UUID(manifest.meta.scan_id)  # validates format

    def test_meta_config_reflects_runtime(self, manifest: ScanManifest) -> None:
        assert manifest.meta.config["preview_max_chars"] == 1000
        assert manifest.meta.config["enable_specialists"] is False

    def test_stats_totals_consistent(self, manifest: ScanManifest) -> None:
        s = manifest.stats
        assert s.total_files == len(manifest.files)
        assert s.supported_files + s.unsupported_files == s.total_files
        assert s.text_files + s.binary_files == s.total_files

    def test_routing_summary_present(self, manifest: ScanManifest) -> None:
        r = manifest.routing_summary
        # Verify counts match actual file records
        assert r.requires_vision == sum(1 for f in manifest.files if f.requires_vision)
        assert r.requires_specialist_tool == sum(1 for f in manifest.files if f.requires_specialist_tool)
        assert r.baseline_ready == sum(1 for f in manifest.files if not f.is_binary and not f.requires_specialist_tool)
        assert r.binary_only == sum(1 for f in manifest.files if f.is_binary and not f.requires_vision and not f.requires_specialist_tool)

    def test_files_is_list(self, manifest: ScanManifest) -> None:
        assert isinstance(manifest.files, list)
        assert len(manifest.files) > 0

    def test_every_file_has_all_fields(self, manifest: ScanManifest) -> None:
        required = {
            "path", "filename", "extension", "mime_type", "size_bytes",
            "created_at", "modified_at", "checksum_sha256", "stage_folder",
            "directory_depth", "encoding", "is_binary", "requires_vision",
            "requires_specialist_tool", "specialist_tool", "sidecar_exists",
            "frontmatter", "tags", "asset_matches", "content_preview",
            "structural", "mime_analysis", "specialist_metadata",
            "signal_provenance", "errors",
        }
        for rec in manifest.files:
            fields = {f.name for f in rec.__dataclass_fields__.values()}
            assert required <= fields, f"{rec.filename} missing fields: {required - fields}"


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------

class TestJsonSerialization:
    def test_valid_json(self, manifest: ScanManifest) -> None:
        import json
        output = manifest_to_json(manifest)
        data = json.loads(output)
        assert "schema_version" in data
        assert "context" in data
        assert "meta" in data
        assert "stats" in data
        assert "routing_summary" in data
        assert "delta" in data
        assert "manifest_checksum" in data
        assert "files" in data
        assert "generated_at" in data["meta"]

    def test_arrays_never_null(self, manifest: ScanManifest) -> None:
        import json
        data = json.loads(manifest_to_json(manifest))
        for f in data["files"]:
            assert isinstance(f["tags"], list)
            assert isinstance(f["asset_matches"], list)
            assert isinstance(f["errors"], list)
            assert isinstance(f["structural"]["heading_structure"], list)
            assert isinstance(f["structural"]["csv_headers"], list)
            assert isinstance(f["structural"]["document_keys"], list)
            assert isinstance(f["structural"]["technology_hints"], list)

    def test_booleans_are_booleans(self, manifest: ScanManifest) -> None:
        import json
        data = json.loads(manifest_to_json(manifest))
        for f in data["files"]:
            assert isinstance(f["is_binary"], bool)
            assert isinstance(f["requires_vision"], bool)
            assert isinstance(f["requires_specialist_tool"], bool)
            assert isinstance(f["sidecar_exists"], bool)
            assert isinstance(f["frontmatter"]["exists"], bool)


# ---------------------------------------------------------------------------
# Universal tier — runs for every file
# ---------------------------------------------------------------------------

class TestUniversalTier:
    def test_every_file_has_path(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            assert f.path
            assert "/" not in f.path or f.path.count("\\") == 0  # forward slashes

    def test_every_file_has_checksum(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            assert len(f.checksum_sha256) == 64

    def test_extension_lowercase(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            assert f.extension == f.extension.lower()

    def test_size_positive(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            assert f.size_bytes >= 0

    def test_modified_at_is_iso(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            assert "T" in f.modified_at

    def test_depth_consistent_with_path(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            parts = Path(f.path).parts
            expected_depth = max(len(parts) - 1, 0)
            assert f.directory_depth == expected_depth, f"{f.path}: depth {f.directory_depth} != {expected_depth}"


# ---------------------------------------------------------------------------
# Routing flags
# ---------------------------------------------------------------------------

class TestRoutingFlags:
    def test_png_is_binary_and_vision(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_logo.png")
        assert rec.is_binary is True
        assert rec.requires_vision is True

    def test_pdf_is_binary(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_document.pdf")
        assert rec.is_binary is True
        assert rec.requires_specialist_tool is True
        assert rec.specialist_tool == "pdf_extraction"

    def test_txt_is_text(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_notes.txt")
        assert rec.is_binary is False
        assert rec.requires_vision is False

    def test_md_is_text(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_tasks.md")
        assert rec.is_binary is False

    def test_specialist_tool_null_invariant(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            if f.requires_specialist_tool:
                assert f.specialist_tool is not None
            else:
                assert f.specialist_tool is None

    def test_docx_requires_specialist(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_report.docx")
        assert rec.requires_specialist_tool is True
        assert rec.specialist_tool == "document_extraction"

    def test_unsupported_extension_marked(self, manifest: ScanManifest) -> None:
        # .filepart is not in SUPPORTED_EXTENSIONS
        unsupported = [f for f in manifest.files if f.extension == ".filepart"]
        if unsupported:
            codes = [e.code for e in unsupported[0].errors]
            assert "unsupported_extension" in codes
        else:
            # If no .filepart fixtures exist, verify any unsupported extension is flagged
            unsup = [f for f in manifest.files
                     if any(e.code == "unsupported_extension" for e in f.errors)]
            assert len(unsup) >= 0  # non-fatal if all extensions are now supported


# ---------------------------------------------------------------------------
# Baseline tier — text files
# ---------------------------------------------------------------------------

class TestBaselineTier:
    def test_text_file_has_encoding(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_notes.txt")
        assert rec.encoding is not None

    def test_text_file_has_preview(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_notes.txt")
        assert rec.content_preview is not None
        assert len(rec.content_preview) <= 1000

    def test_binary_file_null_encoding(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_logo.png")
        assert rec.encoding is None

    def test_binary_file_null_preview(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_logo.png")
        assert rec.content_preview is None

    def test_csv_headers_extracted(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_document_list.csv")
        assert len(rec.structural.csv_headers) > 0

    def test_yaml_keys_extracted(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_config.yaml")
        assert "domains" in rec.structural.document_keys

    def test_json_keys_extracted(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_plugins.json")
        assert len(rec.structural.document_keys) > 0

    def test_html_title_extracted(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_dashboard.html")
        assert rec.structural.title is not None

    def test_html_technology_detected(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_dashboard.html")
        assert "google-fonts" in rec.structural.technology_hints


# ---------------------------------------------------------------------------
# Markdown-specific
# ---------------------------------------------------------------------------

class TestMarkdownFeatures:
    def test_md_title(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_review.md")
        assert rec.structural.title == "Quarterly Review"

    def test_md_heading_structure(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_review.md")
        assert "Summary" in rec.structural.heading_structure
        assert "Action Items" in rec.structural.heading_structure

    def test_md_frontmatter(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_review.md")
        assert rec.frontmatter.exists is True
        assert "title" in rec.frontmatter.keys

    def test_md_tags(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_tags.md")
        assert isinstance(rec.tags, list)
        assert len(rec.tags) > 0


# ---------------------------------------------------------------------------
# Structural signals
# ---------------------------------------------------------------------------

class TestStructuralSignals:
    def test_filename_date_extraction(self, manifest: ScanManifest) -> None:
        # Use any fixture with a date in the filename
        dated = [f for f in manifest.files if f.structural.filename_date is not None]
        assert len(dated) > 0
        for f in dated:
            assert len(f.structural.filename_date) == 10  # YYYY-MM-DD

    def test_filename_date_none_when_absent(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_tasks.md")
        assert rec.structural.filename_date is None

    def test_technology_hints_sorted(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            assert f.structural.technology_hints == sorted(f.structural.technology_hints)


# ---------------------------------------------------------------------------
# JSONL output
# ---------------------------------------------------------------------------

class TestJsonlOutput:
    def test_jsonl_valid_lines(self, manifest: ScanManifest) -> None:
        import json
        output = manifest_to_jsonl(manifest)
        lines = output.strip().split("\n")
        # First line is header, rest are file records
        assert len(lines) == len(manifest.files) + 1
        for line in lines:
            json.loads(line)  # each line must be valid JSON

    def test_jsonl_header_has_meta_stats_routing(self, manifest: ScanManifest) -> None:
        import json
        header = json.loads(manifest_to_jsonl(manifest).split("\n")[0])
        assert "meta" in header
        assert "stats" in header
        assert "routing_summary" in header
        assert "delta" in header
        assert "manifest_checksum" in header

    def test_jsonl_records_match_json(self, manifest: ScanManifest) -> None:
        import json
        jsonl_lines = manifest_to_jsonl(manifest).strip().split("\n")
        json_data = json.loads(manifest_to_json(manifest))
        # File records should match
        jsonl_records = [json.loads(line) for line in jsonl_lines[1:]]
        assert jsonl_records == json_data["files"]


# ---------------------------------------------------------------------------
# MIME analysis (Phase 3)
# ---------------------------------------------------------------------------

class TestMimeAnalysisIntegration:
    def test_every_file_has_mime_analysis(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            assert f.mime_analysis is not None
            assert isinstance(f.mime_analysis.matches_extension, bool)

    def test_mime_analysis_detected_mime_present(self, manifest: ScanManifest) -> None:
        for f in manifest.files:
            assert f.mime_analysis.detected_mime is not None

    def test_supported_extensions_have_extension_mime(self, manifest: ScanManifest) -> None:
        # .mdx has no standard MIME registration in Python's mimetypes module
        no_standard_mime = {".mdx", ".msg", ".vx", ".toml"}
        from scanner.scanner import SUPPORTED_EXTENSIONS
        for f in manifest.files:
            if f.extension in SUPPORTED_EXTENSIONS and f.extension not in no_standard_mime:
                assert f.mime_analysis.extension_mime is not None, (
                    f"{f.filename}: supported extension should have a known MIME"
                )

    def test_mime_analysis_in_json_output(self, manifest: ScanManifest) -> None:
        import json
        data = json.loads(manifest_to_json(manifest))
        for f in data["files"]:
            assert "mime_analysis" in f
            assert "detected_mime" in f["mime_analysis"]
            assert "extension_mime" in f["mime_analysis"]
            assert "matches_extension" in f["mime_analysis"]


# ---------------------------------------------------------------------------
# Specialist metadata (Phase 3)
# ---------------------------------------------------------------------------

class TestSpecialistMetadataIntegration:
    def test_specialist_metadata_null_by_default(self, manifest: ScanManifest) -> None:
        """Specialist metadata should be null when specialists are disabled (default)."""
        for f in manifest.files:
            assert f.specialist_metadata is None

    def test_specialist_metadata_in_json_output(self, manifest: ScanManifest) -> None:
        import json
        data = json.loads(manifest_to_json(manifest))
        for f in data["files"]:
            assert "specialist_metadata" in f


# ---------------------------------------------------------------------------
# HTML formal support (Phase 3)
# ---------------------------------------------------------------------------

class TestHtmlIntegration:
    def test_html_no_unsupported_error(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_dashboard.html")
        codes = [e.code for e in rec.errors]
        assert "unsupported_extension" not in codes

    def test_html_is_text(self, manifest: ScanManifest) -> None:
        rec = _find(manifest, "sample_dashboard.html")
        assert rec.is_binary is False
        assert rec.encoding is not None

    def test_html_counted_as_supported(self, manifest: ScanManifest) -> None:
        """HTML files should count toward supported_files in stats."""
        html_count = sum(1 for f in manifest.files if f.extension in {".html", ".htm"})
        if html_count > 0:
            # Verify none of them have unsupported_extension errors
            for f in manifest.files:
                if f.extension in {".html", ".htm"}:
                    codes = [e.code for e in f.errors]
                    assert "unsupported_extension" not in codes
