"""v1.45 — decouple the human summary from the checksum + refresh it (#147).

Falsify-first. The load-bearing test is #1: the summary is a derived VIEW, so `manifest_checksum`
must be INDEPENDENT of its content — mutating the prose moves nothing. With that decoupling, the
#147 refresh (lexicon vector detail + fact_block + ai_session) rides free (LOGIC bump is the one-time
exclusion, not the prose). The refresh is gated on presence, so plain corpora render unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_observer.scanner import (
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
    compute_manifest_checksum,
)

LEX = {"lexicon_id": "fruit", "categories": {"fruit": ["banana"]}}

AI_SESSION = "\n".join(json.dumps(x) for x in [
    {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "please help me with this task now"}]}},
    {"type": "assistant", "message": {"id": "msg_01A", "role": "assistant", "model": "claude-opus-4-8",
        "content": [{"type": "text", "text": "sure here is how you do it in some detail"}],
        "usage": {"input_tokens": 10, "output_tokens": 6, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 100}}},
    {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "thanks that worked out great for me"}]}},
    {"type": "assistant", "message": {"id": "msg_01B", "role": "assistant", "model": "claude-opus-4-8",
        "content": [{"type": "text", "text": "glad it helped you out a lot today"}],
        "usage": {"input_tokens": 20, "output_tokens": 8, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 0}}},
]) + "\n"

FACT_BLOCK = "Name: Alice\nRole: Engineer\nTeam: Platform Services\nLocation: Remote Office\n"


@pytest.fixture
def rich_tree(tmp_path: Path) -> Path:
    (tmp_path / "doc.md").write_text("i love banana pie today with friends\n", encoding="utf-8")  # lexicon hit
    (tmp_path / "facts.txt").write_text(FACT_BLOCK, encoding="utf-8")                             # fact_block
    (tmp_path / "session.jsonl").write_text(AI_SESSION, encoding="utf-8")                         # ai_session
    return tmp_path


@pytest.fixture
def plain_tree(tmp_path: Path) -> Path:
    (tmp_path / "a.md").write_text("just some ordinary prose here, nothing special at all\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("x,y\n1,2\n3,4\n", encoding="utf-8")
    return tmp_path


# --- 1. THE decoupling: manifest_checksum is INDEPENDENT of the summary content -------------------
def test_checksum_independent_of_summary(plain_tree: Path):
    m = Scanner(plain_tree, ScannerConfig(enable_specialists=True)).scan()
    assert m.manifest_checksum == compute_manifest_checksum(m)   # the EMITTED field matches the recompute
    c1 = m.manifest_checksum
    m.summary = "ARBITRARY REWRITTEN PROSE " * 20   # mutate the human view
    assert compute_manifest_checksum(m) == c1, "summary must NOT be in the checksum (v1.45)"


# --- 2. the refresh appears on a rich corpus ------------------------------------------------------
def test_refresh_present(rich_tree: Path):
    m = Scanner(rich_tree, ScannerConfig(enable_specialists=True, lexicon=LEX)).scan()
    s = m.summary.lower()
    assert "lexicon matched" in s
    assert "fact block" in s
    assert "ai session" in s
    # the ai_session token total in the summary = summed canonical token counts (a count, never a price)
    keys = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "reasoning_tokens")
    total = 0
    for f in m.files:
        ais = (f.specialist_metadata or {}).get("ai_session")
        if isinstance(ais, dict):                                # guard: an ai_session value may be None
            u = ais.get("usage") or {}
            t = u.get("total_tokens")                            # vendor total when present, else components
            total += t if t is not None else sum(u.get(k) or 0 for k in keys)
    assert total > 0 and f"{total:,}" in m.summary


# --- 3. gated: a plain corpus renders NONE of the new lines ---------------------------------------
def test_refresh_gated(plain_tree: Path):
    s = Scanner(plain_tree, ScannerConfig(enable_specialists=True)).scan().summary.lower()
    assert "lexicon matched" not in s and "fact block" not in s and "ai session" not in s


# --- 4. the signature is over a summary-independent checksum (non-sealed consequence) -------------
def test_signature_over_summary_independent_checksum(plain_tree: Path):
    m = Scanner(plain_tree, ScannerConfig(enable_specialists=True, signing_key="k" * 16)).scan()
    assert m.manifest_signature is not None
    c1 = compute_manifest_checksum(m)
    m.summary = "TAMPERED SUMMARY"          # tampering the prose ...
    assert compute_manifest_checksum(m) == c1   # ... does not move the checksum the signature is over


# --- 5. version axes ------------------------------------------------------------------------------
def test_version_axes():
    assert tuple(int(p) for p in SCANNER_VERSION.split(".")) >= (1, 45, 0)   # floor (v1.46 bumped SCANNER)
    assert tuple(int(p) for p in LOGIC_VERSION.split(".")) >= (1, 23, 0)   # floor (v1.46 bumped LOGIC)
    assert SCHEMA_VERSION == "1.23"    # the summary field's shape is unchanged
