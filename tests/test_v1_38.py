"""v1.38 — bring-your-own-lexicon term observer. Falsify-first.

fo counts a CONSUMER-SUPPLIED, category-tagged lexicon's terms in a file's text and reports
per-category counts + density — an OBSERVATION, never a verdict. The engine is values-neutral;
these tests use ONLY benign placeholder terms (fruit/animal words). The real sensitive lexicon is
consumer runtime config — never generated here, never committed, never echoed into the manifest.

Contracts falsified here:
  - dormant (no lexicon) → byte-identical to today (no namespace / vector / flag);
  - word-boundary matching, NOT substring (the measured 9.4x-FP decision);
  - multi-token (phrase) terms match as a contiguous token subsequence;
  - terms are NEVER emitted into the manifest (only counts + category names + a hash);
  - dictionary_id moves on ANY term change (silent-drift catch) + is stable on the same lexicon;
  - full-file read beats the 64 KB baseline window (no silent miss on a long file);
  - a hostile lexicon fails loud (bounded), never crashes;
  - workers byte-identical (the v1.9 contract holds for the new field);
  - version axes: SCANNER 1.38.0 · LOGIC 1.21.0 · SCHEMA 1.22.

Version axes: SCANNER 1.37.0→1.38.0 · LOGIC 1.20.0→1.21.0 · SCHEMA 1.21→1.22.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig, manifest_to_json,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
    parse_lexicon, lexicon_dictionary_id,
    LEXICON_NAMESPACE, LEXICON_VECTOR_ID, LEXICON_SAFETY_FLAG, LEXICON_METHOD_VERSION,
)

# --- BENIGN placeholder lexicon (stands in for the consumer's category-tagged terms) ---
BENIGN_LEXICON = {
    "lexicon_id": "benign-test-v1",
    "categories": {
        "fruit": ["apple", "banana", "cherry date"],   # includes a 2-token PHRASE term
        "animal": ["cat", "ox"],
    },
}
# distinctive benign terms for the no-echo test (unlikely to occur incidentally)
DISTINCTIVE_LEXICON = {
    "lexicon_id": "distinctive-v1",
    "categories": {"critters": ["quokka", "narwhal"]},
}


def _scan(dir_: Path, lexicon=None, specialists=False, workers=1):
    return Scanner(source_dir=dir_,
                   config=ScannerConfig(lexicon=lexicon, enable_specialists=specialists, workers=workers)).scan()


def _rec(manifest, name):
    return next(r for r in manifest.files if r.filename == name)


def _lexblock(manifest, name):
    return (_rec(manifest, name).specialist_metadata or {}).get(LEXICON_NAMESPACE)


class TestDormant:
    def test_no_lexicon_leaves_no_trace(self, tmp_path):
        (tmp_path / "a.txt").write_text("apple cat banana ox")
        m = _scan(tmp_path, lexicon=None)
        # no per-file namespace, no vector, no flag — the mechanism is dormant
        assert _lexblock(m, "a.txt") is None
        assert not any(v["vector_id"] == LEXICON_VECTOR_ID for v in m.vectors_collected)
        assert LEXICON_SAFETY_FLAG not in _rec(m, "a.txt").safety_flags

    def test_lexicon_not_in_meta_config(self, tmp_path):
        (tmp_path / "a.txt").write_text("apple")
        m = _scan(tmp_path, lexicon=BENIGN_LEXICON)
        assert "lexicon" not in m.meta.config   # consumer-private, like signing_key


class TestCounts:
    def test_counts_density_and_total(self, tmp_path):
        (tmp_path / "f.txt").write_text("apple apple banana cat ox ox ox")  # fruit=3, animal=4
        m = _scan(tmp_path, lexicon=BENIGN_LEXICON)
        blk = _lexblock(m, "f.txt")
        assert blk["lexicon_id"] == "benign-test-v1"
        assert blk["categories"]["fruit"]["count"] == 3
        assert blk["categories"]["animal"]["count"] == 4
        assert blk["total_hits"] == 7
        # density = count / total_tokens (7 tokens in the file)
        assert blk["categories"]["fruit"]["density"] == round(3 / 7, 8)

    def test_every_category_emitted_even_at_zero(self, tmp_path):
        (tmp_path / "f.txt").write_text("apple only")   # animal = 0
        blk = _lexblock(_scan(tmp_path, lexicon=BENIGN_LEXICON), "f.txt")
        assert blk["categories"]["animal"] == {"count": 0, "density": 0.0}  # observed-and-clear, not absent


class TestMatchingSemantics:
    def test_word_boundary_not_substring(self, tmp_path):
        # "category"/"concatenate" contain "cat"; "grapple" contains "apple"; only STANDALONE tokens count.
        (tmp_path / "f.txt").write_text("category concatenate grapple pineapple apple")
        blk = _lexblock(_scan(tmp_path, lexicon=BENIGN_LEXICON), "f.txt")
        assert blk["categories"]["animal"]["count"] == 0   # no standalone "cat" — substring would over-count
        assert blk["categories"]["fruit"]["count"] == 1    # only the standalone "apple"

    def test_phrase_term_matches_as_subsequence(self, tmp_path):
        (tmp_path / "hit.txt").write_text("i ate a cherry date today")   # "cherry date" contiguous → 1
        (tmp_path / "miss.txt").write_text("cherry pie and a fresh date")  # split → the phrase term is 0
        m = _scan(tmp_path, lexicon=BENIGN_LEXICON)
        assert _lexblock(m, "hit.txt")["categories"]["fruit"]["count"] == 1
        assert _lexblock(m, "miss.txt")["categories"]["fruit"]["count"] == 0

    def test_case_insensitive(self, tmp_path):
        (tmp_path / "f.txt").write_text("APPLE Cat oX")
        blk = _lexblock(_scan(tmp_path, lexicon=BENIGN_LEXICON), "f.txt")
        assert blk["total_hits"] == 3


class TestCoexistsWithSpecialist:
    def test_lexicon_and_email_specialist_both_present(self, tmp_path):
        # leg-1 review: a TEXT file with an extension specialist (.eml) + a lexicon must keep BOTH
        # namespaces — the extension-specialist path must MERGE, not reassign (which clobbered lexicon).
        (tmp_path / "m.eml").write_text(
            "From: alice@example.com\nTo: bob@example.com\nSubject: apple harvest\n\n"
            "We should discuss the apple and banana crop.\n")
        m = _scan(tmp_path, lexicon=BENIGN_LEXICON, specialists=True)
        sm = _rec(m, "m.eml").specialist_metadata or {}
        assert "email" in sm, "email specialist metadata was clobbered"
        assert LEXICON_NAMESPACE in sm, "lexicon metadata was clobbered by the email specialist"
        assert sm[LEXICON_NAMESPACE]["categories"]["fruit"]["count"] >= 2   # apple + banana

    def test_total_tokens_emitted_and_reconciles_density(self, tmp_path):
        (tmp_path / "f.txt").write_text("apple banana cat and some filler words here")
        blk = _lexblock(_scan(tmp_path, lexicon=BENIGN_LEXICON), "f.txt")
        tt = blk["total_tokens"]
        assert tt == 8   # tokens in the file
        # a consumer can recompute density from count + total_tokens
        assert blk["categories"]["fruit"]["density"] == round(blk["categories"]["fruit"]["count"] / tt, 8)


class TestPresenceFlag:
    def test_flag_on_hit_only(self, tmp_path):
        (tmp_path / "hit.txt").write_text("apple")
        (tmp_path / "clear.txt").write_text("nothing relevant here")
        m = _scan(tmp_path, lexicon=BENIGN_LEXICON)
        assert LEXICON_SAFETY_FLAG in _rec(m, "hit.txt").safety_flags
        assert LEXICON_SAFETY_FLAG not in _rec(m, "clear.txt").safety_flags
        assert _rec(m, "hit.txt").safety_flags == sorted(_rec(m, "hit.txt").safety_flags)  # deterministic order


class TestNoTermLeak:
    def test_terms_never_appear_in_manifest(self, tmp_path):
        # even when a distinctive term MATCHES, it must not be echoed anywhere in the manifest.
        (tmp_path / "f.txt").write_text("a quokka and a narwhal walk in")
        m = _scan(tmp_path, lexicon=DISTINCTIVE_LEXICON)
        blk = _lexblock(m, "f.txt")
        assert blk["categories"]["critters"]["count"] == 2   # matched
        # the emitted per-file block + the vector must contain NO term string
        assert "quokka" not in json.dumps(blk) and "narwhal" not in json.dumps(blk)
        vec = next(v for v in m.vectors_collected if v["vector_id"] == LEXICON_VECTOR_ID)
        assert "quokka" not in json.dumps(vec) and "narwhal" not in json.dumps(vec)
        assert "quokka" not in vec["dictionary_id"]   # dictionary_id is a hash, not the terms
        assert len(vec["dictionary_id"]) == 64 and all(c in "0123456789abcdef" for c in vec["dictionary_id"])


class TestDictionaryId:
    def test_stable_on_same_lexicon(self):
        assert lexicon_dictionary_id(parse_lexicon(BENIGN_LEXICON)) == \
               lexicon_dictionary_id(parse_lexicon(BENIGN_LEXICON))

    def test_no_delimiter_collision(self):
        # leg-4/Codex: a naive `|`/`=`-joined preimage collides on valid inputs — a lexicon_id
        # containing the delimiters vs a category with the same bytes. Canonical JSON must not collide.
        a = parse_lexicon({"lexicon_id": "x", "categories": {"a": ["b"], "c": ["d"]}})
        b = parse_lexicon({"lexicon_id": "x|a=b", "categories": {"c": ["d"]}})
        assert lexicon_dictionary_id(a) != lexicon_dictionary_id(b)

    def test_moves_on_term_change_same_label(self):
        # same lexicon_id LABEL, different terms → different dictionary_id (silent-drift catch)
        a = parse_lexicon({"lexicon_id": "x", "categories": {"c": ["apple"]}})
        b = parse_lexicon({"lexicon_id": "x", "categories": {"c": ["apple", "banana"]}})
        assert lexicon_dictionary_id(a) != lexicon_dictionary_id(b)

    def test_vector_identity_moves_with_dictionary(self, tmp_path):
        (tmp_path / "f.txt").write_text("apple")
        def _digest(lex):
            m = _scan(tmp_path, lexicon=lex)
            return next(v for v in m.vectors_collected if v["vector_id"] == LEXICON_VECTOR_ID)["identity_digest"]
        d1 = _digest({"lexicon_id": "x", "categories": {"c": ["apple"]}})
        d2 = _digest({"lexicon_id": "x", "categories": {"c": ["apple", "cherry"]}})
        assert d1 != d2


class TestFullFileRead:
    def test_term_past_baseline_window_is_counted(self, tmp_path):
        # a benign term ~200 KB in — well past the 64 KB baseline window. Full-file read must catch it.
        filler = "lorem ipsum dolor sit amet " * 8000   # ~216 KB, no lexicon terms
        (tmp_path / "big.txt").write_text(filler + "\ntrailing apple here\n")
        blk = _lexblock(_scan(tmp_path, lexicon=BENIGN_LEXICON), "big.txt")
        assert blk["categories"]["fruit"]["count"] >= 1   # a windowed read would report 0 (false clear)


class TestHostileLexicon:
    @pytest.mark.parametrize("bad", [
        {"categories": {"c": ["a"]}},                                   # no lexicon_id
        {"lexicon_id": "x"},                                            # no categories
        {"lexicon_id": "x", "categories": {}},                         # empty categories
        {"lexicon_id": "x", "categories": {"c": "apple"}},             # terms not a list
        {"lexicon_id": "x", "categories": {"c": [123]}},               # non-string term
        {"lexicon_id": "x", "categories": {"c": ["  "]}},              # term with no matchable token
        {"lexicon_id": "x" * 500, "categories": {"c": ["a"]}},         # oversized id
        {"lexicon_id": "x", "categories": {"c": ["word " * 40]}},      # >16-token term
    ])
    def test_bad_lexicon_fails_loud(self, bad):
        with pytest.raises(ValueError):
            parse_lexicon(bad)

    def test_invalid_term_not_echoed_in_error(self):
        # security (leg-4/CodeRabbit): a validation error must NOT leak the consumer-private term —
        # main() prints these to stderr/CI logs. Report the category + reason only, never the term.
        with pytest.raises(ValueError) as ei:
            parse_lexicon({"lexicon_id": "x", "categories": {"c": ["sekrittoken " * 20]}})  # >16 tokens
        assert "sekrittoken" not in str(ei.value)   # the term must not appear in the error

    def test_scanner_surfaces_bad_lexicon(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        with pytest.raises(ValueError):
            _scan(tmp_path, lexicon={"lexicon_id": "x", "categories": {}})


class TestVector:
    def test_registered_only_when_supplied(self, tmp_path):
        (tmp_path / "a.txt").write_text("apple cat")
        m = _scan(tmp_path, lexicon=BENIGN_LEXICON)
        vec = next((v for v in m.vectors_collected if v["vector_id"] == LEXICON_VECTOR_ID), None)
        assert vec is not None
        assert vec["scope"] == "file" and vec["method_version"] == LEXICON_METHOD_VERSION
        assert vec["dictionary_id"] and vec["summary"]["lexicon_id"] == "benign-test-v1"
        assert vec["summary"]["files_matched"] == 1
        assert vec["summary"]["category_hits"]["fruit"] == 1 and vec["summary"]["category_hits"]["animal"] == 1


class TestDeterminism:
    def test_workers_byte_identical(self, tmp_path):
        for i in range(6):
            (tmp_path / f"f{i}.txt").write_text("apple cat banana ox " * (i + 1))
        c1 = json.loads(manifest_to_json(_scan(tmp_path, lexicon=BENIGN_LEXICON, workers=1)))["manifest_checksum"]
        c2 = json.loads(manifest_to_json(_scan(tmp_path, lexicon=BENIGN_LEXICON, workers=2)))["manifest_checksum"]
        assert c1 == c2


class TestVersioning:
    def test_axes(self):
        # >= so later releases don't break this (v1.38 introduced these; LOGIC/SCHEMA held since)
        assert tuple(int(p) for p in SCANNER_VERSION.split(".")) >= (1, 38, 0)
        # >= floors (v1.38 established these; v1.41 legitimately bumped past them — see HISTORY)
        assert tuple(int(p) for p in LOGIC_VERSION.split(".")) >= (1, 21, 0)   # new baseline derivation
        assert tuple(int(p) for p in SCHEMA_VERSION.split(".")) >= (1, 22)      # additive: namespace + vector + flag + trigger
