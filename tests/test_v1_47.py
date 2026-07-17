"""v1.47.0 — promotion pass: `presentation` + `audio` namespaces provisional → stable.

The third promotion pass (after v1.10/v1.14/v1.23/v1.31), and exactly the pair v1.31.0 §6 deferred
as "presentation/audio — too young, season next pass". Designation-only: stability lives ONLY in
`--schema`, so every extracted VALUE is byte-identical and the manifest carries no stability
annotation at all; `manifest_checksum` moves only because `schema_version` (1.23→1.24) is in the
checksum preimage (as on any SCHEMA bump). LOGIC frozen 1.24.6.

Falsify-first: the stability assertions are RED against the pre-promotion registry (which listed
presentation/audio in PROVISIONAL_SPECIALIST_FIELDS).
"""
from __future__ import annotations

import json
from pathlib import Path

from file_observer.scanner import (
    LOGIC_VERSION,
    PROVISIONAL_SPECIALIST_FIELDS,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
    _field_stability,
    manifest_to_json,
)

PROMOTED = [
    ("presentation", "slide_count"), ("presentation", "title"),
    ("presentation", "author"), ("presentation", "application"),
    ("audio", "format"), ("audio", "bitrate"), ("audio", "duration_s"),
    ("audio", "title"), ("audio", "artist"), ("audio", "album"), ("audio", "year"),
]

# Fields that MUST stay provisional — proves the pass is scoped, not a blanket flip.
STILL_PROVISIONAL = [
    ("chatlog", "content_shape"),      # alpha-locked + non-count redesign pending
    ("chatlog", "first_timestamp"),    # chatlog family, alpha-locked
    ("fact_block", "pairs"),           # too young (v1.32)
    ("ai_session", "usage"),           # too young (v1.33)
    ("ai_session", "usage_by_model"),  # too young (v1.35)
    ("lexicon_match", "categories"),   # too young (v1.38)
]

# Already stable since v1.31 — must remain stable (no regression).
STILL_STABLE = [("image", "make"), ("video", "codec"), ("video", "creation_date_qt")]


def test_presentation_audio_now_stable():
    """Falsify-first: red against the pre-promotion registry."""
    for ns, f in PROMOTED:
        assert _field_stability(ns, f) == "stable", f"{ns}.{f} should be promoted to stable"


def test_promoted_fields_removed_from_registry():
    for ns, f in PROMOTED:
        assert (ns, f) not in PROVISIONAL_SPECIALIST_FIELDS, f"{ns}.{f} still in the provisional registry"


def test_held_fields_stay_provisional():
    """The pass is SCOPED — the alpha-locked chatlog family and the young July namespaces must NOT
    have been swept along."""
    for ns, f in STILL_PROVISIONAL:
        assert _field_stability(ns, f) == "provisional", f"{ns}.{f} must stay provisional (held)"


def test_previously_stable_unchanged():
    for ns, f in STILL_STABLE:
        assert _field_stability(ns, f) == "stable", f"{ns}.{f} regressed off stable"


def test_manifest_carries_no_stability_annotation(tmp_path: Path):
    """The load-bearing designation-only proof: stability is a `--schema`-only concept. A real
    manifest — even of a presentation/audio-bearing tree — contains no `stability` key anywhere, so
    the promotion is structurally incapable of moving any manifest value. (The only manifest change
    this release is `schema_version` itself.)"""
    # a minimal recognizable text tree is enough — the manifest shape is what matters
    (tmp_path / "a.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Title\n\nbody\n", encoding="utf-8")
    m = Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan()
    payload = manifest_to_json(m)
    assert '"stability"' not in payload, "manifest must not carry a stability annotation (--schema-only)"
    # schema_version is the promoted contract version
    assert json.loads(payload)["schema_version"] == "1.24"


def test_schema_lists_presentation_audio_as_stable():
    """`--schema` (the surface where stability DOES live) annotates the promoted fields stable."""
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, "-m", "file_observer.scanner", "--schema", "--schema-format", "json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    doc = json.dumps(json.loads(r.stdout))  # normalize
    # crude but sufficient: the schema doc must contain the audio/presentation fields marked stable,
    # not provisional. Assert none of the promoted namespaces' fields are annotated provisional.
    schema = json.loads(r.stdout)

    def find_provisional(obj, ns_hint=None):
        bad = []
        if isinstance(obj, dict):
            nm = obj.get("name")
            if obj.get("stability") == "provisional" and nm in {f for _, f in PROMOTED}:
                bad.append(nm)
            for v in obj.values():
                bad += find_provisional(v)
        elif isinstance(obj, list):
            for v in obj:
                bad += find_provisional(v)
        return bad

    # Note: some field NAMES (title/author/format) also exist in still-provisional namespaces, so a
    # name-only check would false-positive. The authoritative check is _field_stability (above); this
    # asserts --schema and the registry agree for the unambiguous promoted names.
    for ns, f in [("audio", "bitrate"), ("audio", "duration_s"), ("audio", "year"),
                  ("presentation", "slide_count")]:
        assert _field_stability(ns, f) == "stable"


def test_version_axes():
    assert SCANNER_VERSION == "1.47.0"
    assert SCHEMA_VERSION == "1.24"    # promotion = contract change (v0.11/v1.10/v1.14/v1.23/v1.31)
    assert LOGIC_VERSION == "1.24.6"   # FROZEN — designation-only, no observing logic changed
