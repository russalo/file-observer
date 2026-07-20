"""v1.34 — chatlog session axes: first_timestamp / last_timestamp / cwd (recall#62), falsify-first.

Three new FLAT top-level scalars in the chatlog block:
  - first_timestamp / last_timestamp = min/max turn timestamp, parsed (recognized-key set, ISO string
    OR numeric epoch) → canonical ISO-8601 UTC (`…Z`, fixed ms precision). Null when untimestamped.
  - cwd = first-seen top-level `cwd`, verbatim, bounded, null when absent.
Deterministic pure function of the file. Measure-first grounded the key set + format variance on real
corpora (scratch/measure_chatlog_timestamps_2026-07-07.md): Claude Code `timestamp` Z/ms; oasst
`created_date` +00:00/µs (nested); ChatGPT `create_time` epoch-float; cwd single-valued per session.

Version axes: SCANNER 1.33.0→1.34.0 · LOGIC 1.17.0→1.18.0 · SCHEMA 1.19→1.20 · chatlog mv 10→11.
"""
from __future__ import annotations

import json
from pathlib import Path


from file_observer.scanner import (
    Scanner, ScannerConfig,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
    CHATLOG_METHOD_VERSION, CHATLOG_VECTOR_ID,
)


def _meta(text: str) -> dict:
    sc = Scanner(source_dir=Path("."), config=ScannerConfig(enable_specialists=True))
    return sc._extract_chatlog_metadata(text) or {}


def _scan(tmp_path: Path, name: str, content: str, specialists=True):
    (tmp_path / name).write_text(content, encoding="utf-8")
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=specialists)).scan()
    return next(r for r in m.files if r.path.endswith(name)), m


# Claude Code — timestamp Z/ms (top-level) + cwd.
CLAUDE_CODE = "\n".join(json.dumps(o) for o in [
    {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi please help me today friend"}]},
     "cwd": "/srv/projects/pkplab/scanner", "sessionId": "s", "timestamp": "2026-07-04T06:09:38.131Z"},
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "sure I can help you with that now"}]},
     "cwd": "/srv/projects/pkplab/scanner", "timestamp": "2026-07-04T06:10:12.456Z"},
    {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "thanks so much for the help"}]},
     "cwd": "/srv/projects/pkplab/scanner", "timestamp": "2026-07-04T06:11:00.789Z"},
])

# oasst — created_date +00:00/µs, NESTED in a message tree, NO cwd.
OASST = json.dumps({"messages": [
    {"role": "user", "text": "hello there friend how are you doing", "created_date": "2023-02-05T14:23:50.983374+00:00"},
    {"role": "assistant", "text": "i am well thank you very much indeed", "created_date": "2023-02-05T14:24:30.500000+00:00"},
    {"role": "user", "text": "that is good to hear my friend", "created_date": "2023-02-05T14:25:10.111222+00:00"},
]})

# ChatGPT export — create_time epoch FLOAT, nested in mapping.
CHATGPT = json.dumps({"mapping": {
    "a": {"message": {"author": {"role": "user"}, "content": {"parts": ["hello please help me out today"]}, "create_time": 1699564800.5}},
    "b": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["sure I can help you now"]}, "create_time": 1699564830.25}},
    "c": {"message": {"author": {"role": "user"}, "content": {"parts": ["thanks that is helpful indeed"]}, "create_time": 1699564860.0}},
}, "current_node": "c"})

# Prose / ConvoKit — no timestamps, no cwd.
PROSE = "Alice: hello there how are you doing today\nBob: i am well thank you for asking\nAlice: that is good to hear my friend\nBob: yes it has been a fine week\n"


def test_version_surfaces():
    assert tuple(map(int, SCANNER_VERSION.split("."))) >= (1, 34, 0), SCANNER_VERSION
    assert tuple(map(int, SCHEMA_VERSION.split("."))) >= (1, 20), SCHEMA_VERSION
    assert tuple(map(int, LOGIC_VERSION.split("."))) >= (1, 18, 0), LOGIC_VERSION
    assert CHATLOG_METHOD_VERSION >= 11


