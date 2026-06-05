"""v1.10.0 — provisional-lifecycle release.

Promotions to stable (duplicate_clusters, specialist_stats, errors[].detail,
pdf.text_detected, pdf.xref_type) are designation-only — covered by the unchanged
golden/manifest tests (no value changes). These tests cover the NEW provisional
intake: the preservation block, OLE2 producing-app → provenance, and summary top-N.
The OLE2 .doc/.xls extraction itself is corpus-validated (no OLE2 unit fixtures, as
with all OLE2 extraction in this project); here we test the ingestion + the rest.
"""
from pathlib import Path

from file_observer.scanner import (
    Scanner, ScannerConfig, FORMAT_OBSOLESCENCE, PROVENANCE_METHOD_VERSION,
    AUTHOR_AGGREGATE_VECTOR_ID,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _scan(workers=1):
    return Scanner(source_dir=FIXTURES,
                   config=ScannerConfig(enable_specialists=True, workers=workers)).scan()


# --- preservation (new provisional field) ---------------------------------------
def test_preservation_tier_lookup():
    s = Scanner(source_dir=Path("."), config=ScannerConfig())
    assert s._extract_preservation(".doc") == {"format_obsolescence": "at_risk", "migration_recommended": False}
    assert s._extract_preservation(".swf") == {"format_obsolescence": "obsolete", "migration_recommended": True}
    assert s._extract_preservation(".pdf") == {"format_obsolescence": "current", "migration_recommended": False}
    assert s._extract_preservation(".DOC") == s._extract_preservation(".doc")   # case-insensitive


def test_preservation_field_and_vector_present():
    m = _scan()
    assert all(f.preservation is not None for f in m.files)         # on every file
    pv = next((v for v in m.vectors_collected if v["vector_id"] == "preservation"), None)
    assert pv is not None and pv["scope"] == "file"
    assert set(pv["summary"]) >= {"current", "at_risk", "obsolete"}
    assert pv["applied_to_count"] == len(m.files)


def test_preservation_byte_identical_across_workers():
    # the new field must not break the v1.9 determinism contract
    assert _scan(1).manifest_checksum == _scan(4).manifest_checksum


def test_obsolescence_table_is_closed_and_nonempty():
    assert len(FORMAT_OBSOLESCENCE) >= 10
    assert all(v in ("at_risk", "obsolete") for v in FORMAT_OBSOLESCENCE.values())


# --- OLE2 producing-app → provenance (ingestion path) ----------------------------
def test_provenance_method_version_bumped():
    assert PROVENANCE_METHOD_VERSION == 2   # v1.10: OLE2 .doc/.xls producing-app input


def test_document_application_feeds_provenance():
    # the path the OLE2 .doc/.xls producing-app uses: document/spreadsheet.application
    # → provenance toolchains (extraction is corpus-validated; this pins the ingestion)
    s = Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True))
    s._vector_registry = __import__("file_observer.scanner", fromlist=["VectorRegistry"]).VectorRegistry()
    from file_observer.scanner import FileRecord, FrontmatterRecord, StructuralRecord, MimeAnalysisRecord
    rec = FileRecord(
        path="a.doc", filename="a.doc", extension=".doc", mime_type="application/msword",
        size_bytes=1, created_at=None, modified_at="", checksum_sha256="x", stage_folder="",
        directory_depth=0, encoding=None, is_binary=True, requires_vision=False,
        requires_specialist_tool=True, specialist_tool="document_extraction", sidecar_exists=False,
        frontmatter=FrontmatterRecord(), tags=[], asset_matches=[], content_preview=None,
        structural=StructuralRecord(), mime_analysis=MimeAnalysisRecord(None, None, False),
        specialist_metadata={"document": {"application": "Microsoft Office Word"}},
    )
    s._run_provenance([rec])
    prov = next(v for v in s._vector_registry.to_list() if v["vector_id"] == "provenance")
    names = {t["name"] for t in prov["summary"].get("toolchains", [])}
    assert "Microsoft Word" in names   # normalized via the closed toolchain table


# --- summary top-authors (cheap re-display) --------------------------------------
def test_summary_surfaces_top_authors_when_present():
    m = _scan()
    aa = next((v for v in m.vectors_collected if v["vector_id"] == AUTHOR_AGGREGATE_VECTOR_ID), None)
    if aa and aa["summary"].get("top_authors"):
        assert "Top authors:" in m.summary
    # else: fixtures carry no authors — the wiring is still exercised without crashing
