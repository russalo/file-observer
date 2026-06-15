"""v1.15.1 — HEIC/HEIF/AVIF *recognition* (patch).

v1.15.0 detects HEIC/HEIF/AVIF (stops the video/mp4 mislabel) but they were still
flagged `unsupported_extension` and carried no `extension_mime`. v1.15.1 finishes the
recognition: register their extension MIMEs, add them to SUPPORTED_EXTENSIONS, and
split the brand→MIME mapping so generic HEIF brands (heif/mif1/msf1) report the honest
generic `image/heif` rather than asserting HEVC-coded `image/heic`. No extraction
(dimensions/EXIF stay in v1.16). Falsify-first.
"""
from __future__ import annotations

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig, SUPPORTED_EXTENSIONS,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)


def _ftyp(brand: bytes) -> bytes:
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00" + brand


def test_release_version_surfaces():
    assert SCANNER_VERSION == "1.15.1", f"got {SCANNER_VERSION!r}"
    assert LOGIC_VERSION == "1.5.1", f"LOGIC: {LOGIC_VERSION!r}"   # brand-label move + recognition
    assert SCHEMA_VERSION == "1.9", f"SCHEMA unchanged: {SCHEMA_VERSION!r}"


class TestBrandLabelPrecision:
    """heic/heix → image/heic (HEVC-coded); generic HEIF heif/mif1/msf1 → image/heif;
    avif/avis → image/avif. The generic brands no longer claim image/heic."""

    @pytest.fixture(scope="class")
    def scanner(self, tmp_path_factory):
        return Scanner(source_dir=tmp_path_factory.mktemp("v151"))

    @pytest.mark.parametrize("brand,expect", [
        (b"heic", "image/heic"),
        (b"heix", "image/heic"),
        (b"heif", "image/heif"),   # generic HEIF — was image/heic in v1.15.0
        (b"mif1", "image/heif"),   # generic HEIF still image
        (b"msf1", "image/heif"),   # HEIF image sequence
        (b"avif", "image/avif"),
        (b"avis", "image/avif"),
    ])
    def test_brand_mime(self, scanner, brand, expect):
        assert scanner._sniff_mime(_ftyp(brand)) == expect

    @pytest.mark.parametrize("brand", [b"heif", b"mif1", b"msf1"])
    def test_heif_not_a_false_polyglot(self, scanner, brand):
        # the generic ftyp→video/mp4 label must be superseded by image/heif too
        _sig, formats, is_polyglot = scanner.scan_signatures(_ftyp(brand))
        labels = {f["format"] for f in formats}
        assert "video/mp4" not in labels
        assert is_polyglot is False


class TestRecognizedAsSupported:
    """The extensions are first-class: in SUPPORTED_EXTENSIONS, with an extension_mime,
    NOT flagged unsupported_extension, and NOT routed to a (nonexistent) specialist."""

    def test_extensions_are_supported(self):
        assert {".heic", ".heif", ".avif"} <= SUPPORTED_EXTENSIONS

    @pytest.mark.parametrize("ext,brand,emime", [
        (".heic", b"heic", "image/heic"),
        (".heif", b"heif", "image/heif"),
        (".avif", b"avif", "image/avif"),
    ])
    def test_recognized_not_degraded(self, tmp_path, ext, brand, emime):
        (tmp_path / f"photo{ext}").write_bytes(_ftyp(brand) + b"\x00" * 64)
        rec = next(f for f in Scanner(source_dir=tmp_path).scan().files
                   if f.filename == f"photo{ext}")
        # not flagged unsupported (the v1.15.0 wart this patch removes)
        assert not any(e.code == "unsupported_extension" for e in rec.errors)
        assert rec.mime_analysis.extension_mime == emime
        # recognized but NOT extracted — no specialist for these yet
        assert rec.requires_specialist_tool is False

    def test_iphone_heic_matches_extension(self, tmp_path):
        # the common case: a .heic with the heic brand → content == extension → match
        (tmp_path / "IMG.heic").write_bytes(_ftyp(b"heic") + b"\x00" * 64)
        rec = next(f for f in Scanner(source_dir=tmp_path).scan().files if f.filename == "IMG.heic")
        assert rec.mime_analysis.matches_extension is True

    def test_generic_brand_heic_mismatches_extension(self, tmp_path):
        # DECISION (observe-don't-interpret): we report the MAJOR brand's type. A .heic
        # whose major brand is the generic `mif1` → detected image/heif vs extension
        # image/heic → matches_extension=False. This is an honest content-vs-extension
        # SIGNAL, not a bug — file-observer surfaces the divergence, never "fixes" it.
        # Deep compatible-brands analysis (would mif1+heic-compatible → image/heic?) is
        # v1.16 HEIC-specialist territory, not the fallback sniffer.
        (tmp_path / "IMG.heic").write_bytes(_ftyp(b"mif1") + b"\x00" * 64)
        rec = next(f for f in Scanner(source_dir=tmp_path).scan().files if f.filename == "IMG.heic")
        assert rec.mime_analysis.matches_extension is False
