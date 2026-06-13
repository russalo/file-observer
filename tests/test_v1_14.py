"""v1.14 — promotion pass + `--schema` stability annotation (falsify-first).

v1.14 promotes three settled provisional fields to STABLE — `pdf.parser`,
`{document,spreadsheet}.application`, and the `provenance` vector — and surfaces
each enumerated surface element's `stability` in `--schema` (closing the v1.13
§3.3 deferral). It is a DESIGNATION change: the manifest scan output is byte-
identical except the version stamps; `LOGIC_VERSION` is frozen.

The falsifiable contracts here:
  - the promotion didn't change scan output (designation-only): the manifest
    carries NO `stability` key — stability lives only in `--schema`;
  - `--schema` marks the promoted three stable and the held set provisional;
  - the provisional registry can't silently drift from PUBLIC_CONTRACT §2.4;
  - every enumerated surface element carries a stability label.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    PROVISIONAL_SPECIALIST_FIELDS,
    PROVISIONAL_VECTORS,
    PROVISIONAL_MANIFEST_FIELDS,
    build_schema_document,
    manifest_to_json,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


@pytest.fixture(scope="module")
def schema_doc():
    return build_schema_document()


def test_release_version_surfaces():
    assert SCANNER_VERSION == "1.14.0", f"got {SCANNER_VERSION!r}"
    assert SCHEMA_VERSION == "1.9", f"SCHEMA: {SCHEMA_VERSION!r}"   # promotion = contract designation change
    assert LOGIC_VERSION == "1.4.3", f"LOGIC must stay frozen: {LOGIC_VERSION!r}"


# --- the promotion is visible in --schema, the held set stays provisional ---

def _field_stability(doc, ns, field):
    return next(f["stability"] for f in doc["specialists"]["fields"][ns] if f["name"] == field)


def _vector_stability(doc, vid):
    return next(v["stability"] for v in doc["vectors"] if v["vector_id"] == vid)


class TestStabilityAnnotation:
    def test_promoted_fields_are_stable(self, schema_doc):
        assert _field_stability(schema_doc, "pdf", "parser") == "stable"
        assert _field_stability(schema_doc, "document", "application") == "stable"
        assert _field_stability(schema_doc, "spreadsheet", "application") == "stable"
        assert _vector_stability(schema_doc, "provenance") == "stable"

    def test_held_fields_are_provisional(self, schema_doc):
        for f in ("content_shape", "speaker_turn_counts", "speaker_turn_chars", "alternation"):
            assert _field_stability(schema_doc, "chatlog", f) == "provisional", f
        assert _vector_stability(schema_doc, "preservation") == "provisional"
        # preservation is also a FileRecord field
        fr = {x["name"]: x["stability"] for x in schema_doc["manifest"]["FileRecord"]}
        assert fr["preservation"] == "provisional"

    def test_every_schema_element_has_a_stability_label(self, schema_doc):
        valid = {"stable", "provisional"}
        for ns, fields in schema_doc["specialists"]["fields"].items():
            for f in fields:
                assert f.get("stability") in valid, f"{ns}.{f['name']}"
        for v in schema_doc["vectors"]:
            assert v.get("stability") in valid, v["vector_id"]
        for cls, fields in schema_doc["manifest"].items():
            for f in fields:
                assert f.get("stability") in valid, f"{cls}.{f['name']}"


class TestProvisionalRegistryMatchesContract:
    """Guard: the provisional registry must equal the documented provisional
    surface (PUBLIC_CONTRACT §2.4). A promotion/demotion that edits one without
    the other fails here — same drift-guard discipline as the v1.13 registries."""

    def test_provisional_set_is_exactly_the_documented_set(self):
        assert PROVISIONAL_SPECIALIST_FIELDS == frozenset({
            ("chatlog", "content_shape"),
            ("chatlog", "speaker_turn_counts"),
            ("chatlog", "speaker_turn_chars"),
            ("chatlog", "alternation"),
        })
        assert PROVISIONAL_VECTORS == frozenset({"preservation"})
        assert PROVISIONAL_MANIFEST_FIELDS == frozenset({
            ("FileRecord", "preservation"),
            ("FileRecord", "format_signatures"),  # §2.4 internal field set
            ("FileRecord", "is_polyglot"),         # §2.4 internal field set
        })


class TestPromotionIsDesignationOnly:
    """Promotion changes the stability promise, not scan output."""

    @pytest.fixture(scope="class")
    def manifest(self):
        cfg = ScannerConfig(enable_specialists=True)
        return Scanner(source_dir=FIXTURES, config=cfg).scan()

    def test_promoted_fields_keep_their_shape(self, manifest):
        saw_parser = saw_app = saw_provenance = False
        for f in manifest.files:
            pm = (f.specialist_metadata or {}).get("pdf")
            if pm and "parser" in pm:
                assert pm["parser"] in ("pypdf", "stdlib", "none", None)
                saw_parser = True
            for ns in ("document", "spreadsheet"):
                nm = (f.specialist_metadata or {}).get(ns)
                if nm and "application" in nm:
                    assert nm["application"] is None or isinstance(nm["application"], str)
                    saw_app = True
        if any(v.get("vector_id") == "provenance" for v in manifest.vectors_collected):
            saw_provenance = True
        # fixtures include PDFs + a docx/xlsx, so at least parser is exercised
        assert saw_parser, "no PDF in fixtures exercised pdf.parser"
        assert saw_app, "no docx/xlsx in fixtures exercised application"
        assert saw_provenance, "provenance vector not present on the fixtures scan"

    def test_stability_does_not_leak_into_the_manifest(self, manifest):
        """The stability annotation is a `--schema`-only surface — it must NOT
        appear in the scan manifest (proves the promotion is designation-only)."""
        blob = manifest_to_json(manifest)
        assert '"stability"' not in blob

    def test_manifest_is_deterministic(self):
        cfg = ScannerConfig(enable_specialists=True)
        a = Scanner(source_dir=FIXTURES, config=cfg).scan()
        b = Scanner(source_dir=FIXTURES, config=cfg).scan()
        assert a.manifest_checksum == b.manifest_checksum
