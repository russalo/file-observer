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

    def test_utf16_le_bom_not_binary(self, scanner: Scanner) -> None:
        # UTF-16 LE encoding of "[List 1]\nfoo=bar" — interleaved NULs by design.
        sample = "[List 1]\nfoo=bar".encode("utf-16-le")
        sample = b"\xff\xfe" + sample  # add BOM
        result, prov = scanner.detect_binary(sample, "text/plain")
        assert result is False
        assert prov.trigger == "unicode_bom"
        assert prov.detail == {"bom": "utf-16-le"}

    def test_utf16_be_bom_not_binary(self, scanner: Scanner) -> None:
        sample = b"\xfe\xff" + "Hello".encode("utf-16-be")
        result, prov = scanner.detect_binary(sample, "text/plain")
        assert result is False
        assert prov.trigger == "unicode_bom"
        assert prov.detail == {"bom": "utf-16-be"}

    def test_utf32_le_bom_not_binary(self, scanner: Scanner) -> None:
        sample = b"\xff\xfe\x00\x00" + "Hello".encode("utf-32-le")
        result, prov = scanner.detect_binary(sample, "text/plain")
        assert result is False
        assert prov.trigger == "unicode_bom"
        assert prov.detail == {"bom": "utf-32-le"}

    def test_utf32_be_bom_not_binary(self, scanner: Scanner) -> None:
        sample = b"\x00\x00\xfe\xff" + "Hello".encode("utf-32-be")
        result, prov = scanner.detect_binary(sample, "text/plain")
        assert result is False
        assert prov.trigger == "unicode_bom"
        assert prov.detail == {"bom": "utf-32-be"}

    def test_utf32_le_bom_takes_precedence_over_utf16_le(self, scanner: Scanner) -> None:
        # UTF-32 LE BOM ff fe 00 00 starts with the UTF-16 LE BOM ff fe.
        # The 4-byte BOM must be checked first or it would be misclassified.
        sample = b"\xff\xfe\x00\x00" + "X".encode("utf-32-le")
        result, prov = scanner.detect_binary(sample, "text/plain")
        assert result is False
        assert prov.detail == {"bom": "utf-32-le"}

    def test_bom_overrides_image_mime(self, scanner: Scanner) -> None:
        # A BOM-prefixed sample should be treated as text even if the MIME would
        # otherwise route to binary. This is intentional: the BOM is a stronger
        # signal than the MIME (which can be wrong on extension-fallback paths).
        sample = b"\xff\xfe" + "txt".encode("utf-16-le")
        result, prov = scanner.detect_binary(sample, "image/png")
        assert result is False
        assert prov.trigger == "unicode_bom"


# ---------------------------------------------------------------------------
# _detect_unicode_bom
# ---------------------------------------------------------------------------

class TestDetectUnicodeBom:
    def test_no_bom_returns_none(self) -> None:
        from scanner.scanner import _detect_unicode_bom
        assert _detect_unicode_bom(b"hello") is None
        assert _detect_unicode_bom(b"") is None

    def test_utf8_bom_not_unicode_bom(self) -> None:
        # UTF-8 BOM (ef bb bf) is intentionally NOT in the table — UTF-8 has no
        # NUL-byte problem, so it never trips detect_binary the wrong way.
        from scanner.scanner import _detect_unicode_bom
        assert _detect_unicode_bom(b"\xef\xbb\xbfhello") is None

    def test_each_unicode_bom(self) -> None:
        from scanner.scanner import _detect_unicode_bom
        assert _detect_unicode_bom(b"\xff\xfe") == "utf-16-le"
        assert _detect_unicode_bom(b"\xfe\xff") == "utf-16-be"
        assert _detect_unicode_bom(b"\xff\xfe\x00\x00") == "utf-32-le"
        assert _detect_unicode_bom(b"\x00\x00\xfe\xff") == "utf-32-be"


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
        assert ctx.scanner_version == "0.9.2"
        assert ctx.logic_version == "0.9.0"
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
        assert data["context"]["scanner_version"] == "0.9.2"


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

    def test_provenance_utf16_le_text_file(self, tmp_path: Path) -> None:
        # Mimic a NASSCO LACP .lst export: UTF-16 LE with BOM and INI-style content.
        # Pre-patch this would have been misclassified as binary because of the
        # interleaved NULs in UTF-16 ASCII content.
        content = "[List 1]\r\nKey=Value\r\nKey2=Value2\r\n"
        (tmp_path / "report.txt").write_bytes(b"\xff\xfe" + content.encode("utf-16-le"))
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.is_binary is False
        assert rec.signal_provenance["is_binary"]["trigger"] == "unicode_bom"
        assert rec.signal_provenance["is_binary"]["detail"]["bom"] == "utf-16-le"

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
        # Also a regression guard for the v0.7.1 OLE2 sample-vs-path fix:
        # the extractor must take a Path and reject non-OLE files cleanly.
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
# v0.7.2: MSG date and from-name fixes
# ---------------------------------------------------------------------------

