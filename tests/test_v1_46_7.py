"""v1.46.7 (patch) — MIME synonym classes: a mismatch must mean a GENUINE content-vs-
extension disagreement, not two spellings of one format.

`analyze_mime` compared `detected_mime == extension_mime` with a strict `==`, so a
legitimate synonym was reported as a content-vs-extension MISMATCH → the file scored
"degraded". Surfaced by a real jsonl chatlog corpus (recall's LongMemEval synthesis)
scoring 0% clean — 19,195/19,195 false mismatches, ALL JSON-family synonyms: libmagic
types `.jsonl` as `application/x-ndjson` (multi-line) or `application/json` (single-line)
while the extension map registers `application/jsonl`.

Fix: `_mime_labels_compatible` folds SAME-format-different-label classes (JSON family +
xml/rtf/markdown/python pairs). A binary content type for a text extension — or any
genuine cross-format pair — is NOT in a synonym class → still flags (a `.txt` that is
really a PNG survives). Values-move: `matches_extension` False→True on synonym-labelled
files → manifest_checksum moves for those corpora ONLY (the v1.25.1 accuracy-fix
precedent; default corpora byte-identical). LOGIC 1.24.4→1.24.5, SCHEMA 1.23 FROZEN.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_observer.scanner import (
    MIME_SYNONYM_CLASSES,
    Scanner,
    ScannerConfig,
    _mime_labels_compatible,
    manifest_to_json,
)


# ---- the helper, in isolation --------------------------------------------------------

def test_identical_labels_match():
    assert _mime_labels_compatible("application/json", "application/json")


@pytest.mark.parametrize(
    "detected,expected",
    [
        # the recall finding: both libmagic spellings of a .jsonl vs the extension map
        ("application/x-ndjson", "application/jsonl"),
        ("application/json", "application/jsonl"),
        ("application/jsonl", "application/x-ndjson"),
        # symmetric
        ("application/jsonl", "application/json"),
        # DELIBERATE JSON-FAMILY fold (leg-1 v1.46.7, accepted tradeoff): a `.json` whose
        # content libmagic types x-ndjson (or vice-versa) is treated as compatible, NOT a
        # disagreement — libmagic's single-vs-multi-doc split is an unreliable line-count
        # heuristic and both are JSON-family text the specialists consume interchangeably.
        ("application/json", "application/x-ndjson"),
        ("application/x-ndjson", "application/json"),
        # the other grounded synonym classes (from the fixtures mismatch sweep)
        ("text/xml", "application/xml"),
        ("application/xml", "text/xml"),
        ("text/rtf", "application/rtf"),
        ("text/x-script.python", "text/x-python"),
        ("application/x-bytecode.python", "application/x-python-code"),
        ("text/x-markdown", "text/markdown"),
    ],
)
def test_synonyms_compatible(detected, expected):
    assert _mime_labels_compatible(detected, expected), f"{detected} ≡ {expected} should match"


@pytest.mark.parametrize(
    "detected,expected",
    [
        # genuine cross-format disagreements MUST still flag
        ("image/png", "text/plain"),            # a .txt that is really a PNG
        ("application/pdf", "text/plain"),
        ("image/webp", "image/png"),
        ("video/quicktime", "video/mp4"),
        ("application/zip", "application/pdf"),
        # the SUPERTYPE relationship is deliberately NOT folded here (separate question):
        # text/plain content for a text-based extension is left as a mismatch, unchanged.
        ("text/plain", "text/markdown"),
        ("text/plain", "application/yaml"),
        # cross-class: json is a synonym class, xml is another — not compatible across
        ("application/json", "application/xml"),
    ],
)
def test_genuine_mismatch_still_flags(detected, expected):
    assert not _mime_labels_compatible(detected, expected), f"{detected} vs {expected} must NOT match"


# ---- end-to-end: a real jsonl file no longer scores degraded --------------------------

_MULTILINE = (
    '{"role":"user","content":"what did I say about the dentist"}\n'
    '{"role":"assistant","content":"you mentioned an appointment on the 5th"}\n'
    '{"role":"user","content":"right, thanks"}\n'
)


def test_jsonl_not_a_mismatch(tmp_path: Path):
    """The load-bearing repro: a valid multi-line .jsonl chatlog. libmagic types it
    application/x-ndjson; the extension map says application/jsonl. Pre-fix this was a
    mismatch → degraded. Post-fix it is clean."""
    p = tmp_path / "session.jsonl"
    p.write_text(_MULTILINE, encoding="utf-8")
    m = Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan()
    fr = next(f for f in m.files if f.path.endswith("session.jsonl"))
    ma = fr.mime_analysis
    # Only assert the fix when libmagic actually returned a synonym (not text/plain on a
    # no-libmagic box) — otherwise the pin isn't exercised and the assertion is vacuous.
    if ma.detected_mime in {"application/x-ndjson", "application/json", "application/jsonl"}:
        assert ma.matches_extension is True, (
            f"jsonl detected={ma.detected_mime} vs extension={ma.extension_mime} "
            "should be a MATCH (JSON-family synonym), not a mismatch"
        )
    # is_chatlog is unaffected by the MIME-mismatch fix (detection guards already synonym-aware)
    assert fr.is_chatlog is True


def test_jsonl_corpus_scores_clean(tmp_path: Path):
    """quality: a directory of valid .jsonl chatlogs is no longer 100% degraded (the
    recall symptom: 0 clean on a clean corpus). Guarded to the synonym path."""
    for i in range(5):
        (tmp_path / f"s{i}.jsonl").write_text(_MULTILINE, encoding="utf-8")
    m = Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan()
    detected = {f.mime_analysis.detected_mime for f in m.files}
    if detected & {"application/x-ndjson", "application/json", "application/jsonl"}:
        # The fix's guarantee, on BOTH the libmagic and no-libmagic paths: a valid jsonl
        # corpus is no longer 100% MIME-mismatch (the recall symptom).
        assert m.quality.mime_mismatches == 0, "valid jsonl corpus must not be all-mismatch"
        # clean_files is stronger and libmagic-path-specific: on the NO-libmagic path a
        # `.jsonl` has no magic signature → falls to extension_fallback → degraded for that
        # (pre-existing, accepted — v1.21) reason, NOT a mismatch. So only assert "clean"
        # when libmagic CONTENT-identified the file (detected is x-ndjson/json, not the
        # extension-fallback application/jsonl). recall's real scan is the libmagic path.
        if detected & {"application/x-ndjson", "application/json"}:
            assert m.quality.clean_files == m.quality.total_files, "a content-identified jsonl corpus must score clean"


# ---- a real cross-format mismatch is still surfaced end-to-end ------------------------

def test_png_as_txt_still_mismatches(tmp_path: Path):
    """Falsify the fix: a PNG with a .txt extension must STILL be a mismatch (the synonym
    fold must not swallow a genuine binary-in-text-clothing disagreement)."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # PNG magic → libmagic image/png
    p = tmp_path / "lying.txt"
    p.write_bytes(png)
    m = Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan()
    fr = next(f for f in m.files if f.path.endswith("lying.txt"))
    if fr.mime_analysis.detected_mime == "image/png":
        assert fr.mime_analysis.matches_extension is False, "PNG-as-.txt must remain a mismatch"


