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
    # v1.14 floor — the exact current-version pin lives in the newest release test
    # (test_v1_15). Older release tests assert floors so a later bump doesn't break them.
    def _v(s): return tuple(int(p) for p in s.split("."))
    assert _v(SCANNER_VERSION) >= (1, 14, 0), f"SCANNER regressed below v1.14: {SCANNER_VERSION!r}"
    assert _v(SCHEMA_VERSION) >= (1, 9), f"SCHEMA regressed below 1.9: {SCHEMA_VERSION!r}"   # promotion landed in 1.9
    assert _v(LOGIC_VERSION) >= (1, 4, 3), f"LOGIC regressed below 1.4.3: {LOGIC_VERSION!r}"


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
        # preservation was PROMOTED to stable in v1.23.0 (see test_v1_23) — the chatlog family stays held.
        assert _vector_stability(schema_doc, "preservation") == "stable"
        fr = {x["name"]: x["stability"] for x in schema_doc["manifest"]["FileRecord"]}
        assert fr["preservation"] == "stable"
        # format_signatures/is_polyglot stay provisional (held-by-design, §2.4 — vocabulary stays fluid)
        assert fr["format_signatures"] == "provisional" and fr["is_polyglot"] == "provisional"

    def test_capture_metadata_fields_promoted_stable_v1_31(self, schema_doc):
        # v1.31.0 promotion pass: the v1.16 image-EXIF fields + the whole v1.17–1.20
        # video namespace were promoted provisional→stable (see test_v1_31). This guard
        # tracks the now-current reality so test_v1_14 doesn't lag the contract.
        for f in ("make", "model", "orientation", "datetime_original", "gps_present", "xmp_present"):
            assert _field_stability(schema_doc, "image", f) == "stable", f"image.{f}"
        for f in ("codec", "duration_s", "width", "height", "creation_date",
                  "creation_date_qt", "make", "model", "gps_present", "gps_source"):
            assert _field_stability(schema_doc, "video", f) == "stable", f"video.{f}"
        # the OLD image dimensions were already stable (since 0.5)
        for f in ("width", "height", "bit_depth"):
            assert _field_stability(schema_doc, "image", f) == "stable", f"image.{f}"

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
            # v1.31.0 promotion pass: image-EXIF (v1.16) + the whole video namespace
            # (v1.17–1.20) were PROMOTED provisional→stable → no longer here (see test_v1_31).
            # v1.24 (Candidate B): new presentation namespace — provisional on arrival (held: too young)
            ("presentation", "slide_count"), ("presentation", "title"),
            ("presentation", "author"), ("presentation", "application"),
            # v1.25 (Candidate B ph.2): new audio namespace — provisional on arrival
            ("audio", "format"), ("audio", "bitrate"), ("audio", "duration_s"),
            ("audio", "title"), ("audio", "artist"), ("audio", "album"), ("audio", "year"),
            # v1.32 (FR #114): new fact_block namespace — provisional on arrival
            ("fact_block", "pair_count"), ("fact_block", "pairs"), ("fact_block", "duplicate_keys"),
            # v1.33: the new ai_session namespace — provisional on arrival.
            ("ai_session", "vendor"), ("ai_session", "surface"), ("ai_session", "models"),
            ("ai_session", "id_prefix"), ("ai_session", "object_types"), ("ai_session", "schema_mismatch"),
            ("ai_session", "usage"),
        })
        assert PROVISIONAL_VECTORS == frozenset()  # v1.23.0 promoted `preservation` (was the only one)
        assert PROVISIONAL_MANIFEST_FIELDS == frozenset({
            # v1.23.0 promoted ("FileRecord","preservation") → stable; the two below are held-by-DESIGN
            # (§2.4, permanently-informational — the signature vocabulary intentionally stays fluid).
            ("FileRecord", "format_signatures"),
            ("FileRecord", "is_polyglot"),
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
