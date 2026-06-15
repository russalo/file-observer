"""Coverage for format paths that previously had NO fixtures — HEIF/AVIF brand
detection + recognition, and the OLE2 `.doc`/`.xls` specialists.

Fixtures are self-generated + spec-accurate (see tests/fixtures/generated/README.md);
they exercise exactly what the scanner reads (the `ftyp` brand / OLE2
SummaryInformation), without redistributing unclear-license third-party files.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig, SUPPORTED_EXTENSIONS, olefile,
)

GEN = Path(__file__).parent / "fixtures" / "generated"


@pytest.fixture(scope="module")
def manifest():
    return Scanner(source_dir=GEN, config=ScannerConfig(enable_specialists=True)).scan()


def _rec(manifest, name):
    return next(f for f in manifest.files if f.filename == name)


class TestHeifAvifFixtures:
    """Real-structure HEIF/AVIF files (ftyp brand) are detected + recognized."""

    @pytest.mark.parametrize("name,family", [
        ("image_heic.heic", "image/heic"),     # heic major → exact
        ("image_avif.avif", "image/avif"),     # avif major → exact
        ("heif_mif1_heic.heic", "image/heif"), # generic HEIF family
        ("heif_msf1_seq.heic", "image/heif"),  # libmagic may say image/heif-sequence
    ])
    def test_detected_as_image_family(self, manifest, name, family):
        rec = _rec(manifest, name)
        assert rec.mime_type.startswith(family), f"{name}: {rec.mime_type!r}"

    @pytest.mark.parametrize("name", [
        "image_heic.heic", "image_avif.avif", "heif_mif1_heic.heic", "heif_msf1_seq.heic"])
    def test_recognized_not_degraded(self, manifest, name):
        rec = _rec(manifest, name)
        ext = Path(name).suffix
        assert ext in SUPPORTED_EXTENSIONS                      # v1.15.1 recognition
        assert not any(e.code == "unsupported_extension" for e in rec.errors)
        assert rec.requires_specialist_tool is False           # no specialist yet (v1.16)
        assert rec.is_polyglot is False                        # ftyp-superseding holds
        assert not rec.errors or all(e.code != "universal_read_failed" for e in rec.errors)

    def test_no_crashes(self, manifest):
        assert all(f.path for f in manifest.files)             # every file produced a record


class TestXlsSpecialist:
    """Real BIFF8 .xls → spreadsheet_structure extracts sheets + format (full scan)."""

    def test_xls_extraction(self, manifest):
        rec = _rec(manifest, "generated.xls")
        assert rec.specialist_tool == "spreadsheet_structure"
        md = (rec.specialist_metadata or {}).get("spreadsheet", {})
        assert md.get("format") == "biff"
        assert md.get("sheet_names") == ["Summary", "Data"]


class TestDocSpecialist:
    """The minimal OLE2 .doc carries a SummaryInformation property stream; the
    specialist reads Title/Author from it. Tested at the extraction-method level:
    a minimal OLE2 (no WordDocument stream) is detected by libmagic as
    `application/vnd.ms-office`, which the full-scan MIME guard does not list for the
    document namespace — a real (minor) guard gap this fixture surfaced (candidate for
    a future patch). The extraction logic itself is exercised directly here."""

    @pytest.mark.skipif(olefile is None, reason="olefile not installed")
    def test_doc_summaryinformation_extraction(self):
        sc = Scanner(source_dir=GEN, config=ScannerConfig(enable_specialists=True))
        meta = sc._extract_doc_metadata(GEN / "generated.doc")
        assert meta is not None
        assert meta["author"] == "File Observer Test"
        assert meta["title"] == "File Observer Test Doc"
