"""v1.43 — lexicon source loader: distribution format + composition.

Falsify-first. Two accepted formats (JSON canonical + EasyList-style text) normalize to ONE resolved
lexicon; composition is order-independent; source provenance NEVER reaches the manifest; the resolved
lexicon (and thus dictionary_id + the manifest) is identical to the equivalent single-JSON path. The
new text/index parsers are bounded / fail-loud.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_observer.scanner import (
    LEXICON_MAX_SOURCES,
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
    compose_lexicons,
    lexicon_dictionary_id,
    load_lexicon,
    load_lexicon_source,
    parse_lexicon,
    parse_lexicon_text,
)

JSON_LEX = {
    "lexicon_id": "fruit", "version": "2026.07", "source": "SECRET-SOURCE-NAME",
    "categories": {"tropical": ["banana", "mango"], "stone": ["cherry"]},
}
TEXT_LEX = """! Title: fruit
! Version: 2026.07
! Source: SECRET-SOURCE-NAME
[tropical]
mango
banana
[stone]
cherry
"""


def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "doc.md").write_text("i love banana and cherry pie\n", encoding="utf-8")
    return tmp_path


# --- 1. format equivalence: text vs JSON, same terms → identical dictionary_id + manifest ----------
def test_text_json_equivalence(tmp_path: Path, tree: Path):
    jp = _write(tmp_path, "l.json", json.dumps(JSON_LEX))
    tp = _write(tmp_path, "l.txt", TEXT_LEX)
    lj, _ = load_lexicon([str(jp)])
    lt, _ = load_lexicon([str(tp)])
    assert lexicon_dictionary_id(lj) == lexicon_dictionary_id(lt)
    m1 = Scanner(tree, ScannerConfig(enable_specialists=True, lexicon=lj)).scan()
    m2 = Scanner(tree, ScannerConfig(enable_specialists=True, lexicon=lt)).scan()
    assert m1.manifest_checksum == m2.manifest_checksum  # byte-identical for equivalent resolved terms


# --- 2. composition determinism: order-independent; flags == index ---------------------------------
def test_composition_order_independent(tmp_path: Path):
    a = _write(tmp_path, "a.txt", "! Title: fruit\n[tropical]\nmango\n")
    b = _write(tmp_path, "b.txt", "! Title: veg\n[tropical]\nbanana\n[root]\ncarrot\n")
    fwd, _ = load_lexicon([str(a), str(b)], lexicon_id="all")
    rev, _ = load_lexicon([str(b), str(a)], lexicon_id="all")
    assert lexicon_dictionary_id(fwd) == lexicon_dictionary_id(rev)
    assert fwd["categories"] == {"tropical": ["banana", "mango"], "root": ["carrot"]}


def test_index_matches_flags(tmp_path: Path):
    a = _write(tmp_path, "a.txt", "! Title: fruit\n[tropical]\nmango\n")
    b = _write(tmp_path, "b.json", json.dumps({"lexicon_id": "veg", "categories": {"root": ["carrot"]}}))
    idx = _write(tmp_path, "index.txt", "! subscription list\na.txt\nb.json\n")
    via_index, _ = load_lexicon(None, str(idx), lexicon_id="all")
    via_flags, _ = load_lexicon([str(a), str(b)], lexicon_id="all")
    assert lexicon_dictionary_id(via_index) == lexicon_dictionary_id(via_flags)


# --- 3. no-leak: version / source / path never in the manifest -------------------------------------
def test_no_provenance_leak(tmp_path: Path):
    # the lexicon file lives OUTSIDE the scanned tree (else the scan reads it as a data file)
    scan_dir = tmp_path / "data"; scan_dir.mkdir()
    (scan_dir / "doc.md").write_text("i love banana and cherry pie\n", encoding="utf-8")
    lex_dir = tmp_path / "lex"; lex_dir.mkdir()
    tp = _write(lex_dir, "SECRET-FILENAME.txt", TEXT_LEX)
    lex, metas = load_lexicon([str(tp)])
    assert any(m.get("source") == "SECRET-SOURCE-NAME" for m in metas)  # provenance reaches stderr metas
    from file_observer.scanner import manifest_to_json
    m = manifest_to_json(Scanner(scan_dir, ScannerConfig(enable_specialists=True, lexicon=lex)).scan())
    assert "SECRET-SOURCE-NAME" not in m
    assert "SECRET-FILENAME" not in m
    assert "2026.07" not in m


# --- 4. backward-compat: loader resolved id == the direct parse_lexicon id -------------------------
def test_backward_compat_dictionary_id(tmp_path: Path):
    jp = _write(tmp_path, "l.json", json.dumps(JSON_LEX))
    lex, _ = load_lexicon([str(jp)])
    assert lexicon_dictionary_id(lex) == lexicon_dictionary_id(parse_lexicon(JSON_LEX))


# --- 5. dictionary_id semantics: version bump == same id; term added → id moves --------------------
def test_version_bump_same_id_term_moves_id(tmp_path: Path):
    v1 = _write(tmp_path, "v1.txt", "! Title: x\n! Version: 1\n[c]\nbanana\n")
    v2 = _write(tmp_path, "v2.txt", "! Title: x\n! Version: 2\n[c]\nbanana\n")
    v3 = _write(tmp_path, "v3.txt", "! Title: x\n! Version: 2\n[c]\nbanana\ncherry\n")
    a, _ = load_lexicon([str(v1)]); b, _ = load_lexicon([str(v2)]); c, _ = load_lexicon([str(v3)])
    assert lexicon_dictionary_id(a) == lexicon_dictionary_id(b)
    assert lexicon_dictionary_id(a) != lexicon_dictionary_id(c)


# --- 6. bounds / never-crash ----------------------------------------------------------------------
def test_term_before_category_fails(tmp_path: Path):
    p = _write(tmp_path, "bad.txt", "! Title: x\nbanana\n[c]\ncherry\n")
    with pytest.raises(ValueError):
        load_lexicon_source(p)


def test_missing_title_fails():
    with pytest.raises(ValueError):
        parse_lexicon_text("[c]\nbanana\n")


def test_too_many_sources(tmp_path: Path):
    ps = [str(_write(tmp_path, f"s{i}.txt", f"! Title: x{i}\n[c]\nt{i}\n"))
          for i in range(LEXICON_MAX_SOURCES + 1)]
    with pytest.raises(ValueError):
        load_lexicon(ps)


def test_oversize_line_fails():
    with pytest.raises(ValueError):
        parse_lexicon_text("! Title: x\n[c]\n" + ("a" * 9000) + "\n")


def test_compose_empty_fails():
    with pytest.raises(ValueError):
        compose_lexicons([])


# --- 7. integrity warning: declared count != parsed → recorded, not a failure ----------------------
def test_count_mismatch_recorded(tmp_path: Path):
    p = _write(tmp_path, "c.txt", "! Title: x\n! Count: 5\n[c]\nbanana\ncherry\n")
    lex, metas = load_lexicon([str(p)])
    assert metas[0]["count_mismatch"] is True
    assert lex["categories"]["c"] == ["banana", "cherry"]  # load still succeeded


# --- version axes ---------------------------------------------------------------------------------
def test_version_axes():
    assert SCANNER_VERSION == "1.43.0"
    assert LOGIC_VERSION == "1.22.0"   # loader upgrade = front-door, LOGIC frozen
    assert SCHEMA_VERSION == "1.23"    # manifest contract frozen
