"""v1.46.6 (patch) — confine lexicon-index members to the index directory (bestiary soak ③ note).

A `--lexicon-index` subscription file lists member lexicon `sources` "resolved relative to the index
dir". bestiary found a `sources:["../../etc/passwd"]` (or an absolute path, or a symlink) escaped the
index dir before failing loud — the exact traversal surface the v1.43 RFC deferred `!#include` to avoid
and claimed absent. Operator-trust so not a strict vuln, but it matters under the subscription/
distribution model (a third-party index shouldn't reach outside its bundle).

Fix: resolve()-containment in `_read_lexicon_index` — a member escaping the index dir fails LOUD (the
read never happens). Cross-bundle composition stays via separate `--lexicon PATH` flags. A loader
hardening → a valid in-bundle index resolves identically → LOGIC/SCHEMA frozen (the v1.43 precedent).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from file_observer.scanner import (
    LEXICON_MAX_SOURCES,
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    _read_lexicon_index,
)


def _bundle(tmp_path: Path) -> Path:
    b = tmp_path / "bundle"
    b.mkdir()
    (b / "base.json").write_text('{"lexicon_id":"x","categories":{"c":["term"]}}', encoding="utf-8")
    (b / "sub").mkdir()
    (b / "sub" / "more.json").write_text('{"categories":{"d":["t2"]}}', encoding="utf-8")
    (tmp_path / "secret.json").write_text('{"categories":{"leak":["x"]}}', encoding="utf-8")  # OUT of bundle
    return b


def _idx(bundle: Path, sources) -> Path:
    p = bundle / "index.json"
    p.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return p


def test_in_bundle_members_ok(tmp_path: Path):
    b = _bundle(tmp_path)
    members, _ = _read_lexicon_index(_idx(b, ["base.json", "sub/more.json"]))
    # assert the EXACT members (not just the count — a dup/wrong-path regression would pass otherwise)
    assert [m.resolve() for m in members] == [(b / "base.json").resolve(), (b / "sub" / "more.json").resolve()]


@pytest.mark.parametrize("bad", ["../secret.json", "../../etc/passwd", "sub/../../secret.json"])
def test_dotdot_escape_rejected(tmp_path: Path, bad: str):
    b = _bundle(tmp_path)
    with pytest.raises(ValueError, match="escapes the index directory"):
        _read_lexicon_index(_idx(b, [bad]))


def test_absolute_out_of_bundle_rejected(tmp_path: Path):
    b = _bundle(tmp_path)
    with pytest.raises(ValueError, match="absolute path"):
        _read_lexicon_index(_idx(b, [str(tmp_path / "secret.json")]))   # absolute, out of bundle


def test_absolute_in_bundle_also_rejected(tmp_path: Path):
    # leg-4/CodeRabbit: an absolute path that lands INSIDE the bundle still violates the relative
    # contract (non-portable for a distributed index) → rejected regardless of where it resolves.
    b = _bundle(tmp_path)
    with pytest.raises(ValueError, match="absolute path"):
        _read_lexicon_index(_idx(b, [str(b / "base.json")]))


def test_overlong_index_capped_before_resolution(tmp_path: Path):
    # leg-4/Codex + CodeRabbit: the source-count cap must fire BEFORE the per-member resolve loop.
    # Prove the ORDERING (not just that it raises): make every over-cap member an ESCAPING path. If the
    # cap fires first → the CAP error ("refused before resolving"); if resolution ran first → the ESCAPE
    # error. Asserting the cap error proves no per-member resolve() happened.
    b = _bundle(tmp_path)
    with pytest.raises(ValueError, match="refused before resolving"):
        _read_lexicon_index(_idx(b, ["../escape.json"] * (LEXICON_MAX_SOURCES + 1)))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_symlink_escape_rejected(tmp_path: Path):
    # a symlink INSIDE the bundle pointing OUT → resolve()-containment must catch it
    b = _bundle(tmp_path)
    os.symlink(tmp_path / "secret.json", b / "link.json")
    with pytest.raises(ValueError, match="escapes the index directory"):
        _read_lexicon_index(_idx(b, ["link.json"]))


def test_version_axes():
    # NOTE: current net version moved on in v1.46.7 (MIME synonyms); this suite pins the
    # axes AS OF v1.46.6's LOGIC-frozen loader hardening, which the later patch preserved.
    assert SCANNER_VERSION == "1.46.7"
    assert LOGIC_VERSION == "1.24.5"   # v1.46.6 was LOGIC-frozen; v1.46.7 bumped it (synonym values-move)
    assert SCHEMA_VERSION == "1.23"
