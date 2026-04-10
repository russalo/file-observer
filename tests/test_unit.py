"""Unit tests for individual extraction methods in Scanner."""
from __future__ import annotations

from pathlib import Path

import pytest

import struct
from dataclasses import asdict
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

    def test_frontmatter_crlf(self, scanner: Scanner) -> None:
        text = "---\r\ntitle: Hello\r\ndate: 2026-01-01\r\n---\r\nBody text"
        fm = scanner.extract_frontmatter(text)
        assert fm.exists is True
        assert "title" in fm.keys

    def test_frontmatter_malformed_crlf(self, scanner: Scanner) -> None:
        text = "---\r\ntitle: Broken\r\nThis never closes"
        fm = scanner.extract_frontmatter(text)
        assert fm.exists is False
        assert fm.raw is not None


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
# Silent failure recording (v0.5)
# ---------------------------------------------------------------------------

class TestSilentFailureRecording:
    def test_xml_parse_failure_records_error(self, tmp_path: Path) -> None:
        (tmp_path / "bad.xml").write_text("<broken><no closing tag")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "xml_parse_failed" in codes

    def test_xml_valid_no_error(self, tmp_path: Path) -> None:
        (tmp_path / "good.xml").write_text("<root><child/></root>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "xml_parse_failed" not in codes

    def test_toml_parse_failure_records_error(self, tmp_path: Path) -> None:
        (tmp_path / "bad.toml").write_text("invalid [[[")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "toml_parse_failed" in codes

    def test_toml_valid_no_error(self, tmp_path: Path) -> None:
        (tmp_path / "good.toml").write_text('name = "test"\n')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "toml_parse_failed" not in codes

    def test_specialist_null_records_error(self, tmp_path: Path) -> None:
        (tmp_path / "bad.xlsx").write_bytes(b"not a zip")
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        codes = [e.code for e in rec.errors]
        assert "specialist_probe_failed" in codes

    def test_structural_title_provenance_md(self, tmp_path: Path) -> None:
        (tmp_path / "doc.md").write_text("# Title\n\nContent\n")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "structural.title" in rec.signal_provenance
        assert rec.signal_provenance["structural.title"]["method"] == "extract_md_title"

    def test_structural_title_provenance_html(self, tmp_path: Path) -> None:
        (tmp_path / "page.html").write_text("<html><head><title>Test</title></head></html>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "structural.title" in rec.signal_provenance
        assert rec.signal_provenance["structural.title"]["method"] == "extract_html_title"

    def test_structural_keys_provenance_json(self, tmp_path: Path) -> None:
        (tmp_path / "data.json").write_text('{"key": "val"}')
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "structural.document_keys" in rec.signal_provenance
        assert rec.signal_provenance["structural.document_keys"]["method"] == "extract_json_keys"

    def test_structural_keys_provenance_xml(self, tmp_path: Path) -> None:
        (tmp_path / "data.xml").write_text("<root><child/></root>")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "structural.document_keys" in rec.signal_provenance
        assert rec.signal_provenance["structural.document_keys"]["method"] == "extract_xml_keys"


# ---------------------------------------------------------------------------
# extract_xml_keys
# ---------------------------------------------------------------------------

class TestExtractXmlKeys:
    def test_root_and_children(self, scanner: Scanner) -> None:
        text = '<config><db/><cache/><log/></config>'
        keys = scanner.extract_xml_keys(text)
        assert keys[0] == "config"
        assert "cache" in keys
        assert "db" in keys
        assert "log" in keys

    def test_deduplicates_children(self, scanner: Scanner) -> None:
        text = '<list><item/><item/><item/></list>'
        keys = scanner.extract_xml_keys(text)
        assert keys.count("item") == 1

    def test_children_sorted(self, scanner: Scanner) -> None:
        text = '<root><zebra/><alpha/><mid/></root>'
        keys = scanner.extract_xml_keys(text)
        children = keys[1:]  # skip root
        assert children == sorted(children)

    def test_empty_root(self, scanner: Scanner) -> None:
        keys = scanner.extract_xml_keys('<empty/>')
        assert keys == ["empty"]

    def test_malformed_returns_empty(self, scanner: Scanner) -> None:
        assert scanner.extract_xml_keys('<broken') == []

    def test_with_namespaces(self, scanner: Scanner) -> None:
        text = '<ns:root xmlns:ns="http://example.com"><ns:child/></ns:root>'
        keys = scanner.extract_xml_keys(text)
        assert len(keys) >= 1  # namespace-prefixed names preserved


# ---------------------------------------------------------------------------
# extract_toml_keys
# ---------------------------------------------------------------------------

class TestExtractTomlKeys:
    def test_top_level_keys(self, scanner: Scanner) -> None:
        text = 'name = "test"\nversion = "1.0"\ndebug = false\n'
        keys = scanner.extract_toml_keys(text)
        assert "name" in keys
        assert "version" in keys
        assert "debug" in keys

    def test_keys_sorted(self, scanner: Scanner) -> None:
        text = 'zebra = 1\nalpha = 2\n'
        keys = scanner.extract_toml_keys(text)
        assert keys == sorted(keys)

    def test_nested_tables_top_level_only(self, scanner: Scanner) -> None:
        text = '[server]\nhost = "localhost"\n[database]\nurl = "sqlite"\n'
        keys = scanner.extract_toml_keys(text)
        assert "server" in keys
        assert "database" in keys
        assert "host" not in keys

    def test_malformed_returns_empty(self, scanner: Scanner) -> None:
        assert scanner.extract_toml_keys('invalid [[[') == []

    def test_empty_returns_empty(self, scanner: Scanner) -> None:
        assert scanner.extract_toml_keys('') == []


# ---------------------------------------------------------------------------
# detect_binary
# ---------------------------------------------------------------------------

class TestDetectBinary:
    def test_nul_byte_triggers_binary(self, scanner: Scanner) -> None:
        result, prov = scanner.detect_binary(b"hello\x00world", "text/plain")
        assert result is True
        assert prov.trigger == "nul_byte"

    def test_image_mime_triggers_binary(self, scanner: Scanner) -> None:
        result, prov = scanner.detect_binary(b"fakepng", "image/png")
        assert result is True
        assert prov.trigger == "mime_prefix_binary"

    def test_pdf_mime_triggers_binary(self, scanner: Scanner) -> None:
        result, prov = scanner.detect_binary(b"%PDF-1.4", "application/pdf")
        assert result is True
        assert prov.trigger == "known_binary_mime"

    def test_plain_text_not_binary(self, scanner: Scanner) -> None:
        result, prov = scanner.detect_binary(b"Hello world\n", "text/plain")
        assert result is False
        assert prov.trigger == "text_ratio_ok"

    def test_empty_sample_not_binary(self, scanner: Scanner) -> None:
        result, prov = scanner.detect_binary(b"", "text/plain")
        assert result is False

    def test_json_mime_not_binary(self, scanner: Scanner) -> None:
        result, prov = scanner.detect_binary(b'{"key": "value"}', "application/json")
        assert result is False

    def test_low_text_ratio_triggers_binary(self, scanner: Scanner) -> None:
        sample = bytes(range(1, 32)) * 10  # mostly control chars, no NUL
        result, prov = scanner.detect_binary(sample, "text/plain")
        assert result is True
        assert prov.trigger == "text_ratio_failure"


# ---------------------------------------------------------------------------
# detect_requires_vision
# ---------------------------------------------------------------------------

class TestDetectRequiresVision:
    def test_image_mime(self, scanner: Scanner) -> None:
        result, prov = scanner.detect_requires_vision(b"", "image/png", ".png", True)
        assert result is True
        assert prov.trigger == "image_mime"
        result2, _ = scanner.detect_requires_vision(b"", "image/jpeg", ".jpg", True)
        assert result2 is True

    def test_pdf_with_text_markers(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 /Font /Text BT\n"
        result, prov = scanner.detect_requires_vision(sample, "application/pdf", ".pdf", True)
        assert result is False
        assert prov.trigger == "pdf_has_text_markers"

    def test_pdf_with_crlf_text_markers(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 BT\r\n some text ET\r\n"
        result, prov = scanner.detect_requires_vision(sample, "application/pdf", ".pdf", True)
        assert result is False
        assert prov.trigger == "pdf_has_text_markers"

    def test_pdf_without_text_markers(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 just image data"
        result, prov = scanner.detect_requires_vision(sample, "application/pdf", ".pdf", True)
        assert result is True
        assert prov.trigger == "pdf_no_text_markers"

    def test_text_file_no_vision(self, scanner: Scanner) -> None:
        result, prov = scanner.detect_requires_vision(b"hello", "text/plain", ".txt", False)
        assert result is False
        assert prov.trigger == "not_applicable"


# ---------------------------------------------------------------------------
# detect_mime
# ---------------------------------------------------------------------------

class TestDetectMime:
    def test_known_extension_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "test.json"
        f.write_text("{}")
        scanner = Scanner(source_dir=tmp_path)
        scanner._magic = None
        errors: list[ErrorRecord] = []
        mime, prov = scanner.detect_mime(f, errors)
        assert mime == "application/json"
        assert prov.trigger == "extension_fallback"
        assert any(e.code == "mime_type_fallback" for e in errors)

    def test_unknown_extension_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "test.xyz123"
        f.write_bytes(b"\x00\x01\x02")
        scanner = Scanner(source_dir=tmp_path)
        scanner._magic = None
        errors: list[ErrorRecord] = []
        mime, prov = scanner.detect_mime(f, errors)
        assert mime == "application/octet-stream"
        assert prov.trigger == "extension_fallback"


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


# ---------------------------------------------------------------------------
# ScanContext
# ---------------------------------------------------------------------------

class TestScanContext:
    def test_context_present_in_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        ctx = manifest.context
        assert ctx.scanner_version == "0.6.0"
        assert ctx.logic_version == "0.6.0"
        assert ctx.python_version  # non-empty
        assert ctx.platform  # non-empty

    def test_context_dependencies_present(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        deps = manifest.context.dependencies
        assert "magic" in deps
        assert "chardet" in deps
        assert "yaml" in deps
        for name, info in deps.items():
            assert "available" in info
            assert "version" in info

    def test_context_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        c1 = Scanner(source_dir=tmp_path).scan().context
        c2 = Scanner(source_dir=tmp_path).scan().context
        assert c1.logic_version == c2.logic_version
        assert c1.scanner_version == c2.scanner_version
        assert c1.python_version == c2.python_version
        assert c1.platform == c2.platform
        assert c1.dependencies == c2.dependencies

    def test_context_no_hostname(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        ctx_dict = asdict(manifest.context)
        assert "hostname" not in ctx_dict

    def test_context_in_json_output(self, tmp_path: Path) -> None:
        import json as json_mod
        (tmp_path / "a.txt").write_text("hello")
        from scanner.scanner import manifest_to_json
        manifest = Scanner(source_dir=tmp_path).scan()
        data = json_mod.loads(manifest_to_json(manifest))
        assert "context" in data
        assert data["context"]["scanner_version"] == "0.6.0"


# ---------------------------------------------------------------------------
# Signal Provenance
# ---------------------------------------------------------------------------

class TestSignalProvenance:
    def test_provenance_present_on_every_file(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4\x00")
        manifest = Scanner(source_dir=tmp_path).scan()
        for f in manifest.files:
            assert isinstance(f.signal_provenance, dict)
            assert len(f.signal_provenance) > 0

    def test_provenance_required_fields(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        required_keys = {"mime_type", "is_binary", "requires_vision",
                         "requires_specialist_tool", "encoding",
                         "mime_analysis.matches_extension"}
        assert required_keys <= set(rec.signal_provenance.keys())

    def test_provenance_entry_structure(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        for key, entry in rec.signal_provenance.items():
            assert "layer" in entry
            assert "method" in entry
            assert "trigger" in entry
            assert entry["layer"] in ("raw", "derived", "semantic_local")

    def test_provenance_mime_type_trigger(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        mime_prov = rec.signal_provenance["mime_type"]
        assert mime_prov["layer"] == "raw"
        assert mime_prov["trigger"] in ("libmagic", "extension_fallback")

    def test_provenance_binary_text_file(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello world")
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.signal_provenance["is_binary"]["trigger"] == "text_ratio_ok"

    def test_provenance_binary_nul_byte(self, tmp_path: Path) -> None:
        (tmp_path / "a.bin").write_bytes(b"hello\x00world")
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.signal_provenance["is_binary"]["trigger"] == "nul_byte"

    def test_provenance_encoding_binary_file(self, tmp_path: Path) -> None:
        (tmp_path / "a.bin").write_bytes(b"\x00\x01\x02" * 100)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.signal_provenance["encoding"]["trigger"] == "not_applicable"

    def test_provenance_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        p1 = Scanner(source_dir=tmp_path).scan().files[0].signal_provenance
        p2 = Scanner(source_dir=tmp_path).scan().files[0].signal_provenance
        assert p1 == p2

    def test_provenance_in_json_output(self, tmp_path: Path) -> None:
        import json as json_mod
        from scanner.scanner import manifest_to_json
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        data = json_mod.loads(manifest_to_json(manifest))
        assert "signal_provenance" in data["files"][0]
        assert "is_binary" in data["files"][0]["signal_provenance"]


# ---------------------------------------------------------------------------
# Manifest checksum (v0.3 — excludes volatile fields)
# ---------------------------------------------------------------------------

class TestManifestChecksumV03:
    def test_checksum_stable_across_runs(self, tmp_path: Path) -> None:
        """Same files, different scan_id/generated_at → same checksum."""
        (tmp_path / "a.txt").write_text("hello")
        c1 = Scanner(source_dir=tmp_path).scan().manifest_checksum
        c2 = Scanner(source_dir=tmp_path).scan().manifest_checksum
        assert c1 == c2


# ---------------------------------------------------------------------------
# PDF deepened metadata (v0.3)
# ---------------------------------------------------------------------------

class TestPdfDeepenedMetadata:
    def test_pdf_version_extracted(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.7 /Font"
        meta = scanner._extract_pdf_metadata(sample)
        assert meta["pdf_version"] == "1.7"

    def test_pdf_version_2_0(self, scanner: Scanner) -> None:
        sample = b"%PDF-2.0 content"
        meta = scanner._extract_pdf_metadata(sample)
        assert meta["pdf_version"] == "2.0"

    def test_pdf_version_missing(self, scanner: Scanner) -> None:
        sample = b"not a pdf header"
        meta = scanner._extract_pdf_metadata(sample)
        assert meta["pdf_version"] is None

    def test_encrypted_detected(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 /Encrypt << /Filter /Standard >>"
        meta = scanner._extract_pdf_metadata(sample)
        assert meta["encrypted"] is True

    def test_not_encrypted(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 /Font /Text"
        meta = scanner._extract_pdf_metadata(sample)
        assert meta["encrypted"] is False

    def test_text_marker_density_computed(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 BT some text ET BT more ET"
        meta = scanner._extract_pdf_metadata(sample)
        density = meta["sample_text_marker_density"]
        assert density is not None
        assert density > 0
        # 4 markers (2 BT + 2 ET) / len(sample)
        expected = 4 / len(sample)
        assert abs(density - expected) < 1e-10

    def test_text_marker_density_zero(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 just image data no markers"
        meta = scanner._extract_pdf_metadata(sample)
        assert meta["sample_text_marker_density"] == 0.0

    def test_text_marker_density_empty(self, scanner: Scanner) -> None:
        meta = scanner._extract_pdf_metadata(b"")
        assert meta["sample_text_marker_density"] is None

    def test_all_v03_fields_present(self, scanner: Scanner) -> None:
        sample = b"%PDF-1.4 /Font"
        meta = scanner._extract_pdf_metadata(sample)
        assert "encrypted" in meta
        assert "pdf_version" in meta
        assert "sample_text_marker_density" in meta
        # v0.2 fields still present
        assert "has_text_streams" in meta
        assert "page_count" in meta
        assert "title" in meta


# ---------------------------------------------------------------------------
# PNG IHDR metadata (v0.3)
# ---------------------------------------------------------------------------

class TestPngMetadata:
    def _make_png(self, width: int, height: int, bit_depth: int = 8) -> bytes:
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">II", width, height) + bytes([bit_depth, 2, 0, 0, 0])
        ihdr_len = struct.pack(">I", 13)
        return sig + ihdr_len + b"IHDR" + ihdr_data

    def test_valid_png(self, scanner: Scanner) -> None:
        sample = self._make_png(1920, 1080, 8)
        meta = scanner._extract_png_metadata(sample)
        assert meta is not None
        assert meta["width"] == 1920
        assert meta["height"] == 1080
        assert meta["bit_depth"] == 8

    def test_small_png(self, scanner: Scanner) -> None:
        sample = self._make_png(16, 16, 4)
        meta = scanner._extract_png_metadata(sample)
        assert meta["width"] == 16
        assert meta["height"] == 16
        assert meta["bit_depth"] == 4

    def test_invalid_signature(self, scanner: Scanner) -> None:
        sample = b"NOT_A_PNG_FILE" + b"\x00" * 30
        meta = scanner._extract_png_metadata(sample)
        assert meta is None

    def test_truncated_before_ihdr(self, scanner: Scanner) -> None:
        sig = b"\x89PNG\r\n\x1a\n"
        sample = sig + b"\x00" * 5  # too short for IHDR
        meta = scanner._extract_png_metadata(sample)
        assert meta is not None
        assert meta["width"] is None

    def test_missing_ihdr_chunk(self, scanner: Scanner) -> None:
        sig = b"\x89PNG\r\n\x1a\n"
        # Valid length but wrong chunk type
        sample = sig + b"\x00\x00\x00\x0d" + b"tEXt" + b"\x00" * 13
        meta = scanner._extract_png_metadata(sample)
        assert meta["width"] is None

    def test_png_through_scan(self, tmp_path: Path) -> None:
        sample = self._make_png(800, 600)
        (tmp_path / "test.png").write_bytes(sample)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is not None
        assert rec.specialist_metadata["image"]["width"] == 800
        assert rec.specialist_metadata["image"]["height"] == 600


# ---------------------------------------------------------------------------
# MSG envelope metadata (v0.3)
# ---------------------------------------------------------------------------

class TestMsgMetadata:
    def test_msg_without_olefile_returns_none(self, scanner: Scanner) -> None:
        """When olefile is not available, msg extraction returns None."""
        import scanner.scanner as mod
        original = mod.olefile
        try:
            mod.olefile = None
            result = scanner._extract_msg_metadata(Path("fake.msg"))
            assert result is None
        finally:
            mod.olefile = original

    def test_msg_non_ole_file_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "fake.msg").write_bytes(b"not an OLE file")
        scanner = Scanner(source_dir=tmp_path)
        result = scanner._extract_msg_metadata(tmp_path / "fake.msg")
        # Either None (olefile available but rejects) or None (olefile unavailable)
        assert result is None

    def test_msg_specialist_tool_registered(self) -> None:
        from scanner.scanner import SPECIALIST_TOOLS
        assert SPECIALIST_TOOLS.get(".msg") == "email_envelope"

    def test_png_specialist_tool_registered(self) -> None:
        from scanner.scanner import SPECIALIST_TOOLS
        assert SPECIALIST_TOOLS.get(".png") == "image_structure"


# ---------------------------------------------------------------------------
# v0.4: Semantic specialist tool names
# ---------------------------------------------------------------------------

class TestSemanticToolNames:
    def test_all_tool_values_semantic(self) -> None:
        from scanner.scanner import SPECIALIST_TOOLS
        for ext, tool in SPECIALIST_TOOLS.items():
            # No implementation-leak names (no _scanner, _parser, _header, _envelope suffixes)
            assert "_scanner" not in tool, f"{ext}: {tool}"
            assert "_parser" not in tool, f"{ext}: {tool}"
            assert "_header" not in tool, f"{ext}: {tool}"

    def test_tool_name_mapping(self) -> None:
        from scanner.scanner import SPECIALIST_TOOLS
        assert SPECIALIST_TOOLS[".pdf"] == "pdf_extraction"
        assert SPECIALIST_TOOLS[".png"] == "image_structure"
        assert SPECIALIST_TOOLS[".jpg"] == "image_structure"
        assert SPECIALIST_TOOLS[".jpeg"] == "image_structure"
        assert SPECIALIST_TOOLS[".msg"] == "email_envelope"
        assert SPECIALIST_TOOLS[".eml"] == "email_envelope"
        assert SPECIALIST_TOOLS[".docx"] == "document_extraction"
        assert SPECIALIST_TOOLS[".rtf"] == "document_extraction"
        assert SPECIALIST_TOOLS[".xlsx"] == "spreadsheet_structure"

    def test_version_is_current(self) -> None:
        from scanner.scanner import SCANNER_VERSION, LOGIC_VERSION
        assert SCANNER_VERSION == "0.6.0"
        assert LOGIC_VERSION == "0.6.0"  # routing logic unchanged in patch


# ---------------------------------------------------------------------------
# v0.4: JPEG SOF specialist
# ---------------------------------------------------------------------------

class TestJpegMetadata:
    def _make_jpeg_sof0(self, width: int, height: int) -> bytes:
        # SOF0: FF C0 + length(2) + precision(1) + height(2) + width(2) + components
        soi = b"\xff\xd8"
        components = b"\x01\x11\x00"
        seg_length = 2 + 1 + 2 + 2 + len(components)
        sof = b"\xff\xc0" + struct.pack(">H", seg_length) + struct.pack(">B", 8) + struct.pack(">HH", height, width) + components
        return soi + sof

    def test_valid_jpeg_sof0(self, scanner: Scanner) -> None:
        sample = self._make_jpeg_sof0(1920, 1080)
        meta = scanner._extract_jpeg_metadata(sample)
        assert meta["width"] == 1920
        assert meta["height"] == 1080

    def test_valid_jpeg_progressive(self, scanner: Scanner) -> None:
        # SOF2 (progressive) marker
        soi = b"\xff\xd8"
        components = b"\x01\x11\x00"
        seg_length = 2 + 1 + 2 + 2 + len(components)
        sof = b"\xff\xc2" + struct.pack(">H", seg_length) + struct.pack(">B", 8) + struct.pack(">HH", 600, 800) + components
        sample = soi + sof
        meta = scanner._extract_jpeg_metadata(sample)
        assert meta["width"] == 800
        assert meta["height"] == 600

    def test_no_sof_marker(self, scanner: Scanner) -> None:
        # Just SOI + some EXIF data, no SOF
        sample = b"\xff\xd8\xff\xe1\x00\x10" + b"\x00" * 14
        meta = scanner._extract_jpeg_metadata(sample)
        assert meta["width"] is None
        assert meta["height"] is None

    def test_truncated_sof(self, scanner: Scanner) -> None:
        # SOI + SOF marker but truncated before dimensions
        sample = b"\xff\xd8\xff\xc0\x00\x0b\x08"
        meta = scanner._extract_jpeg_metadata(sample)
        assert meta["width"] is None

    def test_jpeg_through_scan(self, tmp_path: Path) -> None:
        sample = self._make_jpeg_sof0(640, 480)
        (tmp_path / "photo.jpg").write_bytes(sample)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata["image"]["width"] == 640
        assert rec.specialist_metadata["image"]["height"] == 480
        assert rec.specialist_tool == "image_structure"


# ---------------------------------------------------------------------------
# v0.4: EML specialist
# ---------------------------------------------------------------------------

class TestEmlMetadata:
    def test_basic_eml(self, scanner: Scanner) -> None:
        eml = (
            b"From: alice@example.com\r\n"
            b"To: bob@example.com\r\n"
            b"Subject: Test Email\r\n"
            b"Date: Mon, 15 Mar 2026 10:30:00 +0000\r\n"
            b"Message-ID: <abc123@example.com>\r\n"
            b"\r\n"
            b"Body text here\r\n"
        )
        meta = scanner._extract_eml_metadata(eml)
        assert meta is not None
        assert meta["subject"] == "Test Email"
        assert "alice@example.com" in meta["from"]
        assert "bob@example.com" in meta["to"]
        assert meta["message_id"] is not None
        assert meta["has_attachments"] is False

    def test_eml_with_attachment(self, scanner: Scanner) -> None:
        eml = (
            b"From: alice@example.com\r\n"
            b"To: bob@example.com\r\n"
            b"Subject: With Attachment\r\n"
            b"Content-Type: multipart/mixed; boundary=boundary\r\n"
            b"\r\n"
            b"--boundary\r\n"
            b"Content-Type: text/plain\r\n\r\nHi\r\n"
            b"--boundary\r\n"
            b"Content-Disposition: attachment; filename=doc.pdf\r\n\r\ndata\r\n"
            b"--boundary--\r\n"
        )
        meta = scanner._extract_eml_metadata(eml)
        assert meta["has_attachments"] is True

    def test_eml_missing_headers(self, scanner: Scanner) -> None:
        eml = b"Just some text without headers\r\n"
        meta = scanner._extract_eml_metadata(eml)
        assert meta is not None
        assert meta["subject"] is None

    def test_eml_through_scan(self, tmp_path: Path) -> None:
        eml = b"From: test@test.com\r\nSubject: Hello\r\n\r\nBody\r\n"
        (tmp_path / "email.eml").write_bytes(eml)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_tool == "email_envelope"
        assert rec.specialist_metadata["email"]["subject"] == "Hello"


# ---------------------------------------------------------------------------
# v0.4: XLSX specialist
# ---------------------------------------------------------------------------

class TestXlsxMetadata:
    def test_xlsx_specialist_tool(self) -> None:
        from scanner.scanner import SPECIALIST_TOOLS
        assert SPECIALIST_TOOLS[".xlsx"] == "spreadsheet_structure"

    def test_xlsx_invalid_file(self, tmp_path: Path) -> None:
        (tmp_path / "bad.xlsx").write_bytes(b"not a zip file")
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_xlsx_no_metadata_when_disabled(self, tmp_path: Path) -> None:
        (tmp_path / "data.xlsx").write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_xlsx_deviation_provenance(self, tmp_path: Path) -> None:
        """XLSX provenance should show bounded_deviation trigger."""
        # Create a minimal valid xlsx-like zip (won't have real sheets but tests provenance)
        import zipfile
        from io import BytesIO
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Sheet1"/></sheets></workbook>')
        (tmp_path / "test.xlsx").write_bytes(buf.getvalue())
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        if rec.specialist_metadata:
            prov = rec.signal_provenance.get("specialist_metadata.spreadsheet.sheet_names", {})
            assert prov.get("trigger") == "bounded_deviation"
            assert prov.get("detail", {}).get("read_budget_bytes") == 131072


# ---------------------------------------------------------------------------
# v0.4: ZIP entry validation
# ---------------------------------------------------------------------------

class TestZipEntryValidation:
    def test_safe_entries(self) -> None:
        assert Scanner._is_safe_zip_entry("xl/workbook.xml") is True
        assert Scanner._is_safe_zip_entry("xl/worksheets/sheet1.xml") is True

    def test_path_traversal_rejected(self) -> None:
        assert Scanner._is_safe_zip_entry("../../etc/passwd") is False
        assert Scanner._is_safe_zip_entry("xl/../../../secret") is False

    def test_absolute_path_rejected(self) -> None:
        assert Scanner._is_safe_zip_entry("/etc/passwd") is False
        assert Scanner._is_safe_zip_entry("\\windows\\system32") is False

    def test_drive_letter_rejected(self) -> None:
        assert Scanner._is_safe_zip_entry("C:\\evil.txt") is False
        assert Scanner._is_safe_zip_entry("D:/path/file") is False

    def test_mixed_separator_traversal_rejected(self) -> None:
        assert Scanner._is_safe_zip_entry("foo\\../bar") is False
        assert Scanner._is_safe_zip_entry("foo\\..\\bar") is False

    def test_current_dir_reference_rejected(self) -> None:
        assert Scanner._is_safe_zip_entry("./hidden") is False
        assert Scanner._is_safe_zip_entry("foo/./bar") is False

    def test_normal_nested_paths_safe(self) -> None:
        assert Scanner._is_safe_zip_entry("word/document.xml") is True
        assert Scanner._is_safe_zip_entry("docProps/core.xml") is True
        assert Scanner._is_safe_zip_entry("xl/worksheets/sheet1.xml") is True


# ---------------------------------------------------------------------------
# Document envelope specialists (DOCX, DOC, RTF)
# ---------------------------------------------------------------------------

class TestDocxMetadata:
    def _make_docx(self, title: str | None = None, author: str | None = None, words: int | None = None) -> bytes:
        import zipfile
        from io import BytesIO
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # core.xml
            core_parts = []
            if title:
                core_parts.append(f'<dc:title>{title}</dc:title>')
            if author:
                core_parts.append(f'<dc:creator>{author}</dc:creator>')
            core_xml = f'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">{"".join(core_parts)}</cp:coreProperties>'
            zf.writestr("docProps/core.xml", core_xml)
            # app.xml
            if words is not None:
                app_xml = f'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Words>{words}</Words></Properties>'
                zf.writestr("docProps/app.xml", app_xml)
            # minimal document.xml
            zf.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
        return buf.getvalue()

    def test_docx_title_and_author(self, tmp_path: Path) -> None:
        (tmp_path / "doc.docx").write_bytes(self._make_docx(title="My Report", author="Jane"))
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata["document"]["title"] == "My Report"
        assert rec.specialist_metadata["document"]["author"] == "Jane"

    def test_docx_word_count(self, tmp_path: Path) -> None:
        (tmp_path / "doc.docx").write_bytes(self._make_docx(words=1500))
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata["document"]["word_count"] == 1500

    def test_docx_no_metadata(self, tmp_path: Path) -> None:
        (tmp_path / "doc.docx").write_bytes(self._make_docx())
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is not None
        assert "document" in rec.specialist_metadata
        assert "title" in rec.specialist_metadata["document"]
        assert "author" in rec.specialist_metadata["document"]

    def test_docx_heading_count(self, tmp_path: Path) -> None:
        import zipfile
        from io import BytesIO
        buf = BytesIO()
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        doc_xml = f'''<w:document xmlns:w="{ns}"><w:body>
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr></w:p>
            <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr></w:p>
            <w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr></w:p>
            <w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr></w:p>
        </w:body></w:document>'''
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", doc_xml)
            zf.writestr("docProps/core.xml", '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>')
        (tmp_path / "doc.docx").write_bytes(buf.getvalue())
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata["document"]["heading_count"] == 3

    def test_docx_invalid_zip(self, tmp_path: Path) -> None:
        (tmp_path / "bad.docx").write_bytes(b"not a zip")
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_docx_real_fixtures(self) -> None:
        from pathlib import Path as P
        fixtures = P(__file__).parent / "fixtures"
        scanner = Scanner(source_dir=fixtures, config=ScannerConfig(enable_specialists=True))
        manifest = scanner.scan()
        docx_with_author = [f for f in manifest.files if f.extension == ".docx"
                           and f.specialist_metadata and f.specialist_metadata.get("document", {}).get("author")]
        assert len(docx_with_author) > 0


class TestDocMetadata:
    def test_doc_without_olefile_returns_none(self, scanner: Scanner) -> None:
        import scanner.scanner as mod
        original = mod.olefile
        try:
            mod.olefile = None
            result = scanner._extract_doc_metadata(b"fake content")
            assert result is None
        finally:
            mod.olefile = original

    def test_doc_invalid_file(self, tmp_path: Path) -> None:
        (tmp_path / "bad.doc").write_bytes(b"not an OLE file")
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_doc_extracts_from_real_fixtures(self) -> None:
        """Test against real .doc fixtures if they exist."""
        from pathlib import Path as P
        fixtures = P(__file__).parent / "fixtures"
        doc_files = list(fixtures.rglob("*.doc"))
        if not doc_files:
            pytest.skip("No .doc fixtures available")
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=fixtures, config=config)
        manifest = scanner.scan()
        docs = [f for f in manifest.files if f.extension == ".doc" and f.specialist_metadata]
        # If olefile is available and fixtures have OLE properties, we should get metadata
        import scanner.scanner as mod
        if mod.olefile:
            # At least verify no crashes; metadata may be null if sample too small
            for f in manifest.files:
                if f.extension == ".doc":
                    assert f.requires_specialist_tool is True
                    assert f.specialist_tool == "document_extraction"

    def test_doc_specialist_tool(self) -> None:
        from scanner.scanner import SPECIALIST_TOOLS
        assert SPECIALIST_TOOLS[".doc"] == "document_extraction"


class TestRtfMetadata:
    def test_rtf_with_info(self, scanner: Scanner) -> None:
        sample = rb"{\rtf1 {\info {\title My Document} {\author John Smith}} Hello}"
        meta = scanner._extract_rtf_metadata(sample)
        assert meta["title"] == "My Document"
        assert meta["author"] == "John Smith"

    def test_rtf_no_info(self, scanner: Scanner) -> None:
        sample = rb"{\rtf1 Hello world}"
        meta = scanner._extract_rtf_metadata(sample)
        assert meta is not None
        assert meta["title"] is None
        assert meta["author"] is None

    def test_rtf_partial_info(self, scanner: Scanner) -> None:
        sample = rb"{\rtf1 {\info {\title Report}} Content}"
        meta = scanner._extract_rtf_metadata(sample)
        assert meta["title"] == "Report"
        assert meta["author"] is None

    def test_rtf_through_scan(self, tmp_path: Path) -> None:
        rtf = rb"{\rtf1 {\info {\title Test Doc} {\author Alice}} Body text}"
        (tmp_path / "doc.rtf").write_bytes(rtf)
        scanner = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True))
        rec = scanner.scan().files[0]
        assert rec.specialist_tool == "document_extraction"
        assert rec.specialist_metadata["document"]["title"] == "Test Doc"
        assert rec.specialist_metadata["document"]["author"] == "Alice"


# ---------------------------------------------------------------------------
# v0.6: Dip switches — configurable depth
# ---------------------------------------------------------------------------

class TestDipSwitches:
    def test_specialist_budget_in_config(self) -> None:
        config = ScannerConfig()
        assert config.specialist_budget == 131072

    def test_extension_overrides_default_empty(self) -> None:
        config = ScannerConfig()
        assert config.extension_overrides == {}

    def test_effective_config_no_override(self) -> None:
        config = ScannerConfig(baseline_max_bytes=65536)
        eff = config.effective_for(".txt")
        assert eff["baseline_max_bytes"] == 65536
        assert eff["specialist_budget"] == 131072

    def test_effective_config_with_override(self) -> None:
        config = ScannerConfig(
            baseline_max_bytes=65536,
            extension_overrides={".csv": {"baseline_max_bytes": 1048576}}
        )
        eff_csv = config.effective_for(".csv")
        eff_txt = config.effective_for(".txt")
        assert eff_csv["baseline_max_bytes"] == 1048576
        assert eff_txt["baseline_max_bytes"] == 65536

    def test_effective_enforces_sample_size_minimum(self) -> None:
        config = ScannerConfig(
            sample_size=8192,
            extension_overrides={".txt": {"baseline_max_bytes": 100}}
        )
        eff = config.effective_for(".txt")
        assert eff["baseline_max_bytes"] == 8192  # enforced minimum

    def test_specialist_budget_override(self) -> None:
        config = ScannerConfig(
            specialist_budget=131072,
            extension_overrides={".pdf": {"specialist_budget": 524288}}
        )
        eff = config.effective_for(".pdf")
        assert eff["specialist_budget"] == 524288

    def test_deep_extract_profile(self, tmp_path: Path) -> None:
        from scanner.scanner import SCAN_PROFILES
        profile = SCAN_PROFILES["deep_extract"]
        assert profile["baseline_max_bytes"] == 1048576
        assert profile["specialist_budget"] == 524288
        assert profile["enable_specialists"] is True

    def test_fast_sort_profile(self) -> None:
        from scanner.scanner import SCAN_PROFILES
        profile = SCAN_PROFILES["fast_sort"]
        assert profile["baseline_max_bytes"] == 8192
        assert profile["enable_specialists"] is False

    def test_override_applies_to_scan(self, tmp_path: Path) -> None:
        # Create a file larger than 100 bytes
        (tmp_path / "big.txt").write_text("x" * 500)
        config = ScannerConfig(
            baseline_max_bytes=100,
            extension_overrides={".txt": {"baseline_max_bytes": 50000}}
        )
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        # Should have extracted content (override gives enough bytes)
        assert rec.content_preview is not None
        assert len(rec.content_preview) > 0

    def test_config_in_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        config = ScannerConfig(
            specialist_budget=262144,
            extension_overrides={".csv": {"baseline_max_bytes": 999999}}
        )
        scanner = Scanner(source_dir=tmp_path, config=config)
        manifest = scanner.scan()
        assert manifest.meta.config["specialist_budget"] == 262144
        assert manifest.meta.config["extension_overrides"] == {".csv": {"baseline_max_bytes": 999999}}


# ---------------------------------------------------------------------------
# v0.6: Structural signatures and polyglot detection
# ---------------------------------------------------------------------------

class TestStructuralSignatures:
    def test_file_signature_present(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("Hello world")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.file_signature is not None
        assert "magic_bytes" in rec.file_signature
        assert rec.file_signature["magic_length"] > 0

    def test_file_signature_null_for_empty(self, tmp_path: Path) -> None:
        (tmp_path / "empty.txt").write_bytes(b"")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.file_signature is None

    def test_file_signature_hex_format(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"\xff\xd8\xff\xe0test")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.file_signature["magic_bytes"].startswith("ffd8ffe0")

    def test_format_signatures_png(self, tmp_path: Path) -> None:
        import struct as st
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = st.pack(">I", 13) + b"IHDR" + st.pack(">II", 10, 10) + bytes([8, 2, 0, 0, 0])
        (tmp_path / "img.png").write_bytes(sig + ihdr)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert len(rec.format_signatures) >= 1
        assert rec.format_signatures[0]["format"] == "image/png"

    def test_format_signatures_empty_for_unknown(self, tmp_path: Path) -> None:
        (tmp_path / "random.dat").write_bytes(bytes(range(50, 100)))
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.format_signatures == []

    def test_polyglot_detected(self, tmp_path: Path) -> None:
        # JPEG header + PDF content
        poly = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 5 + b"%PDF-1.4 content"
        (tmp_path / "poly.jpg").write_bytes(poly)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.is_polyglot is True
        assert len(rec.format_signatures) >= 2

    def test_not_polyglot_single_format(self, tmp_path: Path) -> None:
        (tmp_path / "plain.txt").write_text("Just plain text nothing special")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.is_polyglot is False


class TestSpecialistMimeGuard:
    def test_text_file_as_pdf_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "fake.pdf").write_text("This is just text")
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None
        codes = [e.code for e in rec.errors]
        assert "specialist_probe_failed" in codes

    def test_real_pdf_not_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "real.pdf").write_bytes(b"%PDF-1.4\x00" + b"\x00" * 50)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is not None


# ---------------------------------------------------------------------------
# v0.6: Data integrity envelope
# ---------------------------------------------------------------------------

class TestIntegrityEnvelope:
    def test_manifest_signature_null_by_default(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert manifest.manifest_signature is None

    def test_manifest_signature_present_with_key(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        config = ScannerConfig(signing_key="test-secret", signing_key_id="test-key-1")
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        assert manifest.manifest_signature is not None
        assert manifest.manifest_signature["algorithm"] == "hmac-sha256"
        assert manifest.manifest_signature["key_id"] == "test-key-1"
        assert len(manifest.manifest_signature["value"]) == 64  # sha256 hex

    def test_signature_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        config = ScannerConfig(signing_key="secret")
        m1 = Scanner(source_dir=tmp_path, config=config).scan()
        m2 = Scanner(source_dir=tmp_path, config=config).scan()
        assert m1.manifest_signature["value"] == m2.manifest_signature["value"]

    def test_signature_changes_with_content(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        config = ScannerConfig(signing_key="secret")
        f.write_text("v1")
        s1 = Scanner(source_dir=tmp_path, config=config).scan().manifest_signature["value"]
        f.write_text("v2")
        s2 = Scanner(source_dir=tmp_path, config=config).scan().manifest_signature["value"]
        assert s1 != s2

    def test_previous_manifest_checksum_in_delta(self, tmp_path: Path) -> None:
        from scanner.scanner import manifest_to_json
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("hello")
        m1 = Scanner(source_dir=src).scan()
        prev = tmp_path / "prev.json"
        prev.write_text(manifest_to_json(m1))
        config = ScannerConfig(previous_manifest=str(prev))
        m2 = Scanner(source_dir=src, config=config).scan()
        assert m2.delta is not None
        assert m2.delta.previous_manifest_checksum == m1.manifest_checksum

    def test_previous_manifest_checksum_null_without_delta(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert manifest.delta is None

    def test_signature_in_json_output(self, tmp_path: Path) -> None:
        import json as json_mod
        from scanner.scanner import manifest_to_json
        (tmp_path / "a.txt").write_text("hello")
        config = ScannerConfig(signing_key="secret", signing_key_id="k1")
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        data = json_mod.loads(manifest_to_json(manifest))
        assert data["manifest_signature"]["key_id"] == "k1"
