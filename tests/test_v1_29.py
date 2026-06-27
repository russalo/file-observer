"""v1.29.0 — chatlog detection recognizes agentic (tool-turn) sessions.

A turn with a conversational role + content carrying a recognized block type
(thinking/tool_use/tool_result/image/document/text) counts in BOTH detection and
turn-counting signals; prose signals stay text+thinking only. Falsify-first: the
relaxation must NOT false-fire on structured JSON with conversational-looking roles.
"""
import json
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    CHATLOG_CONTENT_BLOCK_TYPES,
    CHATLOG_RULES_DEFINITION,
    compute_rules_hash,
)


@pytest.fixture
def scanner(tmp_path):
    return Scanner(tmp_path, ScannerConfig(enable_specialists=True))


def _jsonl(*records):
    return "\n".join(json.dumps(r) for r in records)


# A real agentic Claude Code shape: opening prose, then thinking / tool_use /
# tool_result turns, then a closing text turn. Under the OLD text-centric gate
# only the 2 prose turns counted (< 3) → missed; under v1.29.0 all 5 count.
AGENTIC = _jsonl(
    {"type": "user", "message": {"role": "user", "content": "Fix the failing test."}},
    {"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "thinking", "thinking": "Let me read the file first."}]}},
    {"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "tool_use", "name": "Read", "input": {"path": "x.py"}}]}},
    {"type": "user", "message": {"role": "user",
        "content": [{"type": "tool_result", "content": "def x(): return 1"}]}},
    {"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "Fixed it — off-by-one in the loop."}]}},
)


def test_agentic_session_detected(scanner):
    """The tool-heavy session (the real-miss shape) is now is_chatlog=True."""
    assert scanner._detect_chatlog_pattern(AGENTIC) is True


def test_agentic_fixture_shape(scanner):
    """Documents the recovery mechanism: all 5 turns are recognized, but only 3
    carry prose — the user string, the thinking block, and the assistant text.
    The 2 tool turns (tool_use, tool_result) are empty-prose. Under the OLD
    text-centric gate the thinking turn (no top-level `text` key) and the 2 tool
    turns were uncounted → only 2 counted < 3 → missed. v1.29.0 recognizes all 5."""
    pairs = scanner._extract_json_conversation(AGENTIC)
    assert len(pairs) == 5                              # all turns recognized
    text_bearing = [p for p in pairs if p[1]]
    assert len(text_bearing) == 3                       # user + thinking + assistant text
    empty = [p for p in pairs if not p[1]]
    assert len(empty) == 2                              # tool_use + tool_result


# --- Falsify-first: structured JSON with conversational-LOOKING roles must NOT fire ---

ADVERSARIAL = {
    "telemetry": _jsonl(
        {"type": "system", "content": {"cpu": 0.4, "mem": 1024}},
        {"type": "tool", "content": [{"name": "disk", "val": 91}]},
        {"type": "function", "content": {"args": {"x": 1}, "ret": 0}},
        {"type": "system", "content": {"cpu": 0.6, "mem": 2048}},
        {"type": "tool", "content": [{"name": "net", "val": 12}]},
    ),
    "rbac": _jsonl(
        {"role": "admin", "value": {"perms": ["r", "w", "x"]}},
        {"role": "user", "value": {"perms": ["r"]}},
        {"role": "system", "value": {"perms": ["*"]}},
        {"role": "guest", "value": {"perms": []}},
    ),
    "funccall": _jsonl(
        {"role": "function", "content": {"name": "get_weather", "arguments": "{}"}},
        {"role": "function", "content": {"name": "get_time", "arguments": "{}"}},
        {"role": "system", "content": {"trace_id": "abc"}},
        {"role": "function", "content": {"name": "get_news", "arguments": "{}"}},
    ),
    "metrics": json.dumps([
        {"type": "system", "value": [1, 2, 3]},
        {"type": "model", "value": [4, 5, 6]},
        {"type": "tool", "value": [7, 8, 9]},
    ]),
}


@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_toolturn_gate_rejects_structured_json(scanner, name):
    """Telemetry / RBAC / function-call / metrics JSON have conversational-looking
    roles but no recognized content blocks → must stay is_chatlog=False."""
    assert scanner._detect_chatlog_pattern(ADVERSARIAL[name]) is False


# --- No regression on string-content formats (arm (a) unchanged) ---

def test_no_regression_on_sharegpt(scanner):
    sharegpt = json.dumps([
        {"from": "human", "value": "What is 2+2?"},
        {"from": "gpt", "value": "It is 4."},
        {"from": "human", "value": "Thanks!"},
    ])
    assert scanner._detect_chatlog_pattern(sharegpt) is True


def test_no_regression_on_string_jsonl(scanner):
    convo = _jsonl(
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
        {"role": "user", "content": "bye"},
    )
    assert scanner._detect_chatlog_pattern(convo) is True


# --- Extraction extends to tool turns (RFC §4) ---

def test_extraction_counts_tool_turns(scanner):
    """turn_count includes the thinking/tool_use/tool_result turns, not only prose."""
    meta = scanner._extract_chatlog_metadata(AGENTIC)
    assert meta is not None
    assert meta["turn_count"] == 5                     # all 5 turns counted
    # both speakers present in per-speaker counts
    counts = meta.get("speaker_turn_counts", {})
    assert counts.get("user") == 2 and counts.get("assistant") == 3


def test_prose_signals_exclude_tool_io(scanner):
    """A tool_use/tool_result turn adds a turn but 0 chars; a thinking turn DOES
    contribute prose. (The §4 turn-vs-prose split.)"""
    pairs = dict((i, p) for i, p in enumerate(scanner._extract_json_conversation(AGENTIC)))
    # index 1 = thinking → prose present; 2 = tool_use, 3 = tool_result → empty
    assert pairs[1][1] == "Let me read the file first."   # thinking is prose
    assert pairs[2][1] == ""                              # tool_use → no prose
    assert pairs[3][1] == ""                              # tool_result → no prose


# --- Determinism: the block-type set feeds the rules_hash ---

def test_block_type_set_feeds_rules_hash():
    """The live set is enumerated in CHATLOG_RULES_DEFINITION, so editing it moves
    the rules_hash → the chatlog vector identity_digest (the determinism contract)."""
    enumerated = ",".join(sorted(CHATLOG_CONTENT_BLOCK_TYPES))
    assert enumerated in CHATLOG_RULES_DEFINITION
    # A changed set produces a different rules_hash.
    h_now = compute_rules_hash(CHATLOG_RULES_DEFINITION)
    mutated = CHATLOG_RULES_DEFINITION.replace(enumerated, enumerated + ",audio")
    assert compute_rules_hash(mutated) != h_now


def test_block_types_are_the_expected_closed_set():
    assert CHATLOG_CONTENT_BLOCK_TYPES == frozenset(
        {"text", "thinking", "tool_use", "tool_result", "image", "document"}
    )
