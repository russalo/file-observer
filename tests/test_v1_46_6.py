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
    assert len(members) == 2                                  # same-dir + subdir both allowed


@pytest.mark.parametrize("bad", ["../secret.json", "../../etc/passwd", "sub/../../secret.json"])
def test_dotdot_escape_rejected(tmp_path: Path, bad: str):
    b = _bundle(tmp_path)
    with pytest.raises(ValueError, match="escapes the index directory"):
        _read_lexicon_index(_idx(b, [bad]))


def test_absolute_path_rejected(tmp_path: Path):
    b = _bundle(tmp_path)
    with pytest.raises(ValueError, match="escapes the index directory"):
        _read_lexicon_index(_idx(b, [str(tmp_path / "secret.json")]))   # absolute, out of bundle


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink")
def test_symlink_escape_rejected(tmp_path: Path):
    # a symlink INSIDE the bundle pointing OUT → resolve()-containment must catch it
    b = _bundle(tmp_path)
    os.symlink(tmp_path / "secret.json", b / "link.json")
    with pytest.raises(ValueError, match="escapes the index directory"):
        _read_lexicon_index(_idx(b, ["link.json"]))


def test_version_axes():
    assert SCANNER_VERSION == "1.46.6"
    assert LOGIC_VERSION == "1.24.4"   # loader hardening — valid bundles byte-identical, LOGIC frozen
    assert SCHEMA_VERSION == "1.23"