class TestMsgFiletimeConversion:
    """The static FILETIME → ISO 8601 helper, exercised without any .msg file."""

    def test_zero_returns_none(self, scanner: Scanner) -> None:
        assert scanner._filetime_to_iso(0) is None

    def test_negative_returns_none(self, scanner: Scanner) -> None:
        assert scanner._filetime_to_iso(-1) is None

    def test_known_value_2024(self, scanner: Scanner) -> None:
        # 2024-01-15 12:34:56 UTC as a Windows FILETIME.
        # FILETIME = (datetime(2024,1,15,12,34,56,tzinfo=utc) - datetime(1601,1,1,tzinfo=utc)).total_seconds() * 10_000_000
        from datetime import datetime, timezone
        target = datetime(2024, 1, 15, 12, 34, 56, tzinfo=timezone.utc)
        epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        ft = int((target - epoch).total_seconds() * 10_000_000)
        result = scanner._filetime_to_iso(ft)
        assert result is not None
        assert result.startswith("2024-01-15T12:34:56")

    def test_known_value_1990(self, scanner: Scanner) -> None:
        from datetime import datetime, timezone
        target = datetime(1990, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        ft = int((target - epoch).total_seconds() * 10_000_000)
        result = scanner._filetime_to_iso(ft)
        assert result is not None
        assert result.startswith("1990-06-01")

    def test_overflow_returns_none(self, scanner: Scanner) -> None:
        # Astronomically large value should not raise.
        result = scanner._filetime_to_iso(2 ** 63 - 1)
        # Either returns None or a valid ISO string in the far future, but
        # MUST NOT raise.
        assert result is None or isinstance(result, str)


class TestMsgFiletimePropertyReader:
    """Synthetic __properties_version1.0 stream parsing without a real .msg."""

    def test_missing_stream_returns_none(self, scanner: Scanner) -> None:
        # Stub OLE object with no streams.
        class StubOle:
            def exists(self, name: str) -> bool:
                return False
        assert scanner._msg_read_filetime_property(StubOle(), 0x0039) is None

    def test_empty_stream_returns_none(self, scanner: Scanner) -> None:
        from io import BytesIO
        class StubOle:
            def exists(self, name: str) -> bool:
                return name == "__properties_version1.0"
            def openstream(self, name: str):
                return BytesIO(b"")
        assert scanner._msg_read_filetime_property(StubOle(), 0x0039) is None

    def test_header_only_returns_none(self, scanner: Scanner) -> None:
        # 32-byte header with no entries → no matching property.
        from io import BytesIO
        class StubOle:
            def exists(self, name: str) -> bool:
                return name == "__properties_version1.0"
            def openstream(self, name: str):
                return BytesIO(b"\x00" * 32)
        assert scanner._msg_read_filetime_property(StubOle(), 0x0039) is None

    def test_synthetic_filetime_property_round_trip(self, scanner: Scanner) -> None:
        # Build a minimal __properties_version1.0 stream:
        #   32-byte top-level header
        #   one 16-byte entry: tag=0x00390040 (PR_CLIENT_SUBMIT_TIME), flags=0,
        #     value=FILETIME for 2023-07-04 18:30:00 UTC
        from datetime import datetime, timezone
        from io import BytesIO

        target = datetime(2023, 7, 4, 18, 30, 0, tzinfo=timezone.utc)
        epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        ft = int((target - epoch).total_seconds() * 10_000_000)

        header = b"\x00" * 32
        tag = (0x0039 << 16) | 0x0040  # = 0x00390040
        entry = tag.to_bytes(4, "little") + (0).to_bytes(4, "little") + ft.to_bytes(8, "little")
        stream_bytes = header + entry

        class StubOle:
            def __init__(self, data: bytes) -> None:
                self.data = data
            def exists(self, name: str) -> bool:
                return name == "__properties_version1.0"
            def openstream(self, name: str):
                return BytesIO(self.data)

        result = scanner._msg_read_filetime_property(StubOle(stream_bytes), 0x0039)
        assert result is not None
        assert result.startswith("2023-07-04T18:30:00")

    def test_synthetic_property_not_found_returns_none(self, scanner: Scanner) -> None:
        # Build a stream containing a property that's NOT the one we're looking for.
        from io import BytesIO
        header = b"\x00" * 32
        # Some unrelated tag, e.g. 0x00010040 (made-up)
        wrong_tag = (0x0001 << 16) | 0x0040
        entry = wrong_tag.to_bytes(4, "little") + (0).to_bytes(4, "little") + (0).to_bytes(8, "little")
        stream_bytes = header + entry

        class StubOle:
            def exists(self, name: str) -> bool:
                return name == "__properties_version1.0"
            def openstream(self, name: str):
                return BytesIO(stream_bytes)

        # Looking for 0x0039 should miss.
        assert scanner._msg_read_filetime_property(StubOle(), 0x0039) is None


class TestMsgFromFieldOrder:
    """Verify the from-name preference order: PR_SENDER_NAME (0x0C1A) first.

    These tests use a stub OLE that returns a specific string for each substg
    stream lookup. We're checking the *order* of fallbacks, not real .msg parsing.
    """

    def _make_scanner_with_stub(self, scanner: Scanner, present_streams: dict):
        """Patch _msg_read_property to consult the dict instead of olefile."""
        original = scanner._msg_read_property

        def fake_read_property(ole, stream_name):
            return present_streams.get(stream_name)

        scanner._msg_read_property = fake_read_property
        return original

    def test_sender_name_wins_when_present(self, scanner: Scanner, tmp_path: Path) -> None:
        # When PR_SENDER_NAME (0x0C1A) is set AND PR_SENDER_EMAIL_ADDRESS
        # (0x0C1F) is set, the display name should win.
        # We can't easily test this through _extract_msg_metadata without a
        # real .msg, so we verify the lookup order via the substg name strings
        # in the source code.
        import inspect
        src = inspect.getsource(scanner._extract_msg_metadata)
        # Confirm the from chain references 0x0C1A BEFORE 0x0C1F
        idx_0c1a = src.find("0C1A001F")
        idx_0c1f = src.find("0C1F001F")
        assert idx_0c1a != -1, "PR_SENDER_NAME (0x0C1A) lookup must be present"
        assert idx_0c1f != -1, "PR_SENDER_EMAIL_ADDRESS (0x0C1F) lookup must still be present as fallback"
        assert idx_0c1a < idx_0c1f, "PR_SENDER_NAME must be tried BEFORE PR_SENDER_EMAIL_ADDRESS"


# ---------------------------------------------------------------------------
# v0.8 Phase 1: chatlog content-based detection
# ---------------------------------------------------------------------------

class TestDetectChatlogPattern:
    """Unit tests for the _detect_chatlog_pattern detection rules.

    Per spec §2.3 (v0.9.1 tuned), ANY of three rules triggers detection:
      1. 3+ lines matching the speaker label pattern (excluding stop-list)
      2. 5+ occurrences of `### ` headers (raised from 3 in v0.9.1)
      3. 3+ section divider lines
    """

    # ---- Empty / negative ----

    def test_empty_string_is_not_chatlog(self, scanner: Scanner) -> None:
        assert scanner._detect_chatlog_pattern("") is False

    def test_plain_prose_is_not_chatlog(self, scanner: Scanner) -> None:
        text = (
            "This is a normal document. It has multiple sentences. None of "
            "them look like a chat log. There are no speaker labels, no "
            "Markdown headers, and no section dividers anywhere in this text."
        )
        assert scanner._detect_chatlog_pattern(text) is False

    # ---- Rule 1: speaker labels ----

    def test_three_speaker_labels_triggers(self, scanner: Scanner) -> None:
        text = "User: hi\nAssistant: hello\nUser: how are you\n"
        assert scanner._detect_chatlog_pattern(text) is True

    def test_two_speaker_labels_does_not_trigger(self, scanner: Scanner) -> None:
        # Below threshold — only 2 speaker label matches.
        text = "User: hi\nAssistant: hello\nThis is just prose continuing.\n"
        assert scanner._detect_chatlog_pattern(text) is False

    def test_speaker_label_too_long_does_not_match(self, scanner: Scanner) -> None:
        # Identifier > 16 chars before the colon should NOT count as a speaker
        # label (the regex caps at 16 chars to avoid sentence false positives).
        text = (
            "ThisIsAVeryLongIdentifierName: foo\n"
            "ThisIsAVeryLongIdentifierName: bar\n"
            "ThisIsAVeryLongIdentifierName: baz\n"
        )
        assert scanner._detect_chatlog_pattern(text) is False

    def test_speaker_label_lowercase_start_does_not_match(self, scanner: Scanner) -> None:
        # Speaker labels must start with an uppercase letter.
        text = "user: hi\nuser: hi\nuser: hi\n"
        assert scanner._detect_chatlog_pattern(text) is False

    def test_rpg_style_speaker_labels(self, scanner: Scanner) -> None:
        text = "DM: The dragon roars.\nPlayer_2: I attack!\nDM: Roll for it.\n"
        assert scanner._detect_chatlog_pattern(text) is True

    # ---- Rule 2: ### headers ----

    def test_five_h3_headers_triggers(self, scanner: Scanner) -> None:
        text = "### One\nbody\n### Two\nbody\n### Three\nbody\n### Four\nbody\n### Five\nbody\n"
        assert scanner._detect_chatlog_pattern(text) is True

    def test_four_h3_headers_does_not_trigger(self, scanner: Scanner) -> None:
        """v0.9.1: threshold raised from 3 to 5 — 4 headers no longer trigger."""
        text = "### One\nbody\n### Two\nbody\n### Three\nbody\n### Four\nbody\n"
        assert scanner._detect_chatlog_pattern(text) is False

    def test_three_h3_headers_does_not_trigger(self, scanner: Scanner) -> None:
        """v0.9.1: 3 H3 headers was the old threshold, now requires 5."""
        text = "### One\nbody\n### Two\nbody\n### Three\nbody\n"
        assert scanner._detect_chatlog_pattern(text) is False

    def test_two_h3_headers_does_not_trigger(self, scanner: Scanner) -> None:
        text = "### One\nbody\n### Two\nbody\nplain prose finishing the file.\n"
        assert scanner._detect_chatlog_pattern(text) is False

    # ---- Rule 3: section dividers ----

    def test_three_dash_dividers_triggers(self, scanner: Scanner) -> None:
        text = "section a\n---\nsection b\n---\nsection c\n---\nfooter\n"
        assert scanner._detect_chatlog_pattern(text) is True

    def test_three_equals_dividers_does_not_trigger_detection(self, scanner: Scanner) -> None:
        # Detection rule 3 per spec §2.3 is specifically "3+ `---` section
        # dividers" — other divider styles (===, ***, ###-as-pure-line) do
        # NOT participate in activation, though they ARE captured in the
        # extracted section_marker_styles list for files that activate via
        # some other rule.
        text = "section a\n===\nsection b\n===\nsection c\n===\n"
        assert scanner._detect_chatlog_pattern(text) is False

    def test_two_dividers_does_not_trigger(self, scanner: Scanner) -> None:
        text = "section a\n---\nsection b\n---\nfooter\n"
        assert scanner._detect_chatlog_pattern(text) is False

    def test_h3_header_does_not_count_as_divider(self, scanner: Scanner) -> None:
        # `### Heading` has text after the hashes — it's a header, not a
        # divider line. Three of them should NOT trigger rule 3 (but they DO
        # trigger rule 2, which is fine — that's a different rule).
        text = "### One header only\nbody continues here\n"
        assert scanner._detect_chatlog_pattern(text) is False

    # ---- Mixed / realistic ----

    def test_realistic_chat_log(self, scanner: Scanner) -> None:
        text = (
            "User: what's the weather\n"
            "Assistant: I don't have weather data.\n"
            "User: ok then tell me a joke\n"
            "Assistant: Why did the chicken cross the road?\n"
            "User: why\n"
            "Assistant: To get to the other side.\n"
        )
        assert scanner._detect_chatlog_pattern(text) is True

    def test_realistic_journal_with_dividers(self, scanner: Scanner) -> None:
        text = (
            "# 2026-04-10\n"
            "Worked on the scanner. Patched the OLE2 bug.\n"
            "---\n"
            "# 2026-04-09\n"
            "Designed the chatlog specialist.\n"
            "---\n"
            "# 2026-04-08\n"
            "Schema reshape day.\n"
            "---\n"
        )
        assert scanner._detect_chatlog_pattern(text) is True

    # ---- regression guards for PR #9 review comments ----

    def test_inline_h3_mentions_do_not_trigger_detection(self, scanner: Scanner) -> None:
        # Rule 2 ("3+ ### headers") must be line-anchored. Inline mentions of
        # the characters `### ` in prose or code should NOT trigger.
        # Regression guard for PR #9 comment 5.
        text = (
            "This document discusses markdown. The `### ` header level "
            "is third-level. You write `### ` like this and `### ` again "
            "and `### ` a third time in inline code.\n"
        )
        assert scanner._detect_chatlog_pattern(text) is False

    def test_only_dash_dividers_activate_rule_3(self, scanner: Scanner) -> None:
        # Rule 3 per spec §2.3: "3+ `---` section dividers." Other divider
        # styles do not participate in activation. Regression guard for
        # PR #9 comment 1. (The extraction layer still reports other styles
        # in section_marker_styles for files that activate via some other
        # rule — that's tested separately in TestExtractChatlogMetadata.)
        for divider in ("===", "***", "###"):
            text = f"section a\n{divider}\nsection b\n{divider}\nsection c\n{divider}\n"
            assert scanner._detect_chatlog_pattern(text) is False, (
                f"{divider} should not trigger rule-3 detection"
            )


class TestChatlogSpeakerStopList:
    """v0.9.1: speaker label stop-list prevents false positives from
    documentation patterns like Note:, Example:, Result:, Disallow:."""

    def test_stop_list_words_dont_trigger_detection(self, scanner: Scanner) -> None:
        text = "Note: something\nNote: another\nNote: third\n"
        assert scanner._detect_chatlog_pattern(text) is False

    def test_stop_list_mixed_with_real_speakers(self, scanner: Scanner) -> None:
        """Stop-list entries are excluded; real speakers still count."""
        text = (
            "User: hello\n"
            "Note: this is a note\n"
            "Assistant: hi there\n"
            "Example: some example\n"
            "User: thanks\n"
        )
        assert scanner._detect_chatlog_pattern(text) is True

    def test_stop_list_only_speakers_no_trigger(self, scanner: Scanner) -> None:
        """All speaker-like patterns are stop-listed — should not trigger."""
        text = (
            "Warning: be careful\n"
            "Error: something broke\n"
            "IMPORTANT: read this\n"
            "TIP: do this instead\n"
        )
        assert scanner._detect_chatlog_pattern(text) is False

    def test_stop_list_filtered_from_extraction(self, scanner: Scanner) -> None:
        """Stop-list entries don't appear in speaker_labels output."""
        text = (
            "User: hi\nUser: hi\nUser: hi\n"
            "Note: a\nNote: b\nNote: c\n"
            "Assistant: hey\nAssistant: hey\nAssistant: hey\n"
        )
        result = scanner._extract_chatlog_metadata(text)
        assert result is not None
        assert "Note" not in result["speaker_labels"]
        assert "User" in result["speaker_labels"]
        assert "Assistant" in result["speaker_labels"]

    def test_example_and_result_filtered(self, scanner: Scanner) -> None:
        """FastAPI-style false positives are filtered."""
        text = (
            "Example: first\nExample: second\nExample: third\n"
            "Result: a\nResult: b\nResult: c\n"
        )
        assert scanner._detect_chatlog_pattern(text) is False

    def test_disallow_filtered(self, scanner: Scanner) -> None:
        """robots.txt-style false positives are filtered."""
        text = "Disallow: /admin\nDisallow: /private\nDisallow: /secret\n"
        assert scanner._detect_chatlog_pattern(text) is False


class TestMarkdownMimetypeRegistration:
    """Regression guard for PR #9 comment 4: .mdx must have a text MIME
    type registered in stdlib mimetypes so that when libmagic is unavailable,
    the extension-fallback path doesn't return application/octet-stream
    and cause .mdx files to be misclassified as binary."""

    def test_mdx_mimetype_registered(self) -> None:
        import mimetypes
        # Importing scanner.scanner must trigger the mimetypes.add_type calls.
        import scanner.scanner  # noqa: F401
        guessed, _ = mimetypes.guess_type("foo.mdx")
        assert guessed is not None, ".mdx must resolve to a MIME type via stdlib mimetypes"
        assert guessed.startswith("text/"), f".mdx should resolve to a text/* MIME, got {guessed!r}"

    def test_md_mimetype_registered(self) -> None:
        import mimetypes
        import scanner.scanner  # noqa: F401
        guessed, _ = mimetypes.guess_type("foo.md")
        assert guessed is not None, ".md must resolve to a MIME type via stdlib mimetypes"
        assert guessed.startswith("text/"), f".md should resolve to a text/* MIME, got {guessed!r}"


class TestVocabularySizeEstimateSingleChar:
    """Regression guard for PR #9 comment 2: vocabulary_size_estimate must
    count single-character lowercase tokens ("a", "i") to avoid systematically
    undercounting natural prose vocabulary."""

    def test_single_char_tokens_counted(self, scanner: Scanner) -> None:
        text = "a b c d e f g h i j"
        meta = scanner._extract_chatlog_metadata(text)
        # 10 distinct single-char lowercase tokens.
        assert meta["vocabulary_size_estimate"] == 10

    def test_mixed_length_tokens_all_counted(self, scanner: Scanner) -> None:
        text = "I said a word today. A big word. I liked it."
        meta = scanner._extract_chatlog_metadata(text)
        # After lowercasing: i, said, a, word, today, big, liked, it = 8 distinct
        assert meta["vocabulary_size_estimate"] == 8


class TestIsChatlogIntegration:
    """End-to-end tests that the is_chatlog flag appears on FileRecord and
    runs even when enable_specialists is False."""

    def test_is_chatlog_default_false_on_filerecord(self) -> None:
        from scanner.scanner import FileRecord
        # Verify the field exists with the default value False.
        from dataclasses import fields
        names = {f.name for f in fields(FileRecord)}
        assert "is_chatlog" in names
        for f in fields(FileRecord):
            if f.name == "is_chatlog":
                assert f.default is False

    def test_chatlog_md_file_detected(self, tmp_path: Path) -> None:
        content = (
            "User: hi\n"
            "Assistant: hello\n"
            "User: tell me about scanner\n"
            "Assistant: it observes files.\n"
        )
        (tmp_path / "convo.md").write_text(content)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is True
        assert "is_chatlog" in rec.signal_provenance
        assert rec.signal_provenance["is_chatlog"]["trigger"] == "content_pattern_match"

    def test_chatlog_txt_file_detected(self, tmp_path: Path) -> None:
        # The .txt extension is also in the chatlog detection allow list.
        content = (
            "section\n---\nsection\n---\nsection\n---\nfooter\n"
        )
        (tmp_path / "log.txt").write_text(content)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is True

    def test_non_chatlog_md_file_not_detected(self, tmp_path: Path) -> None:
        content = "# A normal markdown doc\n\nJust some prose.\n"
        (tmp_path / "doc.md").write_text(content)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is False
        assert rec.signal_provenance["is_chatlog"]["trigger"] == "content_pattern_none"

    def test_non_target_extension_not_detected(self, tmp_path: Path) -> None:
        # .json files contain chatlog-pattern-matching content but aren't in
        # the .txt/.md/.mdx allow list, so detection should NOT run for them.
        content = '{"User": "hi", "Assistant": "hello"}'
        (tmp_path / "data.json").write_text(content)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is False
        # Provenance should not be recorded for files where detection doesn't run.
        assert "is_chatlog" not in rec.signal_provenance

    def test_binary_file_not_detected(self, tmp_path: Path) -> None:
        # Binary files (e.g. PNGs) never get text-decoded, so chatlog
        # detection cannot run and is_chatlog stays False with no provenance.
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        (tmp_path / "image.png").write_bytes(png_header)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is False
        assert "is_chatlog" not in rec.signal_provenance

    def test_detection_runs_with_specialists_disabled(self, tmp_path: Path) -> None:
        # Phase 1 requirement: chatlog detection must run even when
        # enable_specialists=False, because the detection is cheap.
        content = "User: hi\nAssistant: hello\nUser: again\n"
        (tmp_path / "chat.md").write_text(content)
        config = ScannerConfig(enable_specialists=False)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is True

    def test_is_chatlog_serializes_to_json(self, tmp_path: Path) -> None:
        from scanner.scanner import manifest_to_json
        import json as _json
        content = "### A\n### B\n### C\n### D\n### E\n"
        (tmp_path / "headers.md").write_text(content)
        manifest = Scanner(source_dir=tmp_path).scan()
        data = _json.loads(manifest_to_json(manifest))
        rec = data["files"][0]
        assert rec["is_chatlog"] is True


# ---------------------------------------------------------------------------
# v0.8 Phase 2: chatlog specialist extraction
# ---------------------------------------------------------------------------

class TestExtractChatlogMetadata:
    """Unit tests for _extract_chatlog_metadata.

    Per spec §2.4 / §2.5 / §2.6, the function returns 11 fields. Each test
    isolates one or two of them with a minimal targeted input.
    """

    def test_empty_text_returns_none(self, scanner: Scanner) -> None:
        assert scanner._extract_chatlog_metadata("") is None

    def test_minimal_chatlog_all_fields_present(self, scanner: Scanner) -> None:
        text = "User: hi\nAssistant: hello\nUser: again\n"
        meta = scanner._extract_chatlog_metadata(text)
        assert meta is not None
        for key in (
            "turn_count", "speaker_labels", "section_marker_count",
            "section_marker_styles", "avg_turn_chars", "max_turn_chars",
            "min_turn_chars", "reference_tokens", "top_capitalized_tokens",
            "capitalized_token_count", "vocabulary_size_estimate",
        ):
            assert key in meta, f"missing field: {key}"
        for ref_key in ("at_mentions", "wiki_links", "code_fence_blocks", "url_count"):
            assert ref_key in meta["reference_tokens"], f"missing reference_tokens field: {ref_key}"

    # ---- turn_count ----

    def test_turn_count_counts_all_speaker_label_occurrences(self, scanner: Scanner) -> None:
        text = "User: a\nAssistant: b\nUser: c\nAssistant: d\nUser: e\n"
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["turn_count"] == 5

    def test_turn_count_does_not_filter_by_repetition(self, scanner: Scanner) -> None:
        # turn_count is the raw match count; one-off proper nouns inflate it
        # but get filtered out of speaker_labels.
        text = "User: a\nUser: b\nUser: c\nBob: stranger\nAlice: stranger\n"
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["turn_count"] == 5
        assert meta["speaker_labels"] == ["User"]

    # ---- speaker_labels ----

    def test_speaker_labels_filtered_to_3_plus_repetition(self, scanner: Scanner) -> None:
        text = (
            "Russell: hi\n"
            "Russell: again\n"
            "Russell: third time\n"
            "Bob: one off\n"
        )
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["speaker_labels"] == ["Russell"]
        assert "Bob" not in meta["speaker_labels"]

    def test_speaker_labels_sorted_alphabetically(self, scanner: Scanner) -> None:
        text = (
            "Zander: a\nZander: b\nZander: c\n"
            "Alice: a\nAlice: b\nAlice: c\n"
            "Mike: a\nMike: b\nMike: c\n"
        )
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["speaker_labels"] == ["Alice", "Mike", "Zander"]

    # ---- turn char stats ----

    def test_turn_char_stats(self, scanner: Scanner) -> None:
        # Three speakers with controlled spacing — avg/min/max should reflect
        # the character distance between consecutive speaker labels.
        text = "User: a\nAssistant: bb\nUser: ccc\n"
        meta = scanner._extract_chatlog_metadata(text)
        # Two intervals between three speaker labels: short and longer.
        assert meta["max_turn_chars"] >= meta["min_turn_chars"]
        assert meta["max_turn_chars"] >= 1
        assert meta["min_turn_chars"] >= 1
        assert meta["avg_turn_chars"] >= 1

    def test_turn_char_stats_zero_when_no_speakers(self, scanner: Scanner) -> None:
        text = "Just plain prose with no speaker labels at all here."
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["turn_count"] == 0
        assert meta["avg_turn_chars"] == 0
        assert meta["max_turn_chars"] == 0
        assert meta["min_turn_chars"] == 0

    # ---- section markers ----

    def test_pure_dash_dividers_counted(self, scanner: Scanner) -> None:
        text = "section a\n---\nsection b\n---\nsection c\n---\n"
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["section_marker_count"] == 3
        assert "---" in meta["section_marker_styles"]

    def test_pure_equals_dividers_counted(self, scanner: Scanner) -> None:
        text = "===\n===\n===\n"
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["section_marker_count"] == 3
        assert "===" in meta["section_marker_styles"]

    def test_md_headers_counted_separately_from_dividers(self, scanner: Scanner) -> None:
        text = "### Header A\n### Header B\n## Header C\n"
        meta = scanner._extract_chatlog_metadata(text)
        # Three headers — `### `, `### `, `## `
        assert meta["section_marker_count"] == 3
        assert "### " in meta["section_marker_styles"]
        assert "## " in meta["section_marker_styles"]

    def test_section_marker_styles_sorted(self, scanner: Scanner) -> None:
        text = "===\n---\n***\n### Header\n"
        meta = scanner._extract_chatlog_metadata(text)
        # Sorted alphabetically.
        assert meta["section_marker_styles"] == sorted(meta["section_marker_styles"])

    # ---- reference tokens ----

    def test_reference_at_mentions(self, scanner: Scanner) -> None:
        text = "Hello @alice and @bob and @carol_smith here."
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["reference_tokens"]["at_mentions"] == 3

    def test_reference_wiki_links(self, scanner: Scanner) -> None:
        text = "See [[Project Sentinel]] and [[Russell]] and [[also]]."
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["reference_tokens"]["wiki_links"] == 3

    def test_reference_code_fence_blocks(self, scanner: Scanner) -> None:
        text = "```\ncode1\n```\nprose\n```\ncode2\n```\n"
        meta = scanner._extract_chatlog_metadata(text)
        # Two complete code fence pairs → 2 blocks.
        assert meta["reference_tokens"]["code_fence_blocks"] == 2

    def test_reference_urls(self, scanner: Scanner) -> None:
        text = "Visit https://example.com and http://other.com please."
        meta = scanner._extract_chatlog_metadata(text)
        assert meta["reference_tokens"]["url_count"] == 2

    # ---- capitalized tokens ----

    def test_capitalized_tokens_filtered_by_length(self, scanner: Scanner) -> None:
        # Tokens shorter than 3 chars (e.g. "DM", "OK") should NOT count.
        text = "DM speaks. OK then. " * 5
        meta = scanner._extract_chatlog_metadata(text)
        assert "DM" not in meta["top_capitalized_tokens"]
        assert "OK" not in meta["top_capitalized_tokens"]

    def test_capitalized_tokens_filtered_by_frequency(self, scanner: Scanner) -> None:
        # Sentinel appears 3 times → qualifies. OneOff appears once → doesn't.
        text = "Sentinel was here. Sentinel returned. Sentinel again. OneOff visited."
        meta = scanner._extract_chatlog_metadata(text)
        assert "Sentinel" in meta["top_capitalized_tokens"]
        assert "OneOff" not in meta["top_capitalized_tokens"]
        assert meta["capitalized_token_count"] == 1

    def test_top_capitalized_tokens_sorted_by_frequency_desc(self, scanner: Scanner) -> None:
        text = (
            "Russell Russell Russell Russell Russell "
            "Sentinel Sentinel Sentinel "
            "Mountain Mountain Mountain Mountain "
        )
        meta = scanner._extract_chatlog_metadata(text)
        # Russell (5) > Mountain (4) > Sentinel (3)
        assert meta["top_capitalized_tokens"] == ["Russell", "Mountain", "Sentinel"]

    def test_top_capitalized_tokens_alphabetical_secondary(self, scanner: Scanner) -> None:
        text = (
            "Charlie Charlie Charlie "
            "Alpha Alpha Alpha "
            "Bravo Bravo Bravo "
        )
        meta = scanner._extract_chatlog_metadata(text)
        # All freq 3 — alphabetical order.
        assert meta["top_capitalized_tokens"] == ["Alpha", "Bravo", "Charlie"]

    def test_top_capitalized_tokens_capped_at_default_n(self, scanner: Scanner) -> None:
        # Make 25 distinct qualifying tokens — output should be capped at 20.
        names = [f"Name{i:02d}" for i in range(25)]
        text = " ".join(name + " " + name + " " + name for name in names)
        meta = scanner._extract_chatlog_metadata(text)
        assert len(meta["top_capitalized_tokens"]) == 20
        assert meta["capitalized_token_count"] == 25

    # ---- vocabulary size estimate ----

    def test_vocabulary_size_estimate_counts_distinct_lowercase_words(self, scanner: Scanner) -> None:
        text = "the quick brown fox jumps over the lazy dog the fox runs"
        meta = scanner._extract_chatlog_metadata(text)
        # distinct lowercase words: the, quick, brown, fox, jumps, over, lazy, dog, runs = 9
        assert meta["vocabulary_size_estimate"] == 9

    def test_vocabulary_size_includes_uppercase_words_lowercased(self, scanner: Scanner) -> None:
        text = "Hello World hello world HELLO WORLD"
        meta = scanner._extract_chatlog_metadata(text)
        # All become lowercase: hello, world = 2 distinct
        assert meta["vocabulary_size_estimate"] == 2

    # ---- determinism ----

    def test_deterministic_output(self, scanner: Scanner) -> None:
        text = (
            "User: hi\nAssistant: hello\nUser: again\n"
            "### A\n### B\n### C\n"
            "@alice and @bob and @carol\n"
        )
        m1 = scanner._extract_chatlog_metadata(text)
        m2 = scanner._extract_chatlog_metadata(text)
        assert m1 == m2


class TestChatlogSpecialistIntegration:
    """End-to-end tests that the chatlog specialist activates content-detected,
    populates specialist_metadata, and overrides routing flags correctly."""

    CHATLOG_TEXT = (
        "User: tell me about Sentinel\n"
        "Assistant: Sentinel is a project. Russell is the architect.\n"
        "User: who else is involved\n"
        "Assistant: Russell, Russell, and Russell again.\n"
        "User: thanks\n"
        "Assistant: anytime\n"
    )

    def test_chatlog_extraction_populates_metadata(self, tmp_path: Path) -> None:
        (tmp_path / "chat.md").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is True
        assert rec.specialist_metadata is not None
        assert "chatlog" in rec.specialist_metadata
        chat = rec.specialist_metadata["chatlog"]
        assert chat["turn_count"] == 6
        assert "User" in chat["speaker_labels"]
        assert "Assistant" in chat["speaker_labels"]

    def test_chatlog_specialist_tool_set(self, tmp_path: Path) -> None:
        (tmp_path / "chat.md").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert rec.specialist_tool == "chatlog_signals"
        assert rec.requires_specialist_tool is True

    def test_chatlog_specialist_tool_set_without_extraction(self, tmp_path: Path) -> None:
        # Even without enable_specialists, when is_chatlog activates the
        # specialist_tool field should be set so consumers know which tool
        # would have run. The actual specialist_metadata stays None.
        (tmp_path / "chat.md").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=False)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is True
        assert rec.specialist_tool == "chatlog_signals"
        assert rec.requires_specialist_tool is True
        assert rec.specialist_metadata is None  # extraction gated

    def test_per_field_provenance_recorded(self, tmp_path: Path) -> None:
        (tmp_path / "chat.md").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        # Per-field provenance entries for each top-level chatlog field.
        for field_name in (
            "turn_count", "speaker_labels", "section_marker_count",
            "section_marker_styles", "reference_tokens", "top_capitalized_tokens",
            "vocabulary_size_estimate",
        ):
            prov_key = f"specialist_metadata.chatlog.{field_name}"
            assert prov_key in rec.signal_provenance, f"missing provenance for {prov_key}"
            assert rec.signal_provenance[prov_key]["trigger"] == "bounded_text"
            assert rec.signal_provenance[prov_key]["detail"]["tool"] == "chatlog_signals"

    def test_non_chatlog_md_does_not_get_specialist(self, tmp_path: Path) -> None:
        (tmp_path / "doc.md").write_text("# Just a heading\n\nplain prose follows.\n")
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is False
        assert rec.specialist_tool is None
        assert rec.specialist_metadata is None

    def test_chatlog_serializes_to_json_manifest(self, tmp_path: Path) -> None:
        from scanner.scanner import manifest_to_json
        import json as _json
        (tmp_path / "chat.md").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        data = _json.loads(manifest_to_json(manifest))
        rec = data["files"][0]
        assert rec["specialist_metadata"]["chatlog"]["turn_count"] == 6
        assert "Russell" in rec["specialist_metadata"]["chatlog"]["top_capitalized_tokens"]

    def test_chatlog_txt_file_full_extraction(self, tmp_path: Path) -> None:
        # .txt files should also get the chatlog specialist when content matches.
        (tmp_path / "log.txt").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is True
        assert rec.specialist_metadata is not None
        assert "chatlog" in rec.specialist_metadata


