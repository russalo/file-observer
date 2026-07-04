"""v1.32 — generic kv-fact-block specialist (FR #114), falsify-first.

A content-detected specialist: when a text file's BODY (frontmatter stripped) is dominated by
`key: value` lines, emit the observed pairs verbatim + generic (new provisional `fact_block`
namespace). The sentence-value veto keeps it off dialogue (the chatlog `Key:value` collision).
Measure-first in scratch/measure_kv_fact_block.py (db 497/497, prose 0/397, dialogue 0/60).

SCHEMA 1.17→1.18 (new namespace); LOGIC 1.15.3→1.16.0 (new content-detection routing);
SCANNER 1.31.0→1.32.0.
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
    build_schema_document,
    manifest_to_json,
    fact_block_rules_fingerprint,
)

FACT_BLOCK = """---
id: "edge-10"
title: "an edge"
---

id: 10
source: bestiary
target: puresniff
kind: oracle
status: active
summary: sniff extra
"""

PROSE = """---
id: "doc-1"
---

# A Document

This is a paragraph of ordinary prose. It has sentences, and the occasional
Note: something — but it is not a fact-block by any measure.

## A heading

More prose here, nothing structured.
"""

DIALOGUE = """Alice: I went to the store yesterday and bought some milk.
Bob: Did you remember the eggs we talked about?
Alice: Yes, I got a dozen of them from the back shelf.
Bob: Great, then we have everything we need for the recipe.
"""

FAQ = """Q: What is this?
A: It is a frequently asked questions document with answers.
Q: How does it work?
A: You read the question and then you read the answer below it.
"""

CHANGELOG = """Added: a new feature for exporting reports to disk
Fixed: a crash when the input file was empty on startup
Changed: the default timeout is now five seconds instead of ten
"""

# TERSE repeated-key lists — pass the veto (short values) but are NOT records of DISTINCT facts.
# The distinct-key gate (cross-model review) rejects them. (Note: a block of >=3 DISTINCT keys is a
# kv-block and DOES fire regardless of the author's semantic intent — observe-don't-interpret; the
# gate only rejects the degenerate repeated-key case, not every changelog.)
TERSE_CHANGELOG = "Added: export\nAdded: import\nAdded: sync\nFixed: crash\nFixed: leak\n"  # 2 distinct
TERSE_FAQ = "Q: install\nA: run make\nQ: usage\nA: read docs\n"  # 2 distinct (Q, A)
ID_REPEATED = "id: 1\nid: 2\nid: 3\nid: 4\n"  # 1 distinct

FRONTMATTER_ONLY = """---
id: "fm-1"
title: "frontmatter carries the pairs"
kind: thing
status: ok
---