class TestTimestamps:
    def test_claude_code_z_ms_exact(self):
        m = _meta(CLAUDE_CODE)
        assert m["first_timestamp"] == "2026-07-04T06:09:38.131Z"
        assert m["last_timestamp"] == "2026-07-04T06:11:00.789Z"

    def test_oasst_offset_micros_normalized_to_canonical_z_ms(self):
        # +00:00 -> Z, microsecond -> millisecond; min/max correct on nested created_date.
        m = _meta(OASST)
        assert m["first_timestamp"] == "2023-02-05T14:23:50.983Z"
        assert m["last_timestamp"] == "2023-02-05T14:25:10.111Z"

    def test_chatgpt_epoch_float_parsed(self):
        m = _meta(CHATGPT)
        for k in ("first_timestamp", "last_timestamp"):
            assert m[k] is not None and m[k].endswith("Z") and m[k][-5] == "."  # canonical .sssZ
        assert m["first_timestamp"] < m["last_timestamp"]   # lexical == chronological on canonical

    def test_null_when_untimestamped(self):
        m = _meta(PROSE)
        assert m["first_timestamp"] is None and m["last_timestamp"] is None

    def test_unparseable_timestamp_skipped_never_crashes(self):
        text = "\n".join(json.dumps(o) for o in [
            {"role": "user", "content": "hi please help me out here today", "timestamp": "not-a-date"},
            {"role": "assistant", "content": "sure I can help you now", "timestamp": "2026-07-04T06:10:12.456Z"},
            {"role": "user", "content": "thanks very much for the help", "timestamp": {"nested": "wrong-type"}},
        ])
        m = _meta(text)   # must not raise
        assert m["first_timestamp"] == "2026-07-04T06:10:12.456Z"   # the one valid value
        assert m["last_timestamp"] == "2026-07-04T06:10:12.456Z"


class TestCwd:
    def test_first_seen_cwd(self):
        assert _meta(CLAUDE_CODE)["cwd"] == "/srv/projects/pkplab/scanner"

    def test_cwd_null_when_absent(self):
        assert _meta(OASST)["cwd"] is None
        assert _meta(PROSE)["cwd"] is None

    def test_multi_cwd_takes_first_seen(self):
        text = "\n".join(json.dumps(o) for o in [
            {"role": "user", "content": "hi help me today please friend", "cwd": "/first/dir"},
            {"role": "assistant", "content": "sure thing I can help now", "cwd": "/second/dir"},
            {"role": "user", "content": "thanks a lot for the help", "cwd": "/first/dir"},
        ])
        assert _meta(text)["cwd"] == "/first/dir"

    def test_cwd_bounded(self):
        from file_observer.scanner import CHATLOG_CWD_MAX_STR
        huge = "/" + "x" * 100000
        text = "\n".join(json.dumps(o) for o in [
            {"role": "user", "content": "hi please help me here today", "cwd": huge},
            {"role": "assistant", "content": "ok I can help you now", "cwd": huge},
            {"role": "user", "content": "thanks so much for the help", "cwd": huge},
        ])
        assert len(_meta(text)["cwd"]) <= CHATLOG_CWD_MAX_STR