# ---------------------------------------------------------------------------
# v0.8 Phase 3: ScanQuality.chatlog_files counter
# ---------------------------------------------------------------------------

class TestScanQualityChatlogFiles:
    """Phase 3 work: the manifest-level quality block gains a chatlog_files
    counter that mirrors the per-file is_chatlog flag aggregated to the
    whole scan."""

    def test_chatlog_files_counter_field_exists(self) -> None:
        from scanner.scanner import ScanQuality
        from dataclasses import fields
        names = {f.name for f in fields(ScanQuality)}
        assert "chatlog_files" in names

    def test_chatlog_files_counter_zero_on_empty_corpus(self, tmp_path: Path) -> None:
        # Single non-chatlog file → counter is zero, not missing.
        (tmp_path / "doc.md").write_text("# A heading\n\nplain prose.\n")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert manifest.quality.chatlog_files == 0

    def test_chatlog_files_counter_counts_detections(self, tmp_path: Path) -> None:
        # Three chatlog files + two non-chatlog files → counter == 3.
        chat = "User: a\nAssistant: b\nUser: c\nAssistant: d\nUser: e\nAssistant: f\n"
        (tmp_path / "chat1.md").write_text(chat)
        (tmp_path / "chat2.md").write_text(chat)
        (tmp_path / "chat3.txt").write_text(chat)
        (tmp_path / "doc1.md").write_text("# Heading\n\nprose.\n")
        (tmp_path / "doc2.md").write_text("# Other heading\n\nmore prose.\n")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert manifest.quality.chatlog_files == 3
        assert manifest.quality.total_files == 5

    def test_chatlog_files_counter_independent_of_specialist_extraction(self, tmp_path: Path) -> None:
        # Detection (and the counter) runs even with enable_specialists=False.
        chat = "User: a\nUser: b\nUser: c\nAssistant: a\nAssistant: b\nAssistant: c\n"
        (tmp_path / "chat.md").write_text(chat)
        config = ScannerConfig(enable_specialists=False)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        assert manifest.quality.chatlog_files == 1

    def test_chatlog_files_counter_in_json_serialization(self, tmp_path: Path) -> None:
        from scanner.scanner import manifest_to_json
        import json as _json
        chat = "User: a\nUser: b\nUser: c\nAssistant: a\nAssistant: b\nAssistant: c\n"
        (tmp_path / "chat.md").write_text(chat)
        manifest = Scanner(source_dir=tmp_path).scan()
        data = _json.loads(manifest_to_json(manifest))
        assert data["quality"]["chatlog_files"] == 1


