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
                known = {x["name"] for x in listed.get(ns, [])}  # v1.14: fields are {name, stability}
                for k in fields:
                    if k.startswith("_"):
                        continue  # transient markers, popped before serialization
                    if k not in known:
                        offenders.append(f"{ns}.{k}")
        assert not offenders, f"specialist fields emitted but absent from --schema: {sorted(set(offenders))}"

    def test_email_body_chatlog_crosscut_field_is_in_schema(self, schema_doc, tmp_path):
        """v1.13 leg-1 #4: the email cross-cut emits specialist_metadata.email.
        body_chatlog when an email body is chatlog-shaped — a real serialized
        field that no fixture exercised (the only non-empty .eml has a non-chatlog
        body), so the generic field-completeness test passed blind. Drive the
        cross-cut explicitly and assert body_chatlog is BOTH emitted AND in
        SPECIALIST_FIELDS['email']."""
        body = (
            "Alice: hey, did you finish the report?\n"
            "Bob: yes, sent it this morning. did you get a chance to review?\n"
            "Alice: looking at it now, the numbers look good to me.\n"
            "Bob: great, let me know if anything needs changing before we ship.\n"
            "Alice: will do, thanks for turning it around so fast.\n"
        )
        eml = (
            "From: alice@example.com\n"
            "To: bob@example.com\n"
            "Subject: report\n"
            "Date: Mon, 1 Jan 2026 09:00:00 +0000\n"
            "Message-ID: <crosscut-test@example.com>\n"
            "\n" + body
        )
        p = tmp_path / "chatlog_body.eml"
        p.write_text(eml, encoding="utf-8")
        cfg = ScannerConfig(enable_specialists=True)
        m = Scanner(source_dir=tmp_path, config=cfg).scan()
        rec = next((r for r in m.files if r.path == p.name), None)
        assert rec is not None
        email_md = (rec.specialist_metadata or {}).get("email") or {}
        assert "body_chatlog" in email_md, (
            f"email body cross-cut did not emit body_chatlog; email keys: {sorted(email_md)}"
        )
        # And it must be documented in the schema (the whole point of #4)
        assert "body_chatlog" in {x["name"] for x in schema_doc["specialists"]["fields"]["email"]}


# ---------------------------------------------------------------------------
# Guard: no inline provenance-trigger literal escapes the registry (AST)
# ---------------------------------------------------------------------------

# The triggers that are computed dynamically (a variable or f-string passed to
# `trigger=`) — the AST guard CANNOT statically resolve these, so they are
# enumerated here and validated by test_dynamic_triggers_are_emittable (which
# drives the code paths that produce them). v1.13 leg-1 #8/#12: the original
# guard claimed the corpus cross-check covered these, but the corpus only
# emitted cascade_utf_8 — the other cascade arms + replace were validated by
# NEITHER guard. This explicit list + its driver test closes that gap.
DYNAMIC_TRIGGERS = {
    "bounded_sample", "bounded_deviation", "missing_from_bounds",  # specialist metadata loop
    "cascade_utf_8", "cascade_utf_8_sig", "cascade_cp1252", "cascade_latin_1",  # decode_text f-string
}


def _provenance_trigger_arg(call: ast.Call):
    """The AST node for a ProvenanceEntry call's `trigger` argument — keyword
    OR positional. ProvenanceEntry(layer, method, trigger, ...) so trigger is
    positional index 2 (v1.13 leg-4 Gemini: guards must catch positional form
    too, not only keyword). Returns the node or None."""
    for kw in call.keywords:
        if kw.arg == "trigger":
            return kw.value
    if len(call.args) >= 3:
        return call.args[2]
    return None


