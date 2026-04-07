"""Unit tests for individual extraction methods in Scanner."""
from __future__ import annotations

from pathlib import Path

import pytest

from scanner.scanner import Scanner, ScannerConfig, ErrorRecord


@pytest.fixture
def scanner(tmp_path: Path) -> Scanner:
    return Scanner(source_dir=tmp_path)


# ---------------------------------------------------------------------------
# extract_tags
# ---------------------------------------------------------------------------

class TestExtractTags:
    def test_basic_hashtags(self, scanner: Scanner) -> None:
        text = "Hello #world and #python are great"
        assert scanner.extract_tags(text) == ["python", "world"]

    def test_deduplicated_and_sorted(self, scanner: Scanner) -> None:
        text = "#beta #alpha #beta #alpha"
        assert scanner.extract_tags(text) == ["alpha", "beta"]

    def test_hex_colors_filtered(self, scanner: Scanner) -> None:
        text = "Color is #ff0000 and #abc but #real-tag stays"
        tags = scanner.extract_tags(text)
        assert "ff0000" not in tags
        assert "abc" not in tags
        assert "real-tag" in tags

    def test_stop_words_filtered(self, scanner: Scanner) -> None:
        text = "#tags #tag #hashtag #hashtags #keepme"
        assert scanner.extract_tags(text) == ["keepme"]

    def test_code_blocks_stripped(self, scanner: Scanner) -> None:
        text = "Outside #visible\n```\n#hidden\n```\nAlso `#inline-hidden` here"
        tags = scanner.extract_tags(text)
        assert "visible" in tags
        assert "hidden" not in tags
        assert "inline-hidden" not in tags

    def test_empty_text(self, scanner: Scanner) -> None:
        assert scanner.extract_tags("") == []

    def test_no_tags(self, scanner: Scanner) -> None:
        assert scanner.extract_tags("No tags here at all") == []

    def test_tag_with_slashes_and_hyphens(self, scanner: Scanner) -> None:
        text = "#my-tag #some/nested"
        tags = scanner.extract_tags(text)
        assert "my-tag" in tags
        assert "some/nested" in tags


# ---------------------------------------------------------------------------
# extract_frontmatter
# ---------------------------------------------------------------------------

class TestExtractFrontmatter:
    def test_valid_frontmatter(self, scanner: Scanner) -> None:
        text = "---\ntitle: Hello\ndate: 2026-01-01\n---\nBody text"
        fm = scanner.extract_frontmatter(text)
        assert fm.exists is True
        assert "title" in fm.keys
        assert "date" in fm.keys
        assert "title: Hello" in fm.raw

    def test_no_frontmatter(self, scanner: Scanner) -> None:
        text = "Just a plain document\nwith no frontmatter"
        fm = scanner.extract_frontmatter(text)
        assert fm.exists is False
        assert fm.keys == []
        assert fm.raw is None

    def test_malformed_frontmatter_missing_closing(self, scanner: Scanner) -> None:
        text = "---\ntitle: Broken\nThis never closes"
        fm = scanner.extract_frontmatter(text)
        assert fm.exists is False
        assert fm.raw is not None  # raw preserved for malformed

    def test_frontmatter_keys_sorted_and_deduplicated(self, scanner: Scanner) -> None:
        text = "---\nzebra: 1\nalpha: 2\nalpha: 3\n---\nBody"
        fm = scanner.extract_frontmatter(text)
        assert fm.keys == ["alpha", "zebra"]

    def test_frontmatter_not_mid_document(self, scanner: Scanner) -> None:
        text = "Some text\n---\ntitle: Hidden\n---\nMore text"
        fm = scanner.extract_frontmatter(text)
        assert fm.exists is False


# ---------------------------------------------------------------------------
# extract_assets
# ---------------------------------------------------------------------------