class TestReviewFixes:
    """Locks the four-leg review findings (leg-1 in-house + leg-2 Gemini, converged)."""

    def test_nested_tool_payload_timestamp_not_collected(self):
        # leg-1 + leg-2 CONVERGED: a created_at inside a tool_result (e.g. `gh api` output) must NOT
        # pollute the session span — skip descending into tool_use/tool_result blocks.
        text = "\n".join(json.dumps(o) for o in [
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "look up issue 114 for me please"}]},
             "timestamp": "2026-07-04T10:00:00.000Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_result", "content": {"number": 114, "created_at": "2011-04-10T00:00:00Z", "title": "old"}}]},
             "timestamp": "2026-07-04T10:05:00.000Z"},
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "thanks for that info friend indeed"}]},
             "timestamp": "2026-07-04T10:10:00.000Z"},
        ])
        m = _meta(text)
        assert m["first_timestamp"] == "2026-07-04T10:00:00.000Z"   # NOT dragged back to 2011
        assert m["last_timestamp"] == "2026-07-04T10:10:00.000Z"

    def test_unhashable_type_does_not_crash(self):
        # leg-4/gemini: a non-string `type` (list/dict) is unhashable → `in frozenset` would TypeError.
        text = "\n".join(json.dumps(o) for o in [
            {"type": ["unhashable"], "role": "user", "content": "hi please help me out today",
             "timestamp": "2026-07-04T10:00:00.000Z"},
            {"type": {"n": 1}, "role": "assistant", "content": "sure I can help you now",
             "timestamp": "2026-07-04T10:05:00.000Z"},
            {"role": "user", "content": "thanks so much for the help", "timestamp": "2026-07-04T10:10:00.000Z"},
        ])
        m = _meta(text)   # must not raise
        assert m["first_timestamp"] == "2026-07-04T10:00:00.000Z"

    def test_ai_session_dispatch_leaves_no_error(self, tmp_path):
        # leg-4/codex: the dispatch restructure left `ai_over_cap` undefined → a NameError silently
        # swallowed into an ErrorRecord. A usage-bearing chatlog must scan cleanly with the ai_session
        # provenance intact.
        log = "\n".join(json.dumps(o) for o in [
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi please help me today"}]},
             "cwd": "/x", "timestamp": "2026-07-04T10:00:00.000Z"},
            {"type": "assistant", "message": {"id": "msg_1", "role": "assistant", "model": "claude-opus-4-8",
                "content": [{"type": "text", "text": "sure I can help you now"}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5}}, "timestamp": "2026-07-04T10:05:00.000Z"},
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "thanks for the help friend"}]},
             "timestamp": "2026-07-04T10:10:00.000Z"},
        ])
        rec, _ = _scan(tmp_path, "s.jsonl", log)
        assert rec.specialist_metadata.get("ai_session") is not None
        # a caught NameError would land here; tolerate the benign no-libmagic MIME diagnostic
        # (present on the forced-fallback + Windows CI jobs, not a crash).
        crash_errors = [e for e in rec.errors if e.code != "mime_type_fallback"]
        assert crash_errors == [], [e.code for e in crash_errors]
        # direct proof the ai_session provenance loop RAN (would be absent if it NameError'd first)
        assert any(k.startswith("specialist_metadata.ai_session.") for k in (rec.signal_provenance or {}))

    def test_year_below_1000_zero_padded(self):
        # leg-2/Gemini: %Y emits `999-…`, breaking lexical sort. Manual zero-pad keeps 4 digits.
        from file_observer.scanner import _parse_timestamp_utc, _canonical_iso_ms
        dt = _parse_timestamp_utc("0999-01-02T03:04:05.678Z")
        assert _canonical_iso_ms(dt) == "0999-01-02T03:04:05.678Z"

    def test_head_tail_reads_true_last_for_oversize_file(self, tmp_path, monkeypatch):
        # leg-1 + real-data: last_timestamp lives at the END; a front-only read truncated it on >64MiB
        # sessions. Shrink the caps so a modest file exercises the tail read.
        import file_observer.scanner as S
        monkeypatch.setattr(S, "AI_SESSION_MAX_FILE_BYTES", 20000)
        monkeypatch.setattr(S, "CHATLOG_TAIL_BYTES", 8000)
        lines = []
        for i in range(400):
            hh, mm = divmod(i, 60)
            role = "user" if i % 2 == 0 else "assistant"
            lines.append(json.dumps({"type": role, "message": {"role": role,
                "content": [{"type": "text", "text": f"turn {i} some filler content to grow the file"}]},
                "timestamp": f"2026-07-02T{hh % 24:02d}:{mm:02d}:00.000Z"}))
        rec, _ = _scan(tmp_path, "big.jsonl", "\n".join(lines))
        cl = rec.specialist_metadata["chatlog"]
        assert cl["first_timestamp"] == "2026-07-02T00:00:00.000Z"
        assert cl["last_timestamp"] == "2026-07-02T06:39:00.000Z", cl["last_timestamp"]  # i=399 → 06:39