def test_registry_method_matches_emitted_method():
    """v1.13 leg-4 Gemini HIGH: --schema advertises the `method` for each
    provenance trigger; that method MUST match what the ProvenanceEntry call
    actually emits (else the self-description lies — e.g. registry said
    'structural.title' but the manifest carries 'extract_md_title'). For every
    statically-resolvable trigger literal, assert registry method == emitted
    method. Multi-method triggers (not_applicable) and dynamic per-extension
    methods (`_<ext>_specialist`) are allowed their documented placeholder."""
    tree = ast.parse(SCANNER_PY.read_text(encoding="utf-8"), filename=str(SCANNER_PY))

    def _lits(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.IfExp):
            return _lits(node.body) + _lits(node.orelse)
        return []

    from collections import defaultdict
    emitted = defaultdict(set)  # trigger -> set of method strings
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "ProvenanceEntry"):
            continue
        # method arg: keyword or positional idx 1
        m_node = None
        for kw in node.keywords:
            if kw.arg == "method":
                m_node = kw.value
        if m_node is None and len(node.args) >= 2:
            m_node = node.args[1]
        method = (m_node.value if isinstance(m_node, ast.Constant)
                  else "<dynamic>" if isinstance(m_node, ast.JoinedStr) else "<expr>")
        t_node = _provenance_trigger_arg(node)
        if t_node is None:
            continue
        for t in _lits(t_node):
            emitted[t].add(method)

    ALLOW_PLACEHOLDER = {"_<ext>_specialist", "(various)"}
    mismatches = []
    for trig, ms in emitted.items():
        reg_m = PROVENANCE_TRIGGERS.get(trig, {}).get("method")
        if reg_m in ALLOW_PLACEHOLDER:
            continue  # documented multi/dynamic-method placeholder
        if reg_m not in ms:
            mismatches.append(f"{trig}: registry={reg_m!r} emitted={sorted(ms)}")
    assert not mismatches, (
        "PROVENANCE_TRIGGERS method names disagree with the emitted ProvenanceEntry "
        f"method= values (--schema would advertise wrong methods): {mismatches}"
    )


def test_every_literal_trigger_is_registered():
    """AST guard (mirrors the v1.12.2 error-code guard): every STATICALLY
    RESOLVABLE inline trigger value in a ProvenanceEntry(...) call MUST be a key
    in PROVENANCE_TRIGGERS. Resolves bare Constants AND conditional expressions
    `A if c else B` (both arms — the v1.13 build had 3 triggers in else-arms).

    Dynamically-computed trigger= args (a Name or f-string) CANNOT be resolved
    statically; this test asserts they are accounted for in DYNAMIC_TRIGGERS
    (and test_dynamic_triggers_are_emittable proves each is registered + real).
    It does NOT silently skip them — an unrecognised dynamic trigger= site fails
    (v1.13 leg-1 #8/#12: no false-confidence skip)."""
    def _literal_strings(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value], True   # (values, fully_resolved)
        if isinstance(node, ast.IfExp):
            a, ra = _literal_strings(node.body)
            b, rb = _literal_strings(node.orelse)
            return a + b, (ra and rb)
        return [], False   # Name / JoinedStr (f-string) / anything else: unresolved

    tree = ast.parse(SCANNER_PY.read_text(encoding="utf-8"), filename=str(SCANNER_PY))
    offenders = []
    unresolved_sites = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ProvenanceEntry"):
            continue
        trigger_node = _provenance_trigger_arg(node)  # keyword OR positional (idx 2)
        if trigger_node is None:
            continue
        vals, resolved = _literal_strings(trigger_node)
        for val in vals:
            if val not in PROVENANCE_TRIGGERS:
                offenders.append(f"{val!r} (line {trigger_node.lineno})")
        if not resolved:
            # A dynamic trigger= site. The values it can produce MUST be in
            # DYNAMIC_TRIGGERS (verified emittable by the driver test).
            unresolved_sites += 1
    assert not offenders, (
        f"inline trigger literal(s) not in PROVENANCE_TRIGGERS: {offenders}"
    )
    # There are exactly 2 dynamic trigger= sites (specialist metadata loop +
    # decode_text cascade). If a third appears, DYNAMIC_TRIGGERS must be revisited.
    assert unresolved_sites == 2, (
        f"expected 2 dynamic trigger= sites (specialist loop, decode cascade); "
        f"found {unresolved_sites}. A new dynamic site needs its producible "
        f"values added to DYNAMIC_TRIGGERS + the driver test."
    )


