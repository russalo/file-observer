"""v1.13 — `--schema` self-description capability (falsify-first).

`file-observer --schema` introspects the installed build's COMPLETE output
surface and emits it as a deterministic document (json or md). No scan, no
manifest — a separate surface. SCHEMA_VERSION (the manifest contract) and
LOGIC_VERSION are unchanged.

The load-bearing contract is COMPLETENESS: anything a real scan can emit MUST
appear in `--schema`. These tests cross-check the schema document against what
the training-fixtures corpora actually produce — "the corpus triggers X but
--schema omits X" is a hard failure. This is the test that would have caught
the v1.12.2 inline-error-code gap (a constants-read missing the inline literals).
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    PROVENANCE_TRIGGERS,
    SAFETY_FLAGS,
    ERROR_CODES,
    SPECIALIST_FIELDS,
    build_schema_document,
    schema_to_json,
    schema_to_markdown,
)

REPO = Path(__file__).resolve().parent.parent
SCANNER_PY = REPO / "src" / "file_observer" / "scanner.py"
FIXTURES = REPO / "tests" / "fixtures"


@pytest.fixture(scope="module")
def schema_doc():
    return build_schema_document()


@pytest.fixture(scope="module")
def fixtures_manifest():
    """A real scan of tests/fixtures with specialists on — the empirical
    trigger set the schema must cover."""
    cfg = ScannerConfig(enable_specialists=True)
    return Scanner(source_dir=FIXTURES, config=cfg).scan()


# ---------------------------------------------------------------------------
# Surface presence
# ---------------------------------------------------------------------------

class TestSchemaSurface:
    def test_top_level_sections_present(self, schema_doc):
        for key in ("manifest", "specialists", "vectors", "safety_flags",
                    "error_codes", "provenance_triggers", "format_signatures",
                    "preservation_tiers", "reference_tokens_subcategories",
                    "filename_patterns_subcategories", "mime_tiers"):
            assert key in schema_doc, f"--schema missing section: {key}"

    def test_versions_match_build(self, schema_doc):
        assert schema_doc["scanner_version"] == SCANNER_VERSION
        assert schema_doc["logic_version"] == LOGIC_VERSION
        assert schema_doc["schema_version"] == SCHEMA_VERSION

    def test_all_six_vectors_listed(self, schema_doc):
        ids = {v["vector_id"] for v in schema_doc["vectors"]}
        assert ids == {"chatlog", "reference_tokens", "filename_patterns",
                       "preservation", "author_aggregate", "provenance"}


# ---------------------------------------------------------------------------
# Completeness cross-checks against a real scan (the load-bearing contract)
# ---------------------------------------------------------------------------

class TestSchemaCompleteness:
    def test_every_emitted_error_code_is_in_schema(self, schema_doc, fixtures_manifest):
        """Every errors[].code a real scan produces MUST be in --schema. This is
        the test that would have caught the v1.12.2 inline-literal gap."""
        emitted = {e.code for f in fixtures_manifest.files for e in (f.errors or [])}
        listed = set(schema_doc["error_codes"])
        missing = emitted - listed
        assert not missing, f"error codes emitted by a scan but absent from --schema: {missing}"

    def test_every_emitted_safety_flag_is_in_schema(self, schema_doc, fixtures_manifest):
        emitted = {fl for f in fixtures_manifest.files for fl in (f.safety_flags or [])}
        listed = set(schema_doc["safety_flags"])
        missing = emitted - listed
        assert not missing, f"safety_flags emitted by a scan but absent from --schema: {missing}"

    def test_every_emitted_provenance_trigger_is_in_schema(self, schema_doc, fixtures_manifest):
        """Every signal_provenance trigger a real scan produces (including the
        dynamically-computed ones — bounded_sample, cascade_*, etc.) MUST be in
        the registry. This validates the dynamic triggers the AST guard can't see."""
        emitted = set()
        for f in fixtures_manifest.files:
            for entry in (f.signal_provenance or {}).values():
                trig = entry.get("trigger")
                if trig:
                    emitted.add(trig)
        listed = set(schema_doc["provenance_triggers"])
        missing = emitted - listed
        assert not missing, f"provenance triggers emitted by a scan but absent from --schema registry: {missing}"

    def test_every_emitted_specialist_field_is_in_schema(self, schema_doc, fixtures_manifest):
        """Every specialist-metadata field a real scan emits MUST be documented
        in SPECIALIST_FIELDS (no undocumented field)."""
        listed = schema_doc["specialists"]["fields"]
        offenders = []
        for f in fixtures_manifest.files:
            sm = f.specialist_metadata or {}
            for ns, fields in sm.items():
                if not isinstance(fields, dict):
                    continue
                known = set(listed.get(ns, []))
                for k in fields:
                    if k.startswith("_"):
                        continue  # transient markers, popped before serialization
                    if k not in known:
                        offenders.append(f"{ns}.{k}")
        assert not offenders, f"specialist fields emitted but absent from --schema: {sorted(set(offenders))}"