# ---------------------------------------------------------------------------
# v0.8 Phase 4: chatlog fixtures (real files in tests/fixtures/edge_cases/)
# ---------------------------------------------------------------------------

class TestChatlogFixtures:
    """Verify the chatlog specialist works against the real fixture files
    that ship in tests/fixtures/edge_cases/ — one fixture per detection rule."""

    @property
    def fixtures_dir(self) -> Path:
        return Path(__file__).parent / "fixtures" / "edge_cases"

    def _scan_one_file(self, fixture_name: str, tmp_path: Path) -> Any:
        # Copy a single fixture into a temp dir so the scanner only sees it.
        # Explicit utf-8 so the copy is deterministic on non-UTF-8 locales —
        # the fixtures include unicode characters (em-dashes) that would
        # otherwise depend on the platform default encoding.
        src = self.fixtures_dir / fixture_name
        dst = tmp_path / fixture_name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        return manifest.files[0]

    def test_conversation_fixture_speaker_labels(self, tmp_path: Path) -> None:
        rec = self._scan_one_file("chatlog_conversation.md", tmp_path)
        assert rec.is_chatlog is True
        assert rec.specialist_metadata is not None
        chat = rec.specialist_metadata["chatlog"]
        assert "User" in chat["speaker_labels"]
        assert "Assistant" in chat["speaker_labels"]
        assert chat["turn_count"] >= 6

    def test_journal_fixture_section_dividers(self, tmp_path: Path) -> None:
        rec = self._scan_one_file("chatlog_journal.md", tmp_path)
        assert rec.is_chatlog is True
        chat = rec.specialist_metadata["chatlog"]
        # Has both --- dividers AND # headers
        assert chat["section_marker_count"] >= 3
        assert "---" in chat["section_marker_styles"]

    def test_headers_fixture_h3_rule(self, tmp_path: Path) -> None:
        rec = self._scan_one_file("chatlog_headers.md", tmp_path)
        assert rec.is_chatlog is True
        chat = rec.specialist_metadata["chatlog"]
        assert chat["section_marker_count"] >= 6  # 5 ### headers + 1 # header = 6
        assert "### " in chat["section_marker_styles"]


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
        assert SCANNER_VERSION == "0.9.2"
        assert LOGIC_VERSION == "0.9.0"


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
    def test_doc_without_olefile_returns_none(self, scanner: Scanner, tmp_path: Path) -> None:
        import scanner.scanner as mod
        (tmp_path / "fake.doc").write_bytes(b"fake content")
        original = mod.olefile
        try:
            mod.olefile = None
            result = scanner._extract_doc_metadata(tmp_path / "fake.doc")
            assert result is None
        finally:
            mod.olefile = original

    def test_doc_non_ole_file_returns_none(self, tmp_path: Path) -> None:
        # Sanity check that the OLE2 path-based extractor rejects non-OLE files
        # (regression guard for the v0.7.1 OLE2 sample-vs-path fix).
        (tmp_path / "fake.doc").write_bytes(b"not an OLE file")
        scanner = Scanner(source_dir=tmp_path)
        result = scanner._extract_doc_metadata(tmp_path / "fake.doc")
        assert result is None

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