class TestShapeAndDiscipline:
    def test_all_three_are_flat_top_level_scalars(self):
        m = _meta(CLAUDE_CODE)
        for k in ("first_timestamp", "last_timestamp", "cwd"):
            assert k in m and not isinstance(m[k], (dict, list))   # flat scalar, not nested
        assert "timestamps" not in m   # NOT a nested {first,last} object

    def test_deterministic(self):
        assert _meta(CLAUDE_CODE) == _meta(CLAUDE_CODE)


class TestEndToEnd:
    def test_jsonl_scan_carries_fields(self, tmp_path):
        rec, _ = _scan(tmp_path, "session.jsonl", CLAUDE_CODE)
        assert rec.is_chatlog is True
        cl = rec.specialist_metadata["chatlog"]
        assert cl["first_timestamp"] == "2026-07-04T06:09:38.131Z"
        assert cl["cwd"] == "/srv/projects/pkplab/scanner"

    def test_prose_chatlog_nulls(self, tmp_path):
        rec, _ = _scan(tmp_path, "convo.md", PROSE)
        cl = (rec.specialist_metadata or {}).get("chatlog")
        if cl:   # prose chatlog detected → fields present but null
            assert cl["first_timestamp"] is None and cl["cwd"] is None

    def test_full_file_span_not_windowed(self, tmp_path):
        # The session axes must span the WHOLE file via the full-file read — a session larger than the
        # ~64KB baseline window must report the TRUE last_timestamp, not the last turn inside the window.
        N = 1200  # >64KB of JSONL
        lines = []
        for i in range(N):
            hh, mm = divmod(i, 60)
            ts = f"2026-07-02T{hh % 24:02d}:{mm:02d}:00.000Z"
            role = "user" if i % 2 == 0 else "assistant"   # 2 speakers → trips is_chatlog
            lines.append(json.dumps({"type": role, "message": {"role": role,
                "content": [{"type": "text", "text": f"turn number {i} here is some content to fill the window"}]},
                "cwd": "/proj/x", "timestamp": ts}))
        rec, _ = _scan(tmp_path, "big.jsonl", "\n".join(lines))
        cl = rec.specialist_metadata["chatlog"]
        assert cl["first_timestamp"] == "2026-07-02T00:00:00.000Z"
        # last turn i=1199 → hh=19,mm=59 → 19:59; the window would cut off far earlier
        assert cl["last_timestamp"] == "2026-07-02T19:59:00.000Z", cl["last_timestamp"]
        assert cl["cwd"] == "/proj/x"

    def test_workers_byte_identical(self, tmp_path):
        (tmp_path / "s.jsonl").write_text(CLAUDE_CODE, encoding="utf-8")
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=1)).scan()
        m4 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.manifest_checksum == m4.manifest_checksum

    def test_chatlog_vector_method_version_bumped(self, tmp_path):
        _, m = _scan(tmp_path, "session.jsonl", CLAUDE_CODE)
        vec = next(v for v in m.vectors_collected if v["vector_id"] == CHATLOG_VECTOR_ID)
        assert vec["method_version"] >= 11


def test_new_fields_in_schema_as_provisional():
    from file_observer.scanner import SPECIALIST_FIELDS, PROVISIONAL_SPECIALIST_FIELDS
    for f in ("first_timestamp", "last_timestamp", "cwd"):
        assert f in SPECIALIST_FIELDS["chatlog"], f
        assert ("chatlog", f) in PROVISIONAL_SPECIALIST_FIELDS, f