# Just a heading and a line of prose, no body key:value block at all here.
"""


def _scan(tmp_path: Path, name: str, content: str, specialists=True):
    (tmp_path / name).write_text(content, encoding="utf-8")
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=specialists)).scan()
    return next(r for r in m.files if r.path.endswith(name)), m


def test_version_surfaces():
    assert tuple(map(int, SCANNER_VERSION.split("."))) >= (1, 32, 0), SCANNER_VERSION
    assert tuple(map(int, SCHEMA_VERSION.split("."))) >= (1, 18), SCHEMA_VERSION
    assert tuple(map(int, LOGIC_VERSION.split("."))) >= (1, 16, 0), LOGIC_VERSION


class TestFires:
    def test_fires_on_body_fact_block(self, tmp_path):
        rec, _ = _scan(tmp_path, "edge.md", FACT_BLOCK)
        assert rec.is_fact_block is True
        fb = rec.specialist_metadata["fact_block"]
        keys = [p["key"] for p in fb["pairs"]]
        # BODY pairs only (frontmatter id/title excluded — already extracted); first-occurrence order
        assert keys == ["id", "source", "target", "kind", "status", "summary"]
        assert fb["pairs"][1] == {"key": "source", "value": "bestiary"}
        assert fb["pair_count"] == 6 and fb["duplicate_keys"] == 0

    def test_pairs_are_verbatim_and_generic(self, tmp_path):
        # a totally different key vocabulary still emits verbatim — no schema, no validation
        content = "alpha: 1\nbeta-two: hello\ngamma_3: x.y.z\ndelta: value here ok\n"
        rec, _ = _scan(tmp_path, "generic.txt", content)
        assert rec.is_fact_block
        got = {p["key"]: p["value"] for p in rec.specialist_metadata["fact_block"]["pairs"]}
        assert got == {"alpha": "1", "beta-two": "hello", "gamma_3": "x.y.z", "delta": "value here ok"}


class TestDoesNotFire:
    @pytest.mark.parametrize("name,content", [
        ("prose.md", PROSE),
        ("dialogue.md", DIALOGUE),   # the veto — the chatlog Key:value collision
        ("faq.md", FAQ),
        ("changelog.md", CHANGELOG),
        ("fm_only.md", FRONTMATTER_ONLY),
        ("terse_changelog.md", TERSE_CHANGELOG),  # repeated keys — a list, not a record (distinct-key gate)
        ("terse_faq.md", TERSE_FAQ),
        ("id_repeated.md", ID_REPEATED),
    ])
    def test_negatives(self, tmp_path, name, content):
        rec, _ = _scan(tmp_path, name, content)
        assert rec.is_fact_block is False, f"{name} should NOT be a fact-block"
        assert not (rec.specialist_metadata or {}).get("fact_block")

    def test_source_code_not_flagged(self, tmp_path):
        # a .py of `field: Type` annotations is structurally kv-ish, but libmagic types it non-text
        # (text/x-script.python) → the MIME-guard coherence keeps it off is_fact_block (no flag-only FP).
        py = "class M:\n    name: str\n    id: int\n    count: float\n    active: bool\n"
        rec, _ = _scan(tmp_path, "model.py", py)
        assert rec.is_fact_block is False


class TestBounded:
    def test_hostile_inputs_never_crash_and_stay_capped(self, tmp_path):
        from file_observer.scanner import FACT_BLOCK_MAX_PAIRS, FACT_BLOCK_MAX_VALUE_LEN
        hostile = "\n".join(f"k{i}: v{i}" for i in range(FACT_BLOCK_MAX_PAIRS + 500))
        hostile += "\nbig: " + ("x" * (FACT_BLOCK_MAX_VALUE_LEN + 1000)) + "\n"
        hostile += "colon" + (":" * 5000) + " x\n"
        rec, _ = _scan(tmp_path, "hostile.txt", hostile)
        fb = (rec.specialist_metadata or {}).get("fact_block")
        if fb:  # fires (it is a kv-block) — must be capped
            assert fb["pair_count"] <= FACT_BLOCK_MAX_PAIRS
            assert all(len(p["value"]) <= FACT_BLOCK_MAX_VALUE_LEN for p in fb["pairs"])


class TestSchemaAndDeterminism:
    def test_namespace_provisional_in_schema(self):
        doc = build_schema_document()
        fields = {f["name"]: f["stability"] for f in doc["specialists"]["fields"]["fact_block"]}
        assert fields == {"pair_count": "provisional", "pairs": "provisional", "duplicate_keys": "provisional"}

    def test_registry_matches(self):
        for f in ("pair_count", "pairs", "duplicate_keys"):
            assert ("fact_block", f) in PROVISIONAL_SPECIALIST_FIELDS

    def test_vector_registered_with_rules_hash(self, tmp_path):
        _, m = _scan(tmp_path, "edge.md", FACT_BLOCK)
        v = next(v for v in m.vectors_collected if v["vector_id"] == "fact_block")
        assert v["applied_to_count"] == 1
        assert v["rules_hash"] and v["identity_digest"]

    def test_rules_fingerprint_covers_the_gate(self):
        fp = fact_block_rules_fingerprint()
        # a rule edit MUST be reflected — the fingerprint enumerates the live regex/veto set
        assert "kv_re=" in fp and "veto_words=" in fp and "struct_re=" in fp

    def test_deterministic(self, tmp_path):
        (tmp_path / "edge.md").write_text(FACT_BLOCK, encoding="utf-8")
        a = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        b = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        assert a.manifest_checksum == b.manifest_checksum

    def test_detection_runs_without_specialists(self, tmp_path):
        # the FLAG fires even when extraction is disabled (detection is cheap, always-on)
        rec, _ = _scan(tmp_path, "edge.md", FACT_BLOCK, specialists=False)
        assert rec.is_fact_block is True
        assert (rec.specialist_metadata or {}).get("fact_block") is None


class TestCoherenceWithDedicatedSpecialists:
    def test_email_not_double_handled(self, tmp_path):
        # a .eml body is itself a header kv-block, but the email specialist owns it —
        # fact_block must NOT fire (no double-handling, no spurious probe error).
        eml = "From: a@b.com\nTo: c@d.com\nSubject: Lunch?\nDate: Mon, 1 Jan 2026 00:00:00 +0000\n\nhi\n"
        rec, _ = _scan(tmp_path, "m.eml", eml)
        assert rec.is_fact_block is False
        assert not any(e.detail and e.detail.get("reason") == "mime_guard_mismatch"
                       for e in (rec.errors or []))