# ---------------------------------------------------------------------------
# v0.7: XLS specialist
# ---------------------------------------------------------------------------

class TestXlsSpecialist:
    def test_xls_in_supported_extensions(self) -> None:
        from scanner.scanner import SUPPORTED_EXTENSIONS, SPECIALIST_TOOLS, SPECIALIST_NAMESPACE
        assert ".xls" in SUPPORTED_EXTENSIONS
        assert SPECIALIST_TOOLS[".xls"] == "spreadsheet_structure"
        assert SPECIALIST_NAMESPACE[".xls"] == "spreadsheet"

    def test_xls_invalid_file_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "bad.xls").write_bytes(b"not an OLE file")
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is None

    def test_xls_without_olefile(self, scanner: Scanner, tmp_path: Path) -> None:
        import scanner.scanner as mod
        (tmp_path / "fake.xls").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)
        original = mod.olefile
        try:
            mod.olefile = None
            result = scanner._extract_xls_metadata(tmp_path / "fake.xls")
            assert result is None
        finally:
            mod.olefile = original

    def test_xls_non_ole_file_returns_none(self, tmp_path: Path) -> None:
        # Regression guard for the v0.7.1 OLE2 sample-vs-path fix: the path-based
        # extractor must reject non-OLE files cleanly.
        (tmp_path / "bad.xls").write_bytes(b"not an OLE file")
        scanner = Scanner(source_dir=tmp_path)
        result = scanner._extract_xls_metadata(tmp_path / "bad.xls")
        assert result is None

    def test_xlsx_includes_format_field(self, tmp_path: Path) -> None:
        import zipfile
        from io import BytesIO
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Sheet1"/></sheets></workbook>')
        (tmp_path / "test.xlsx").write_bytes(buf.getvalue())
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert rec.specialist_metadata is not None
        assert rec.specialist_metadata["spreadsheet"]["format"] == "ooxml"