# ---------------------------------------------------------------------------
# Guard: no inline provenance-trigger literal escapes the registry (AST)
# ---------------------------------------------------------------------------

def test_every_literal_trigger_is_registered():
    """AST guard (mirrors the v1.12.2 error-code guard): every inline
    `trigger="literal"` value in a ProvenanceEntry(...) call MUST be a key in
    PROVENANCE_TRIGGERS. Dynamic (variable) trigger= values are validated by the
    corpus cross-check above. Together they guarantee the registry is complete.
    """
    def _literal_strings(node):
        """Yield every string-literal the expression can evaluate to. Handles a
        bare Constant AND a conditional expression `A if c else B` (both arms) —
        the v1.13 build had 3 triggers hiding in `else` arms that a Constant-only
        check missed (caught by the corpus cross-check; this guards the class)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.IfExp):
            yield from _literal_strings(node.body)
            yield from _literal_strings(node.orelse)

    tree = ast.parse(SCANNER_PY.read_text(encoding="utf-8"), filename=str(SCANNER_PY))
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ProvenanceEntry"):
            continue
        for kw in node.keywords:
            if kw.arg == "trigger":
                for val in _literal_strings(kw.value):
                    if val not in PROVENANCE_TRIGGERS:
                        offenders.append(f"{val!r} (line {kw.value.lineno})")
    assert not offenders, (
        f"inline trigger literal(s) not in PROVENANCE_TRIGGERS: {offenders} — "
        "every signal_provenance trigger must be registered (the --schema surface "
        "reads the registry)"
    )


# ---------------------------------------------------------------------------
# Determinism + the committed docs/SCHEMA.md drift guard
# ---------------------------------------------------------------------------

class TestSchemaDeterminismAndDoc:
    def test_schema_json_is_deterministic(self, schema_doc):
        a = schema_to_json(build_schema_document())
        b = schema_to_json(build_schema_document())
        assert a == b

    def test_committed_schema_md_matches_generated(self):
        """docs/SCHEMA.md MUST equal `--schema --format md` output, so it can't
        drift from the code. Regenerate it when the surface changes:
        `python -c "from file_observer.scanner import build_schema_document, schema_to_markdown; open('docs/SCHEMA.md','w').write(schema_to_markdown(build_schema_document())+chr(10))"`
        """
        committed = (REPO / "docs" / "SCHEMA.md").read_text(encoding="utf-8")
        generated = schema_to_markdown(build_schema_document()) + "\n"
        assert committed == generated, (
            "docs/SCHEMA.md is stale vs the code — regenerate it (see this test's docstring)"
        )


# ---------------------------------------------------------------------------
# CLI surface (subprocess — the real entrypoint path)
# ---------------------------------------------------------------------------

class TestSchemaCLI:
    def test_cli_schema_json_runs_without_scanning(self):
        r = subprocess.run(
            [sys.executable, "-m", "file_observer.scanner", "--schema"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert r.returncode == 0, r.stderr
        # stdout is valid JSON with the expected top-level keys
        doc = json.loads(r.stdout)
        assert doc["scanner_version"] == SCANNER_VERSION
        assert "provenance_triggers" in doc

    def test_cli_schema_md_runs(self):
        r = subprocess.run(
            [sys.executable, "-m", "file_observer.scanner", "--schema", "--schema-format", "md"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert r.returncode == 0, r.stderr
        assert r.stdout.startswith("# File Observer output schema")


# ---------------------------------------------------------------------------
# Version + frozen-contract
# ---------------------------------------------------------------------------

def test_version_is_1_13_0():
    assert SCANNER_VERSION == "1.13.0", f"got {SCANNER_VERSION!r}"


def test_logic_and_schema_frozen():
    """v1.13 is a new SEPARATE surface — the manifest contract is unchanged."""
    assert LOGIC_VERSION == "1.4.3", f"LOGIC drifted: {LOGIC_VERSION!r}"
    assert SCHEMA_VERSION == "1.8", f"SCHEMA drifted: {SCHEMA_VERSION!r}"