# ---- table hygiene + version axes ----------------------------------------------------

def test_synonym_corpus_worker_deterministic(tmp_path: Path):
    """The values-move (matches_extension flips on synonym files) must stay byte-identical
    across worker counts — the v1.9 determinism contract. The default fixtures cover
    xml/rtf/python synonyms under the global workers-equality gate, but jsonl isn't among
    them, so pin it explicitly here (leg-4/CodeRabbit)."""
    for i in range(6):
        (tmp_path / f"s{i}.jsonl").write_text(_MULTILINE, encoding="utf-8")
    m1 = Scanner(tmp_path, ScannerConfig(enable_specialists=True, workers=1)).scan()
    m4 = Scanner(tmp_path, ScannerConfig(enable_specialists=True, workers=4)).scan()
    assert m1.manifest_checksum == m4.manifest_checksum, "workers=1 vs 4 must be byte-identical"
    # Compare the full canonical serialized payload (leg-4/CodeRabbit), normalizing only the
    # documented volatile fields (scan_id, generated_at) — the checksum already proves this,
    # but an explicit byte comparison surfaces any drift as a readable diff, not just a hash
    # mismatch, and covers the complete MIME-analysis result, not the boolean alone.
    def _canon(m):
        d = json.loads(manifest_to_json(m))
        d["meta"]["scan_id"] = d["meta"]["generated_at"] = "<volatile>"
        return json.dumps(d, sort_keys=True)
    assert _canon(m1) == _canon(m4), "canonical manifest must be byte-identical across worker counts"
    # And the complete MIME result per file (detected + extension + match), so detection
    # drift on the synonym path can't pass unnoticed.
    mime1 = {f.path: (f.mime_analysis.detected_mime, f.mime_analysis.extension_mime, f.mime_analysis.matches_extension) for f in m1.files}
    mime4 = {f.path: (f.mime_analysis.detected_mime, f.mime_analysis.extension_mime, f.mime_analysis.matches_extension) for f in m4.files}
    assert mime1 == mime4, "full MIME analysis must be identical across worker counts"


def test_synonym_classes_are_disjoint():
    """No MIME may appear in two classes (an ambiguous membership would make
    compatibility non-transitive / order-dependent)."""
    seen: set[str] = set()
    for cls in MIME_SYNONYM_CLASSES:
        dup = seen & cls
        assert not dup, f"MIME(s) {dup} appear in more than one synonym class"
        seen |= cls