# ---------------------------------------------------------------------------
# v0.7: Safety flags
# ---------------------------------------------------------------------------

class TestSafetyFlags:
    def test_safety_flags_default_empty(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.safety_flags == []

    def test_pdf_javascript_detected(self, tmp_path: Path) -> None:
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n/JavaScript (alert('hi'))\n")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "has_javascript" in rec.safety_flags

    def test_pdf_no_javascript(self, tmp_path: Path) -> None:
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n/Font /Text\n")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "has_javascript" not in rec.safety_flags

    def test_docx_macros_detected(self, tmp_path: Path) -> None:
        import zipfile
        from io import BytesIO
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<doc/>")
            zf.writestr("word/vbaProject.bin", b"\xd0\xcf\x11\xe0")
        (tmp_path / "macro.docx").write_bytes(buf.getvalue())
        # DOCX macro detection requires specialists enabled (gated to avoid extra I/O)
        config = ScannerConfig(enable_specialists=True)
        scanner = Scanner(source_dir=tmp_path, config=config)
        rec = scanner.scan().files[0]
        assert "has_macros" in rec.safety_flags

    def test_docx_no_macros(self, tmp_path: Path) -> None:
        import zipfile
        from io import BytesIO
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<doc/>")
        (tmp_path / "clean.docx").write_bytes(buf.getvalue())
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "has_macros" not in rec.safety_flags

    def test_rtf_ole_detected(self, tmp_path: Path) -> None:
        (tmp_path / "doc.rtf").write_bytes(rb"{\rtf1 {\object\objemb}}")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "has_ole_objects" in rec.safety_flags

    def test_xml_external_entity_detected(self, tmp_path: Path) -> None:
        xml = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
        (tmp_path / "xxe.xml").write_bytes(xml)
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert "has_external_references" in rec.safety_flags

    def test_safety_flags_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n/JavaScript /JS\n")
        scanner = Scanner(source_dir=tmp_path)
        rec = scanner.scan().files[0]
        assert rec.safety_flags == sorted(rec.safety_flags)


# ---------------------------------------------------------------------------
# v0.7: Scan quality signals
# ---------------------------------------------------------------------------

class TestScanQuality:
    def test_quality_present(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert manifest.quality is not None
        assert manifest.quality.total_files == 1

    def test_quality_clean_count(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert manifest.quality.clean_files == 2
        assert manifest.quality.degraded_files == 0

    def test_quality_totals_consistent(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.bin").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)
        manifest = Scanner(source_dir=tmp_path).scan()
        q = manifest.quality
        assert q.clean_files + q.degraded_files + q.error_files == q.total_files

    def test_quality_mime_mismatch_count(self, tmp_path: Path) -> None:
        # PNG content in .txt file
        (tmp_path / "spoof.txt").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)
        manifest = Scanner(source_dir=tmp_path).scan()
        assert manifest.quality.mime_mismatches >= 1

    def test_quality_safety_count(self, tmp_path: Path) -> None:
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n/JavaScript test\n")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert manifest.quality.safety_flags >= 1


# ---------------------------------------------------------------------------
# v0.9: Vector Abstraction Tests
# ---------------------------------------------------------------------------


class TestVectorIdentityDigest:
    """Test the identity digest computation per spec §2.4."""

    def test_deterministic(self) -> None:
        from scanner.scanner import compute_vector_identity_digest
        d1 = compute_vector_identity_digest("chatlog", 1, "abc", "def")
        d2 = compute_vector_identity_digest("chatlog", 1, "abc", "def")
        assert d1 == d2
        assert len(d1) == 64  # SHA-256 hex

    def test_different_vector_id(self) -> None:
        from scanner.scanner import compute_vector_identity_digest
        d1 = compute_vector_identity_digest("chatlog", 1, "abc", "def")
        d2 = compute_vector_identity_digest("reference_tokens", 1, "abc", "def")
        assert d1 != d2

    def test_different_method_version(self) -> None:
        from scanner.scanner import compute_vector_identity_digest
        d1 = compute_vector_identity_digest("chatlog", 1, "abc", "def")
        d2 = compute_vector_identity_digest("chatlog", 2, "abc", "def")
        assert d1 != d2

    def test_different_rules_hash(self) -> None:
        from scanner.scanner import compute_vector_identity_digest
        d1 = compute_vector_identity_digest("chatlog", 1, "abc", "def")
        d2 = compute_vector_identity_digest("chatlog", 1, "xyz", "def")
        assert d1 != d2

    def test_different_tuning_hash(self) -> None:
        from scanner.scanner import compute_vector_identity_digest
        d1 = compute_vector_identity_digest("chatlog", 1, "abc", "def")
        d2 = compute_vector_identity_digest("chatlog", 1, "abc", "ghi")
        assert d1 != d2

    def test_null_future_fields(self) -> None:
        from scanner.scanner import compute_vector_identity_digest
        d1 = compute_vector_identity_digest("chatlog", 1, "abc", "def", None, None)
        d2 = compute_vector_identity_digest("chatlog", 1, "abc", "def")
        assert d1 == d2  # None defaults to "null" in preimage

    def test_preimage_is_pipe_delimited(self) -> None:
        from hashlib import sha256
        from scanner.scanner import compute_vector_identity_digest
        expected_preimage = "chatlog|1|abc|def|null|null"
        expected = sha256(expected_preimage.encode("utf-8")).hexdigest()
        actual = compute_vector_identity_digest("chatlog", 1, "abc", "def")
        assert actual == expected


class TestRulesAndTuningHash:
    def test_rules_hash_deterministic(self) -> None:
        from scanner.scanner import compute_rules_hash
        h1 = compute_rules_hash("some rule definition")
        h2 = compute_rules_hash("some rule definition")
        assert h1 == h2

    def test_rules_hash_changes_with_content(self) -> None:
        from scanner.scanner import compute_rules_hash
        h1 = compute_rules_hash("rule v1")
        h2 = compute_rules_hash("rule v2")
        assert h1 != h2

    def test_tuning_hash_deterministic(self) -> None:
        from scanner.scanner import compute_tuning_hash
        h1 = compute_tuning_hash({"threshold": 3, "top_n": 20})
        h2 = compute_tuning_hash({"threshold": 3, "top_n": 20})
        assert h1 == h2

    def test_tuning_hash_key_order_independent(self) -> None:
        from scanner.scanner import compute_tuning_hash
        h1 = compute_tuning_hash({"top_n": 20, "threshold": 3})
        h2 = compute_tuning_hash({"threshold": 3, "top_n": 20})
        assert h1 == h2

    def test_tuning_hash_changes_with_values(self) -> None:
        from scanner.scanner import compute_tuning_hash
        h1 = compute_tuning_hash({"threshold": 3})
        h2 = compute_tuning_hash({"threshold": 4})
        assert h1 != h2


class TestVectorRegistry:
    def test_empty_registry(self) -> None:
        from scanner.scanner import VectorRegistry
        reg = VectorRegistry()
        assert reg.to_list() == []

    def test_register_and_retrieve(self) -> None:
        from scanner.scanner import VectorRegistry, VectorRecord
        reg = VectorRegistry()
        rec = VectorRecord(
            vector_id="chatlog", method_version=1, scope="file",
            rules_hash="abc", static_tuning_hash="def",
            dynamic_tuning_hash=None, dictionary_id=None,
            identity_digest="fff", applied_to_count=5,
            summary={"matched_files": 5},
        )
        reg.register(rec)
        result = reg.to_list()
        assert len(result) == 1
        assert result[0]["vector_id"] == "chatlog"

    def test_sorted_alphabetically(self) -> None:
        from scanner.scanner import VectorRegistry, VectorRecord
        reg = VectorRegistry()
        for vid in ["reference_tokens", "chatlog"]:
            reg.register(VectorRecord(
                vector_id=vid, method_version=1, scope="file",
                rules_hash="x", static_tuning_hash="y",
                dynamic_tuning_hash=None, dictionary_id=None,
                identity_digest="z", applied_to_count=0,
                summary={},
            ))
        result = reg.to_list()
        assert result[0]["vector_id"] == "chatlog"
        assert result[1]["vector_id"] == "reference_tokens"


class TestManifestVectorsCollected:
    def test_vectors_collected_present_on_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert hasattr(manifest, "vectors_collected")
        assert isinstance(manifest.vectors_collected, list)

    def test_vectors_collected_in_json_output(self, tmp_path: Path) -> None:
        import json
        from scanner.scanner import manifest_to_json
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        data = json.loads(manifest_to_json(manifest))
        assert "vectors_collected" in data

    def test_vectors_collected_in_jsonl_output(self, tmp_path: Path) -> None:
        import json
        from scanner.scanner import manifest_to_jsonl
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        lines = manifest_to_jsonl(manifest).strip().split("\n")
        header = json.loads(lines[0])
        assert "vectors_collected" in header


class TestChatlogVector:
    """Test chatlog vector registration and corpus summary."""

    CHATLOG_TEXT = (
        "User: hello there\n"
        "Assistant: hi back\n"
        "User: how are you\n"
        "Assistant: doing well\n"
        "User: thanks\n"
        "Assistant: anytime\n"
    )

    def test_chatlog_vector_registered_when_chatlog_detected(self, tmp_path: Path) -> None:
        (tmp_path / "chat.txt").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        vec_ids = [v["vector_id"] for v in manifest.vectors_collected]
        assert "chatlog" in vec_ids

    def test_chatlog_vector_always_registered(self, tmp_path: Path) -> None:
        """Chatlog vector is registered even with no chatlog files."""
        (tmp_path / "a.txt").write_text("hello world")
        manifest = Scanner(source_dir=tmp_path).scan()
        vec_ids = [v["vector_id"] for v in manifest.vectors_collected]
        assert "chatlog" in vec_ids

    def test_chatlog_vector_applied_count(self, tmp_path: Path) -> None:
        (tmp_path / "chat.txt").write_text(self.CHATLOG_TEXT)
        (tmp_path / "plain.txt").write_text("not a chatlog")
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        chatlog_vec = [v for v in manifest.vectors_collected if v["vector_id"] == "chatlog"][0]
        assert chatlog_vec["applied_to_count"] == 1

    def test_chatlog_vector_summary_fields(self, tmp_path: Path) -> None:
        (tmp_path / "chat.txt").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        chatlog_vec = [v for v in manifest.vectors_collected if v["vector_id"] == "chatlog"][0]
        summary = chatlog_vec["summary"]
        assert summary["matched_files"] == 1
        assert summary["total_turns"] == 6
        assert "User" in summary["distinct_speakers"]
        assert "Assistant" in summary["distinct_speakers"]

    def test_chatlog_vector_identity_digest_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "chat.txt").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        m1 = Scanner(source_dir=tmp_path, config=config).scan()
        m2 = Scanner(source_dir=tmp_path, config=config).scan()
        d1 = [v for v in m1.vectors_collected if v["vector_id"] == "chatlog"][0]["identity_digest"]
        d2 = [v for v in m2.vectors_collected if v["vector_id"] == "chatlog"][0]["identity_digest"]
        assert d1 == d2

    def test_chatlog_vector_specialists_disabled(self, tmp_path: Path) -> None:
        """With specialists disabled, chatlog vector counts detections but summary stays zero."""
        (tmp_path / "chat.txt").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=False)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        chatlog_vec = [v for v in manifest.vectors_collected if v["vector_id"] == "chatlog"][0]
        assert chatlog_vec["applied_to_count"] == 1
        assert chatlog_vec["summary"]["matched_files"] == 1
        # No specialist metadata populated, so summary aggregates stay zero
        assert chatlog_vec["summary"]["total_turns"] == 0

    def test_chatlog_vector_v08_backwards_compat(self, tmp_path: Path) -> None:
        """v0.8 fields (is_chatlog, specialist_metadata.chatlog) still work."""
        (tmp_path / "chat.txt").write_text(self.CHATLOG_TEXT)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        chat_rec = [r for r in manifest.files if r.filename == "chat.txt"][0]
        assert chat_rec.is_chatlog is True
        assert chat_rec.specialist_metadata is not None
        assert "chatlog" in chat_rec.specialist_metadata


class TestReferenceTokensVector:
    """Test reference_tokens vector extraction and registration."""

    def test_reference_tokens_on_text_file(self, tmp_path: Path) -> None:
        text = "Contact @admin or visit https://example.com. See [[WikiPage]].\n"
        (tmp_path / "doc.md").write_text(text)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens is not None
        assert rec.reference_tokens["at_mentions"] == 1
        assert rec.reference_tokens["url_count"] == 1
        assert rec.reference_tokens["wiki_links"] == 1

    def test_reference_tokens_null_on_binary(self, tmp_path: Path) -> None:
        (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens is None

    def test_reference_tokens_vector_registered(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        vec_ids = [v["vector_id"] for v in manifest.vectors_collected]
        assert "reference_tokens" in vec_ids

    def test_reference_tokens_applied_count(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.md").write_text("world")
        (tmp_path / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)
        manifest = Scanner(source_dir=tmp_path).scan()
        rt_vec = [v for v in manifest.vectors_collected if v["vector_id"] == "reference_tokens"][0]
        assert rt_vec["applied_to_count"] == 2  # txt + md, not png

    def test_reference_tokens_corpus_summary(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("@alice @bob https://example.com")
        (tmp_path / "b.md").write_text("@charlie see [[Page]]")
        manifest = Scanner(source_dir=tmp_path).scan()
        rt_vec = [v for v in manifest.vectors_collected if v["vector_id"] == "reference_tokens"][0]
        assert rt_vec["summary"]["at_mentions"] == 3
        assert rt_vec["summary"]["files_with_any_reference"] == 2

    def test_reference_tokens_email_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("Contact user@example.com and admin@test.org")
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens["email_mentions"] == 2

    def test_reference_tokens_path_references(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("See /usr/local/bin or C:\\Users\\test\\file")
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens["path_references"] >= 1

    def test_path_references_url_fragments_excluded(self, tmp_path: Path) -> None:
        """v0.9.2: URL path fragments should not count as path references."""
        text = "Visit https://www.googleapis.com/auth/chat.admin.delete for docs"
        (tmp_path / "a.txt").write_text(text)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens["path_references"] == 0

    def test_path_references_real_paths_still_match(self, tmp_path: Path) -> None:
        text = "Config at /etc/nginx/conf.d and /home/user/.config/app"
        (tmp_path / "a.txt").write_text(text)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens["path_references"] == 2

    def test_path_references_start_of_line(self, tmp_path: Path) -> None:
        text = "/usr/local/bin/python3\n/home/user/.bashrc is not deep enough"
        (tmp_path / "a.txt").write_text(text)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens["path_references"] >= 1

    def test_path_references_api_endpoint_in_json_excluded(self, tmp_path: Path) -> None:
        """v0.9.2: API paths inside JSON values should not match."""
        text = '{"scope": "https://example.com/api/v1/users"}'
        (tmp_path / "a.json").write_text(text)
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens["path_references"] == 0

    def test_reference_tokens_numeric_ids(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("Fix #123 and PROJ-456 for v2.1 release")
        manifest = Scanner(source_dir=tmp_path).scan()
        rec = manifest.files[0]
        assert rec.reference_tokens["numeric_id_patterns"] >= 3

    def test_reference_tokens_identity_digest_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("@test https://example.com")
        m1 = Scanner(source_dir=tmp_path).scan()
        m2 = Scanner(source_dir=tmp_path).scan()
        d1 = [v for v in m1.vectors_collected if v["vector_id"] == "reference_tokens"][0]["identity_digest"]
        d2 = [v for v in m2.vectors_collected if v["vector_id"] == "reference_tokens"][0]["identity_digest"]
        assert d1 == d2

    def test_vectors_sorted_alphabetically(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        vec_ids = [v["vector_id"] for v in manifest.vectors_collected]
        assert vec_ids == sorted(vec_ids)


class TestEmailBodyChatlogCrosscut:
    """Test email body chatlog cross-cut per spec §4.1."""

    CHATLOG_EML = (
        "From: sender@example.com\r\n"
        "To: recipient@example.com\r\n"
        "Subject: Chat thread\r\n"
        "Date: Mon, 1 Jan 2026 12:00:00 +0000\r\n"
        "Message-ID: <test@example.com>\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "User: hello there\r\n"
        "Assistant: hi back\r\n"
        "User: how are you\r\n"
        "Assistant: doing well\r\n"
        "User: thanks for the help\r\n"
        "Assistant: anytime\r\n"
    )

    PLAIN_EML = (
        "From: sender@example.com\r\n"
        "To: recipient@example.com\r\n"
        "Subject: Normal email\r\n"
        "Date: Mon, 1 Jan 2026 12:00:00 +0000\r\n"
        "Message-ID: <plain@example.com>\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Hello, this is a normal email body with no chatlog patterns.\r\n"
    )

    def test_body_chatlog_fires_on_chatlog_email(self, tmp_path: Path) -> None:
        (tmp_path / "chat.eml").write_text(self.CHATLOG_EML)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert rec.specialist_metadata is not None
        assert "email" in rec.specialist_metadata
        assert "body_chatlog" in rec.specialist_metadata["email"]
        body_chatlog = rec.specialist_metadata["email"]["body_chatlog"]
        assert body_chatlog["turn_count"] >= 3

    def test_body_chatlog_absent_on_plain_email(self, tmp_path: Path) -> None:
        (tmp_path / "plain.eml").write_text(self.PLAIN_EML)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        if rec.specialist_metadata and "email" in rec.specialist_metadata:
            assert "body_chatlog" not in rec.specialist_metadata["email"]

    def test_is_chatlog_stays_false_on_email(self, tmp_path: Path) -> None:
        """Per spec §4.1: is_chatlog stays false — file is binary, only body was tested."""
        (tmp_path / "chat.eml").write_text(self.CHATLOG_EML)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert rec.is_chatlog is False

    def test_body_chatlog_provenance(self, tmp_path: Path) -> None:
        (tmp_path / "chat.eml").write_text(self.CHATLOG_EML)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        rec = manifest.files[0]
        assert "specialist_metadata.email.body_chatlog" in rec.signal_provenance

    def test_body_chatlog_counted_in_chatlog_vector(self, tmp_path: Path) -> None:
        """Email body chatlog hits contribute to the chatlog vector's applied_to_count."""
        (tmp_path / "chat.eml").write_text(self.CHATLOG_EML)
        config = ScannerConfig(enable_specialists=True)
        manifest = Scanner(source_dir=tmp_path, config=config).scan()
        chatlog_vec = [v for v in manifest.vectors_collected if v["vector_id"] == "chatlog"][0]
        assert chatlog_vec["applied_to_count"] >= 1
        assert chatlog_vec["summary"]["total_turns"] >= 3


class TestPerDirectorySummary:
    """Test per-directory aggregation in ScanQuality (spec §4.2)."""

    def test_per_directory_summary_present(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        assert hasattr(manifest.quality, "per_directory_summary")
        assert isinstance(manifest.quality.per_directory_summary, list)

    def test_files_at_root_use_empty_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        dirs = [d["directory"] for d in manifest.quality.per_directory_summary]
        assert "" in dirs

    def test_subdirectory_aggregation(self, tmp_path: Path) -> None:
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        (tmp_path / "alpha" / "a.txt").write_text("hello")
        (tmp_path / "alpha" / "b.txt").write_text("world")
        (tmp_path / "beta" / "c.txt").write_text("test")
        manifest = Scanner(source_dir=tmp_path).scan()
        summary = {d["directory"]: d for d in manifest.quality.per_directory_summary}
        assert "alpha" in summary
        assert "beta" in summary
        assert summary["alpha"]["total_files"] == 2
        assert summary["beta"]["total_files"] == 1

    def test_sorted_alphabetically(self, tmp_path: Path) -> None:
        (tmp_path / "zebra").mkdir()
        (tmp_path / "alpha").mkdir()
        (tmp_path / "zebra" / "z.txt").write_text("z")
        (tmp_path / "alpha" / "a.txt").write_text("a")
        manifest = Scanner(source_dir=tmp_path).scan()
        dirs = [d["directory"] for d in manifest.quality.per_directory_summary]
        assert dirs == sorted(dirs)

    def test_chatlog_files_counted_per_directory(self, tmp_path: Path) -> None:
        chatlog_text = "User: hi\nAssistant: hello\nUser: bye\nAssistant: see ya\nUser: thanks\nAssistant: np\n"
        (tmp_path / "logs").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "logs" / "chat.txt").write_text(chatlog_text)
        (tmp_path / "docs" / "readme.txt").write_text("no chatlog here")
        manifest = Scanner(source_dir=tmp_path).scan()
        summary = {d["directory"]: d for d in manifest.quality.per_directory_summary}
        assert summary["logs"]["chatlog_files"] == 1
        assert summary["docs"]["chatlog_files"] == 0

    def test_per_directory_in_json_output(self, tmp_path: Path) -> None:
        import json
        from scanner.scanner import manifest_to_json
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.txt").write_text("hello")
        manifest = Scanner(source_dir=tmp_path).scan()
        data = json.loads(manifest_to_json(manifest))
        assert "per_directory_summary" in data["quality"]