class TestExtractAssets:
    def test_local_assets(self, scanner: Scanner) -> None:
        text = "![logo](images/logo.png)\n[doc](./readme.md)"
        assets = scanner.extract_assets(text)
        assert "images/logo.png" in assets
        assert "./readme.md" in assets

    def test_http_excluded(self, scanner: Scanner) -> None:
        text = "![img](https://example.com/pic.png)\n[link](http://example.com)"
        assert scanner.extract_assets(text) == []

    def test_deduplicated_and_sorted(self, scanner: Scanner) -> None:
        text = "![a](b.png)\n![c](a.png)\n![d](b.png)"
        assert scanner.extract_assets(text) == ["a.png", "b.png"]

    def test_empty_text(self, scanner: Scanner) -> None:
        assert scanner.extract_assets("") == []


# ---------------------------------------------------------------------------
# extract_csv_headers
# ---------------------------------------------------------------------------

class TestExtractCsvHeaders:
    def test_basic_headers(self, scanner: Scanner) -> None:
        text = "Name,Age,City\nAlice,30,NY"
        assert scanner.extract_csv_headers(text) == ["Name", "Age", "City"]

    def test_quoted_headers(self, scanner: Scanner) -> None:
        text = '"First Name","Last Name"\nJohn,Doe'
        assert scanner.extract_csv_headers(text) == ["First Name", "Last Name"]

    def test_numeric_first_row_not_headers(self, scanner: Scanner) -> None:
        text = "1,2,3\n4,5,6"
        assert scanner.extract_csv_headers(text) == []

    def test_empty_text(self, scanner: Scanner) -> None:
        assert scanner.extract_csv_headers("") == []


# ---------------------------------------------------------------------------
# extract_json_keys
# ---------------------------------------------------------------------------

class TestExtractJsonKeys:
    def test_object_keys(self, scanner: Scanner) -> None:
        text = '{"beta": 1, "alpha": 2}'
        assert scanner.extract_json_keys(text) == ["alpha", "beta"]

    def test_array_returns_empty(self, scanner: Scanner) -> None:
        assert scanner.extract_json_keys("[1, 2, 3]") == []

    def test_invalid_json(self, scanner: Scanner) -> None:
        assert scanner.extract_json_keys("{broken") == []

    def test_empty_object(self, scanner: Scanner) -> None:
        assert scanner.extract_json_keys("{}") == []


# ---------------------------------------------------------------------------
# extract_yaml_keys
# ---------------------------------------------------------------------------

class TestExtractYamlKeys:
    def test_top_level_keys(self, scanner: Scanner) -> None:
        text = "name: test\nversion: 1.0\n  nested: ignored"
        keys = scanner.extract_yaml_keys(text)
        assert "name" in keys
        assert "version" in keys
        assert "nested" not in keys

    def test_comments_skipped(self, scanner: Scanner) -> None:
        text = "# comment\nname: test"
        keys = scanner.extract_yaml_keys(text)
        assert keys == ["name"]

    def test_document_separator_skipped(self, scanner: Scanner) -> None:
        text = "---\nname: test"
        keys = scanner.extract_yaml_keys(text)
        assert keys == ["name"]


# ---------------------------------------------------------------------------
# detect_binary
# ---------------------------------------------------------------------------

class TestDetectBinary:
    def test_nul_byte_triggers_binary(self, scanner: Scanner) -> None:
        assert scanner.detect_binary(b"hello\x00world", "text/plain") is True

    def test_image_mime_triggers_binary(self, scanner: Scanner) -> None:
        assert scanner.detect_binary(b"fakepng", "image/png") is True

    def test_pdf_mime_triggers_binary(self, scanner: Scanner) -> None:
        assert scanner.detect_binary(b"%PDF-1.4", "application/pdf") is True

    def test_plain_text_not_binary(self, scanner: Scanner) -> None:
        assert scanner.detect_binary(b"Hello world\n", "text/plain") is False

    def test_empty_sample_not_binary(self, scanner: Scanner) -> None:
        assert scanner.detect_binary(b"", "text/plain") is False

    def test_json_mime_not_binary(self, scanner: Scanner) -> None:
        assert scanner.detect_binary(b'{"key": "value"}', "application/json") is False

    def test_low_text_ratio_triggers_binary(self, scanner: Scanner) -> None:
        sample = bytes(range(0, 32)) * 10  # mostly control chars
        assert scanner.detect_binary(sample, "text/plain") is True


# ---------------------------------------------------------------------------
# detect_requires_vision
# ---------------------------------------------------------------------------