def test_dynamic_triggers_are_emittable():
    """v1.13 leg-1 #8: the dynamically-computed triggers (cascade_*, bounded_*,
    missing_from_bounds) are validated by NEITHER the AST guard (can't resolve
    them) NOR the fixtures corpus (which only happens to emit cascade_utf_8).
    Drive each path explicitly so every DYNAMIC_TRIGGER is both registered AND
    real. (a) Every DYNAMIC_TRIGGER is a registry key. (b) decode_text emits the
    correct cascade_* trigger for a file whose bytes decode only at that step."""
    # (a) all registered
    missing = DYNAMIC_TRIGGERS - set(PROVENANCE_TRIGGERS)
    assert not missing, f"DYNAMIC_TRIGGERS not in registry: {missing}"

    # (b) drive decode_text through each cascade step. Construct byte payloads
    # that fail chardet-confidence + earlier cascade steps and succeed at the
    # target. We assert via the provenance trigger the scanner records.
    import tempfile
    scanner = Scanner(source_dir=Path("."), config=ScannerConfig())
    cases = {
        # cp1252-only bytes: 0x93/0x94 are smart quotes in cp1252, invalid utf-8
        b"cp1252 smart quotes: \x93hello\x94 " * 20: "cascade_cp1252",
        # utf-8-sig: BOM prefix
        b"\xef\xbb\xbfutf8 sig content here " * 20: "cascade_utf_8_sig",
    }
    seen_triggers = set()
    with tempfile.TemporaryDirectory() as td:
        for payload, _expected in cases.items():
            p = Path(td) / "f.txt"
            p.write_bytes(payload)
            # decode_text(sample, path): sample feeds chardet, path is read for content
            _enc, _text, prov = scanner.decode_text(payload, p)
            seen_triggers.add(prov.trigger)
    # We exercised at least the cp1252 + utf-8-sig cascade arms; each emitted
    # trigger must be registered (and is a cascade_* by construction).
    for t in seen_triggers:
        assert t in PROVENANCE_TRIGGERS, f"decode_text emitted unregistered trigger {t!r}"
    assert seen_triggers & {"cascade_cp1252", "cascade_utf_8_sig"}, (
        f"expected to exercise a cascade arm; got {seen_triggers}"
    )


def test_registry_has_no_phantom_keys():
    """v1.13 leg-1 #9: the guards assert emitted ⊆ registry but never registry ⊆
    emittable, so a phantom/stale/renamed key in a registry passes every check
    and is advertised by --schema as contract surface. This reverse guard asserts
    every PROVENANCE_TRIGGERS key is reachable: it appears as a statically-
    resolvable literal in a ProvenanceEntry trigger= arm OR is a known dynamic
    trigger. (Best-effort: a trigger only reachable via a path no corpus exercises
    would still need the literal in source, which this catches.)"""
    tree = ast.parse(SCANNER_PY.read_text(encoding="utf-8"), filename=str(SCANNER_PY))
    literal_triggers = set()

    def _collect(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literal_triggers.add(node.value)
        elif isinstance(node, ast.IfExp):
            _collect(node.body)
            _collect(node.orelse)

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "ProvenanceEntry"):
            t_node = _provenance_trigger_arg(node)  # keyword OR positional
            if t_node is not None:
                _collect(t_node)

    reachable = literal_triggers | DYNAMIC_TRIGGERS
    phantom = set(PROVENANCE_TRIGGERS) - reachable
    assert not phantom, (
        f"phantom PROVENANCE_TRIGGERS keys (in the registry / advertised by "
        f"--schema, but no ProvenanceEntry emits them): {sorted(phantom)} — "
        "remove the stale key or wire the emit site"
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

    def test_cli_schema_rejects_source_dir(self, tmp_path):
        """v1.13 leg-1 #1: --schema does not scan — a source dir passed alongside
        it MUST be rejected (exit 2), not silently discarded."""
        r = subprocess.run(
            [sys.executable, "-m", "file_observer.scanner", "--schema", str(tmp_path)],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert r.returncode == 2, f"expected exit 2, got {r.returncode}: {r.stdout[:200]}"
        assert "does not scan" in r.stderr

    def test_cli_schema_rejects_watch(self):
        """v1.13 leg-1 #6: --schema + --watch must reject (exit 2), symmetric with
        --watch's own incompatibility checks — not silently print schema + ignore."""
        r = subprocess.run(
            [sys.executable, "-m", "file_observer.scanner", "--schema", "--watch"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        assert r.returncode == 2, f"expected exit 2, got {r.returncode}"
        assert "--watch" in r.stderr


# ---------------------------------------------------------------------------
# Version + frozen-contract
# ---------------------------------------------------------------------------

def _ver_tuple(v):
    return tuple(int(p) for p in v.split("."))


def test_version_is_at_least_1_13_0():
    # Floor, not exact pin — v1.13 shipped --schema; later minors (v1.14 promotion
    # pass, …) bump the version and shouldn't break this v1.13 marker.
    assert _ver_tuple(SCANNER_VERSION) >= (1, 13, 0), f"got {SCANNER_VERSION!r}"


def test_logic_frozen_schema_only_grows():
    """v1.13 added a SEPARATE surface (--schema) — the manifest LOGIC contract is
    unchanged. LOGIC stays frozen; SCHEMA only ever goes up (v1.14 promotion pass
    bumped it 1.8→1.9)."""
    assert LOGIC_VERSION == "1.4.3", f"LOGIC drifted: {LOGIC_VERSION!r}"
    assert _ver_tuple(SCHEMA_VERSION) >= (1, 8), f"SCHEMA regressed: {SCHEMA_VERSION!r}"
