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
    PROVISIONAL_SPECIALIST_FIELDS,
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


def test_held_by_design_manifest_fields_stay_provisional():
    """leg-4/CodeRabbit: the held-by-design FileRecord fields (§2.4) must ALSO stay off the promotion
    — they live in a separate registry (PROVISIONAL_MANIFEST_FIELDS) the field-stability test above
    doesn't cover. The signature vocabulary intentionally grows every MIME change → never promotable."""
    from file_observer.scanner import PROVISIONAL_MANIFEST_FIELDS
    for pair in (("FileRecord", "format_signatures"), ("FileRecord", "is_polyglot")):
        assert pair in PROVISIONAL_MANIFEST_FIELDS, f"{pair} (held-by-design §2.4) must stay provisional"


def test_manifest_carries_no_stability_annotation(tmp_path: Path):
    """The load-bearing designation-only proof: stability is a `--schema`-only concept, so a manifest
    that DOES contain promoted-namespace metadata still carries no `stability` key anywhere — the
    promotion is structurally incapable of moving any manifest value. (The only manifest change this
    release is `schema_version` itself.) Exercises the `audio` namespace with a real generated `.mp3`
    (leg-4/CodeRabbit — the prior text-only tree never serialized a promoted namespace)."""
    import struct

    def _cbr_mp3(title, artist, album, year, audio_bytes=16000):
        # a minimal ID3v2.3 tag (UTF-8 text frames) + one 128 kbps MPEG1-LayerIII frame
        def frame(fid, text):
            payload = b"\x03" + text.encode("utf-8")
            return fid + struct.pack(">I", len(payload)) + b"\x00\x00" + payload
        body = frame(b"TIT2", title) + frame(b"TPE1", artist) + frame(b"TALB", album) + frame(b"TYER", year)
        ss = bytes([(len(body) >> 21) & 0x7F, (len(body) >> 14) & 0x7F, (len(body) >> 7) & 0x7F, len(body) & 0x7F])
        id3 = b"ID3\x03\x00\x00" + ss + body
        mpeg_frame = b"\xff\xfb\x90\x00" + b"\x00" * (audio_bytes - 4)  # sync + MPEG1/LayerIII/128kbps/44100
        return id3 + mpeg_frame

    (tmp_path / "a.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "song.mp3").write_bytes(_cbr_mp3("T", "A", "Al", "2024"))
    m = Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan()

    # the audio namespace WAS exercised (otherwise the no-stability check is vacuous for it)
    audio_recs = [f for f in m.files
                  if isinstance(getattr(f, "specialist_metadata", None), dict)
                  and f.specialist_metadata.get("audio")]
    assert audio_recs, "the generated .mp3 must have produced an `audio` specialist record"

    payload = manifest_to_json(m)
    assert '"stability"' not in payload, "manifest must not carry a stability annotation (--schema-only)"
    assert json.loads(payload)["schema_version"] == "1.24"


def test_schema_annotates_promoted_namespaces_stable():
    """`--schema` (the surface where stability DOES live) must annotate EVERY presentation/audio field
    stable. Namespace-scoped (some field names — title/author/format — recur in still-provisional
    namespaces, so a name-only walk would false-positive); asserts on the parsed schema doc directly."""
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, "-m", "file_observer.scanner", "--schema", "--schema-format", "json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    schema = json.loads(r.stdout)

    found: dict[str, dict[str, str]] = {}

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if (k in ("presentation", "audio") and isinstance(v, list) and v
                        and isinstance(v[0], dict) and "stability" in v[0]):
                    found[k] = {e["name"]: e["stability"] for e in v}
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(schema)
    assert {"presentation", "audio"} <= set(found), \
        f"--schema must list the presentation + audio namespaces with stability (got {list(found)})"
    for ns in ("presentation", "audio"):
        for name, stab in found[ns].items():
            assert stab == "stable", f"--schema annotates {ns}.{name} as {stab!r}, expected stable"