class TestDetectRequiresVision:
    def test_image_mime(self, scanner: Scanner) -> None:
        assert scanner.detect_requires_vision(b"", "image/png", ".png", True) is True
        assert scanner.detect_requires_vision(b"", "image/jpeg", ".jpg", True) is True

    def test_pdf_with_text_markers(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 /Font /Text BT\n"
        assert scanner.detect_requires_vision(sample, "application/pdf", ".pdf", True) is False

    def test_pdf_without_text_markers(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 just image data"
        assert scanner.detect_requires_vision(sample, "application/pdf", ".pdf", True) is True

    def test_text_file_no_vision(self, scanner: Scanner) -> None:
        assert scanner.detect_requires_vision(b"hello", "text/plain", ".txt", False) is False


# ---------------------------------------------------------------------------
# detect_mime
# ---------------------------------------------------------------------------

class TestDetectMime:
    def test_known_extension_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "test.json"
        f.write_text("{}")
        scanner = Scanner(source_dir=tmp_path)
        # force no magic
        scanner._magic = None
        errors: list[ErrorRecord] = []
        mime = scanner.detect_mime(f, errors)
        assert mime == "application/json"
        assert any(e.code == "mime_type_fallback" for e in errors)

    def test_unknown_extension_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "test.xyz123"
        f.write_bytes(b"\x00\x01\x02")
        scanner = Scanner(source_dir=tmp_path)
        scanner._magic = None
        errors: list[ErrorRecord] = []
        mime = scanner.detect_mime(f, errors)
        assert mime == "application/octet-stream"


# ---------------------------------------------------------------------------
# looks_like_text
# ---------------------------------------------------------------------------

class TestLooksLikeText:
    def test_ascii_text(self, scanner: Scanner) -> None:
        assert scanner.looks_like_text(b"Hello, World!\n") is True

    def test_empty_sample(self, scanner: Scanner) -> None:
        assert scanner.looks_like_text(b"") is True

    def test_binary_sample(self, scanner: Scanner) -> None:
        sample = bytes(range(0, 20))
        assert scanner.looks_like_text(sample) is False

    def test_utf8_text(self, scanner: Scanner) -> None:
        assert scanner.looks_like_text("Héllo wörld".encode("utf-8")) is True


# ---------------------------------------------------------------------------
# extract_filename_date
# ---------------------------------------------------------------------------

class TestExtractFilenameDate:
    def test_date_with_hyphens(self, scanner: Scanner) -> None:
        assert scanner.extract_filename_date("report-2026-04-02.md") == "2026-04-02"

    def test_date_with_underscores(self, scanner: Scanner) -> None:
        assert scanner.extract_filename_date("log_2025_07_18.txt") == "2025-07-18"

    def test_no_date(self, scanner: Scanner) -> None:
        assert scanner.extract_filename_date("readme.md") is None

    def test_date_in_middle(self, scanner: Scanner) -> None:
        assert scanner.extract_filename_date("backup-2026-01-15-final.tar") == "2026-01-15"


# ---------------------------------------------------------------------------
# detect_technology
# ---------------------------------------------------------------------------

class TestDetectTechnology:
    def test_google_fonts(self, scanner: Scanner) -> None:
        text = '<link href="https://fonts.googleapis.com/css2?family=Inter">'
        assert "google-fonts" in scanner.detect_technology(text)

    def test_react(self, scanner: Scanner) -> None:
        text = "import react-dom from 'react-dom'"
        assert "react" in scanner.detect_technology(text)

    def test_tailwind(self, scanner: Scanner) -> None:
        text = 'cdn.tailwindcss.com'
        assert "tailwind" in scanner.detect_technology(text)

    def test_no_matches(self, scanner: Scanner) -> None:
        assert scanner.detect_technology("plain text no frameworks") == []

    def test_multiple_detected(self, scanner: Scanner) -> None:
        text = 'fonts.googleapis.com react-dom bootstrap.min.css'
        techs = scanner.detect_technology(text)
        assert "google-fonts" in techs
        assert "react" in techs
        assert "bootstrap" in techs

    def test_sorted_output(self, scanner: Scanner) -> None:
        text = 'react-dom bootstrap.min.css fonts.googleapis.com'
        techs = scanner.detect_technology(text)
        assert techs == sorted(techs)


# ---------------------------------------------------------------------------
# extract_md_title / extract_html_title / extract_heading_structure
# ---------------------------------------------------------------------------

class TestTitleExtraction:
    def test_md_h1_title(self, scanner: Scanner) -> None:
        text = "# My Title\n\nBody text\n## Section"
        assert scanner.extract_md_title(text) == "My Title"

    def test_md_no_h1(self, scanner: Scanner) -> None:
        text = "## Only H2\n### And H3"
        assert scanner.extract_md_title(text) is None

    def test_md_first_h1_wins(self, scanner: Scanner) -> None:
        text = "# First\n# Second"
        assert scanner.extract_md_title(text) == "First"

    def test_html_title(self, scanner: Scanner) -> None:
        text = "<html><head><title>My Page</title></head></html>"
        assert scanner.extract_html_title(text) == "My Page"

    def test_html_empty_title(self, scanner: Scanner) -> None:
        text = "<title></title>"
        assert scanner.extract_html_title(text) is None

    def test_html_no_title(self, scanner: Scanner) -> None:
        assert scanner.extract_html_title("<html></html>") is None


class TestHeadingStructure:
    def test_extracts_h2_only(self, scanner: Scanner) -> None:
        text = "# Title\n## First\n### Sub\n## Second"
        assert scanner.extract_heading_structure(text) == ["First", "Second"]

    def test_no_headings(self, scanner: Scanner) -> None:
        assert scanner.extract_heading_structure("No headings here") == []

    def test_preserves_order(self, scanner: Scanner) -> None:
        text = "## Zebra\n## Alpha"
        assert scanner.extract_heading_structure(text) == ["Zebra", "Alpha"]


# ---------------------------------------------------------------------------
# make_preview
# ---------------------------------------------------------------------------

class TestMakePreview:
    def test_basic_truncation(self) -> None:
        config = ScannerConfig()
        config.preview_max_chars = 10
        scanner = Scanner(source_dir=Path("."), config=config)
        assert scanner.make_preview("Hello World, this is long") == "Hello Worl"

    def test_strips_control_characters(self, scanner: Scanner) -> None:
        text = "Hello\x00\x01\x02\x03\x0eWorld"
        preview = scanner.make_preview(text)
        assert "\x00" not in preview
        assert "\x01" not in preview
        assert "\x02" not in preview
        assert "\x0e" not in preview
        assert "HelloWorld" in preview

    def test_preserves_tabs_and_newlines(self, scanner: Scanner) -> None:
        text = "Line1\tTabbed\nLine2\rLine3"
        preview = scanner.make_preview(text)
        assert "\t" in preview
        assert "\n" in preview

    def test_empty_text(self, scanner: Scanner) -> None:
        assert scanner.make_preview("") == ""

    def test_whitespace_only(self, scanner: Scanner) -> None:
        assert scanner.make_preview("   \n\t  ") == ""


# ---------------------------------------------------------------------------
# detect_sidecar
# ---------------------------------------------------------------------------

class TestDetectSidecar:
    def test_json_sidecar(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("content")
        (tmp_path / "report.md.json").write_text("{}")
        scanner = Scanner(source_dir=tmp_path)
        assert scanner.detect_sidecar(f) is True

    def test_md_sidecar(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b")
        (tmp_path / "data.csv.md").write_text("notes")
        scanner = Scanner(source_dir=tmp_path)
        assert scanner.detect_sidecar(f) is True

    def test_stem_json_sidecar(self, tmp_path: Path) -> None:
        f = tmp_path / "report.md"
        f.write_text("content")
        (tmp_path / "report.json").write_text("{}")
        scanner = Scanner(source_dir=tmp_path)
        assert scanner.detect_sidecar(f) is True

    def test_no_sidecar(self, tmp_path: Path) -> None:
        f = tmp_path / "alone.txt"
        f.write_text("content")
        scanner = Scanner(source_dir=tmp_path)
        assert scanner.detect_sidecar(f) is False


# ---------------------------------------------------------------------------
# tags_from_frontmatter
# ---------------------------------------------------------------------------

class TestTagsFromFrontmatter:
    def test_comma_separated(self, scanner: Scanner) -> None:
        raw = "tags: alpha, beta, gamma"
        assert scanner.tags_from_frontmatter(raw) == ["alpha", "beta", "gamma"]

    def test_bracket_syntax(self, scanner: Scanner) -> None:
        raw = "tags: [one, two, three]"
        tags = scanner.tags_from_frontmatter(raw)
        assert "one" in tags
        assert "two" in tags

    def test_quoted_values(self, scanner: Scanner) -> None:
        raw = "tags: 'alpha', \"beta\""
        tags = scanner.tags_from_frontmatter(raw)
        assert "alpha" in tags
        assert "beta" in tags

    def test_no_tags_line(self, scanner: Scanner) -> None:
        assert scanner.tags_from_frontmatter("title: hello") == []


# ---------------------------------------------------------------------------
# hash_file
# ---------------------------------------------------------------------------

class TestHashFile:
    def test_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("consistent content")
        scanner = Scanner(source_dir=tmp_path)
        h1 = scanner.hash_file(f)
        h2 = scanner.hash_file(f)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex length

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")
        scanner = Scanner(source_dir=tmp_path)
        assert scanner.hash_file(f1) != scanner.hash_file(f2)

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        scanner = Scanner(source_dir=tmp_path)
        h = scanner.hash_file(f)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# analyze_mime
# ---------------------------------------------------------------------------

class TestAnalyzeMime:
    def test_matching_text(self, scanner: Scanner) -> None:
        result = scanner.analyze_mime(Path("fake.txt"), "text/plain", ".txt")
        assert result.detected_mime == "text/plain"
        assert result.extension_mime == "text/plain"
        assert result.matches_extension is True

    def test_mismatch(self, scanner: Scanner) -> None:
        result = scanner.analyze_mime(Path("fake.txt"), "image/png", ".txt")
        assert result.detected_mime == "image/png"
        assert result.extension_mime == "text/plain"
        assert result.matches_extension is False

    def test_unknown_extension(self, scanner: Scanner) -> None:
        result = scanner.analyze_mime(Path("file.xyzabc"), "application/octet-stream", ".xyzabc")
        assert result.extension_mime is None
        assert result.matches_extension is True

    def test_json_match(self, scanner: Scanner) -> None:
        result = scanner.analyze_mime(Path("data.json"), "application/json", ".json")
        assert result.matches_extension is True

    def test_pdf_match(self, scanner: Scanner) -> None:
        result = scanner.analyze_mime(Path("doc.pdf"), "application/pdf", ".pdf")
        assert result.matches_extension is True


# ---------------------------------------------------------------------------
# extract_specialist_metadata (PDF)
# ---------------------------------------------------------------------------

class TestExtractSpecialistMetadata:
    def test_pdf_with_all_fields(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 /Font /Count 7 /Title (My Report) /Author (Jane) /Producer (LaTeX) /Creator (pdfTeX) /CreationDate (D:20260101)"
        meta = scanner.extract_specialist_metadata(Path("doc.pdf"), ".pdf", sample)
        assert meta is not None
        assert meta["has_text_streams"] is True
        assert meta["page_count"] == 7
        assert meta["title"] == "My Report"
        assert meta["author"] == "Jane"
        assert meta["producer"] == "LaTeX"
        assert meta["creator"] == "pdfTeX"
        assert meta["creation_date"] == "D:20260101"

    def test_pdf_minimal(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 image only"
        meta = scanner.extract_specialist_metadata(Path("scan.pdf"), ".pdf", sample)
        assert meta is not None
        assert meta["has_text_streams"] is False
        assert meta["page_count"] is None
        assert meta["title"] is None
        assert meta["author"] is None

    def test_non_pdf_returns_none(self, scanner: Scanner) -> None:
        assert scanner.extract_specialist_metadata(Path("a.txt"), ".txt", b"hello") is None
        assert scanner.extract_specialist_metadata(Path("a.csv"), ".csv", b"a,b") is None
        assert scanner.extract_specialist_metadata(Path("a.docx"), ".docx", b"PK") is None
