"""v1.23 — promotion pass: `preservation` → stable (falsify-first).

Designation-only: the `preservation` vector + the per-FileRecord `preservation` field graduate
provisional → stable (settled since v1.10 + demonstrated evidence-of-value on the corpus — the
v1.14 hold resolved). The scan manifest is byte-identical except the version stamps (stability
lives only in `--schema`, the v1.14 pattern). format_signatures/is_polyglot STAY provisional
(held-by-design); the capture fields + chatlog family STAY provisional (not swept up).

SCHEMA 1.13→1.14 (promotion = contract change); LOGIC unchanged (1.12.1); SCANNER 1.22.1→1.23.0.
"""
from __future__ import annotations

from pathlib import Path

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    PROVISIONAL_VECTORS,
    PROVISIONAL_MANIFEST_FIELDS,
    build_schema_document,
    manifest_to_json,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def _schema():
    return build_schema_document()


def _vector_stability(doc, vid):
    return next(v["stability"] for v in doc["vectors"] if v["vector_id"] == vid)


def _filerecord_field_stability(doc, field):
    return {f["name"]: f["stability"] for f in doc["manifest"]["FileRecord"]}[field]


def test_version_surfaces():
    assert SCANNER_VERSION == "1.23.0", f"got {SCANNER_VERSION!r}"
    assert SCHEMA_VERSION == "1.14", f"SCHEMA: {SCHEMA_VERSION!r}"   # promotion = contract change
    assert LOGIC_VERSION == "1.12.1", f"LOGIC: {LOGIC_VERSION!r}"    # unchanged — designation-only


def test_preservation_promoted_to_stable():
    doc = _schema()
    assert _vector_stability(doc, "preservation") == "stable", "preservation VECTOR must be stable"
    assert _filerecord_field_stability(doc, "preservation") == "stable", "FileRecord.preservation must be stable"


def test_preservation_out_of_provisional_registries():
    assert "preservation" not in PROVISIONAL_VECTORS
    assert ("FileRecord", "preservation") not in PROVISIONAL_MANIFEST_FIELDS


def test_held_by_design_fields_stay_provisional():
    # format_signatures / is_polyglot are permanently-informational — NOT swept into the promotion
    doc = _schema()
    assert _filerecord_field_stability(doc, "format_signatures") == "provisional"
    assert _filerecord_field_stability(doc, "is_polyglot") == "provisional"
    assert ("FileRecord", "format_signatures") in PROVISIONAL_MANIFEST_FIELDS
    assert ("FileRecord", "is_polyglot") in PROVISIONAL_MANIFEST_FIELDS


def test_capture_fields_stay_provisional():
    # the promotion must not sweep up the days-old capture fields (season first)
    doc = _schema()
    img = {f["name"]: f["stability"] for f in doc["specialists"]["fields"]["image"]}
    vid = {f["name"]: f["stability"] for f in doc["specialists"]["fields"]["video"]}
    assert img["gps_present"] == "provisional" and img["make"] == "provisional"
    assert vid["creation_date_qt"] == "provisional" and vid["codec"] == "provisional"


class TestDesignationOnly:
    def _manifest(self):
        return Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True)).scan()

    def test_stability_does_not_leak_into_manifest(self):
        blob = manifest_to_json(self._manifest())
        assert '"stability"' not in blob, "stability is a --schema-only surface, not the manifest"

    def test_preservation_values_still_produced(self):
        m = self._manifest()
        # every FileRecord still carries the preservation signal, shape unchanged
        for r in m.files:
            assert r.preservation is not None
            assert r.preservation.get("format_obsolescence") in ("current", "at_risk", "obsolete")
            assert isinstance(r.preservation.get("migration_recommended"), bool)

    def test_manifest_deterministic(self):
        a = Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True)).scan()
        b = Scanner(source_dir=FIXTURES, config=ScannerConfig(enable_specialists=True)).scan()
        assert a.manifest_checksum == b.manifest_checksum
