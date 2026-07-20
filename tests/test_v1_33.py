"""v1.33 — AI-session observation, increment 1: token usage + producer-schema fingerprint.

Falsify-first (written BEFORE implementation). A new provisional `ai_session` namespace, emitted
on is_chatlog-detected AI session logs, carrying:
  - a producer-schema fingerprint (vendor/surface/models/id_prefix/object_types/schema_mismatch),
    anchored on id-prefix + object-type (NOT the usage-key vocab — the OpenAI Responses API
    collides with Anthropic on `input_tokens`, measure_ai_session_2026-07-05.md §"Leg 2");
  - a usage sub-block: per-session token SUMS mapped to canonical fo names, null-per-absent, with
    the vendor's raw usage keys preserved verbatim (reconstructibility). Sums only; NEVER priced.

Fixtures are grounded in the real envelopes captured 2026-07-05
(scratch/ai_session_samples/): Claude Code (Anthropic), OpenAI /v1/responses, Gemini generateContent.

Version axes: SCANNER 1.32.0→1.33.0 · LOGIC 1.16.0→1.17.0 · SCHEMA 1.18→1.19 · new ai_session vector.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    AI_SESSION_NAMESPACE,
    AI_SESSION_VECTOR_ID,
    ai_session_rules_fingerprint,
    build_schema_document,
)


# --------------------------------------------------------------------------- fixtures
# Anthropic / Claude Code — multi-turn JSONL (trips is_chatlog via type+message).
# Real shape: message.usage carries input/output/cache_read/cache_creation; id `msg_`;
# CC wrapper keys parentUuid/sessionId/cwd/version → surface=claude_code.
CLAUDE_CODE = "\n".join(json.dumps(o) for o in [
    {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hello there, can you help me today please"}]},
     "parentUuid": None, "sessionId": "s1", "cwd": "/srv/x", "gitBranch": "main", "version": "2.1.201"},
    {"type": "assistant", "message": {"id": "msg_01A", "role": "assistant", "model": "claude-opus-4-8",
        "content": [{"type": "text", "text": "yes of course I can help you with that task"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 6, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 100}},
     "parentUuid": "u1", "sessionId": "s1"},
    {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "great, then please write the function for me"}]},
     "sessionId": "s1"},
    {"type": "assistant", "message": {"id": "msg_01B", "role": "assistant", "model": "claude-opus-4-8",
        "content": [{"type": "thinking", "thinking": "planning"}, {"type": "text", "text": "here is the function you asked for"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 20, "output_tokens": 8, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 0}},
     "sessionId": "s1"},
])

# OpenAI Chat Completions — one response per line + user turns (chatcmpl-/chat.completion).
OPENAI_CHAT = "\n".join(json.dumps(o) for o in [
    {"role": "user", "content": "hello can you help me with something today"},
    {"id": "chatcmpl-1", "object": "chat.completion", "model": "gpt-4o-2024-08-06",
     "choices": [{"index": 0, "message": {"role": "assistant", "content": "yes I can certainly help you"}, "finish_reason": "stop"}],
     "usage": {"prompt_tokens": 9, "completion_tokens": 7, "total_tokens": 16}},
    {"role": "user", "content": "thanks, now please explain how it works"},
    {"id": "chatcmpl-2", "object": "chat.completion", "model": "gpt-4o-2024-08-06",
     "choices": [{"index": 0, "message": {"role": "assistant", "content": "sure, it works like this here"}, "finish_reason": "stop"}],
     "usage": {"prompt_tokens": 15, "completion_tokens": 11, "total_tokens": 26,
               "completion_tokens_details": {"reasoning_tokens": 4}}},
])

# OpenAI Responses (codex) — resp_/object:"response"; usage collides w/ Anthropic on input_tokens.
OPENAI_RESPONSES = "\n".join(json.dumps(o) for o in [
    {"role": "user", "content": "hello please help me with a coding task today"},
    {"id": "resp_01a", "object": "response", "model": "gpt-5.5-2026-04-23",
     "output": [{"type": "reasoning"}, {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "yes I will help you code that"}]}],
     "usage": {"input_tokens": 19, "output_tokens": 20, "total_tokens": 39,
               "input_tokens_details": {"cached_tokens": 0},
               "output_tokens_details": {"reasoning_tokens": 13}}},
    {"role": "user", "content": "great, now add error handling to it please"},
    {"id": "resp_01b", "object": "response", "model": "gpt-5.5-2026-04-23",
     "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done, here it is now"}]}],
     "usage": {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42,
               "output_tokens_details": {"reasoning_tokens": 5}}},
])

# Gemini generateContent — camelCase, role "model", usageMetadata w/ thoughtsTokenCount.
GEMINI = "\n".join(json.dumps(o) for o in [
    {"candidates": [{"content": {"role": "model", "parts": [{"text": "hello, how can I help you today"}]}, "finishReason": "STOP", "index": 0}],
     "modelVersion": "gemini-2.5-flash", "responseId": "r1",
     "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 6, "totalTokenCount": 20, "thoughtsTokenCount": 7}},
    {"candidates": [{"content": {"role": "model", "parts": [{"text": "sure, here is the answer to that"}]}, "finishReason": "STOP", "index": 0}],
     "modelVersion": "gemini-2.5-flash", "responseId": "r2",
     "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 9, "totalTokenCount": 40, "thoughtsTokenCount": 19}},
    {"candidates": [{"content": {"role": "model", "parts": [{"text": "let me elaborate a bit more for you"}]}, "finishReason": "STOP", "index": 0}],
     "modelVersion": "gemini-2.5-flash", "responseId": "r3",
     "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 4, "totalTokenCount": 30, "thoughtsTokenCount": 6}},
])

# A plain conversational chatlog (ConvoKit-style): roles + content, NO usage, NO vendor tell.
CONVOKIT = "\n".join(json.dumps(o) for o in [
    {"speaker": "alice", "text": "hello there how are you doing today my friend"},
    {"speaker": "bob", "text": "I am doing quite well thank you for asking"},
    {"speaker": "alice", "text": "that is wonderful news I am glad to hear it"},
    {"speaker": "bob", "text": "yes it has been a very good week so far"},
])


def _analyze(text: str) -> dict | None:
    """Unit call into the extractor (decoupled from is_chatlog gating)."""
    sc = Scanner(source_dir=Path("."), config=ScannerConfig(enable_specialists=True))
    return sc._extract_ai_session(text)


def _scan(tmp_path: Path, name: str, content: str, specialists=True):
    (tmp_path / name).write_text(content, encoding="utf-8")
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=specialists)).scan()
    return next(r for r in m.files if r.path.endswith(name)), m


# --------------------------------------------------------------------------- version
def test_version_surfaces():
    assert tuple(map(int, SCANNER_VERSION.split("."))) >= (1, 33, 0), SCANNER_VERSION
    assert tuple(map(int, SCHEMA_VERSION.split("."))) >= (1, 19), SCHEMA_VERSION
    assert tuple(map(int, LOGIC_VERSION.split("."))) >= (1, 17, 0), LOGIC_VERSION


# --------------------------------------------------------------------------- fingerprint (unit)
class TestProducerFingerprint:
    def test_anthropic_claude_code(self):
        a = _analyze(CLAUDE_CODE)
        assert a is not None
        assert a["vendor"] == "anthropic"
        assert a["surface"] == "claude_code"
        assert a["id_prefix"] == "msg_"
        assert a["models"] == ["claude-opus-4-8"]
        assert a["schema_mismatch"] is False

    def test_openai_chat(self):
        a = _analyze(OPENAI_CHAT)
        assert a["vendor"] == "openai"
        assert a["surface"] == "openai_chat"
        assert a["id_prefix"] == "chatcmpl-"
        assert a["object_types"] == ["chat.completion"]

    def test_openai_responses(self):
        # The collision case: input_tokens vocab == Anthropic, but resp_/object:response disambiguate.
        a = _analyze(OPENAI_RESPONSES)
        assert a["vendor"] == "openai"
        assert a["surface"] == "openai_responses"
        assert a["id_prefix"] == "resp_"
        assert a["object_types"] == ["response"]

    def test_gemini(self):
        a = _analyze(GEMINI)
        assert a["vendor"] == "google"
        assert a["surface"] == "gemini_generatecontent"
        assert a["models"] == ["gemini-2.5-flash"]

    def test_plain_chatlog_has_no_ai_session(self):
        # No producer fingerprint and no usage → not an AI-session observation.
        assert _analyze(CONVOKIT) is None

    def test_schema_mismatch_signal(self):
        # model self-claims claude-* but the envelope is unmistakably OpenAI (chatcmpl/choices).
        text = "\n".join(json.dumps(o) for o in [
            {"role": "user", "content": "hi there please help me today"},
            {"id": "chatcmpl-x", "object": "chat.completion", "model": "claude-opus-4-8",
             "choices": [{"message": {"role": "assistant", "content": "sure I can help you"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9}},
            {"role": "user", "content": "thanks that is very helpful indeed"},
        ])
        a = _analyze(text)
        assert a["vendor"] == "openai"           # structure wins
        assert "claude-opus-4-8" in a["models"]  # self-claim surfaced verbatim
        assert a["schema_mismatch"] is True


# --------------------------------------------------------------------------- usage (unit)
class TestUsage:
    def test_anthropic_sums_and_nulls(self):
        u = _analyze(CLAUDE_CODE)["usage"]
        assert u["turns_with_usage"] == 2
        assert u["input_tokens"] == 30
        assert u["output_tokens"] == 14
        assert u["cache_read_tokens"] == 50
        assert u["cache_creation_tokens"] == 100
        assert u["reasoning_tokens"] is None   # Anthropic folds reasoning into output
        assert u["total_tokens"] is None       # CC usage states no total → null, not synthesized
        assert "input_tokens" in u["raw_keys"]

    def test_openai_chat_maps_prompt_completion(self):
        u = _analyze(OPENAI_CHAT)["usage"]
        assert u["input_tokens"] == 24          # 9 + 15
        assert u["output_tokens"] == 18         # 7 + 11
        assert u["total_tokens"] == 42          # 16 + 26 (vendor-stated)
        assert u["reasoning_tokens"] == 4       # from completion_tokens_details
        assert "prompt_tokens" in u["raw_keys"]

    def test_openai_responses_reasoning_from_details(self):
        u = _analyze(OPENAI_RESPONSES)["usage"]
        assert u["input_tokens"] == 49          # 19 + 30
        assert u["output_tokens"] == 32         # 20 + 12
        assert u["reasoning_tokens"] == 18      # 13 + 5
        assert u["cache_read_tokens"] == 0      # input_tokens_details.cached_tokens

    def test_gemini_thoughts_to_reasoning(self):
        u = _analyze(GEMINI)["usage"]
        assert u["input_tokens"] == 39          # 7 + 12 + 20
        assert u["output_tokens"] == 19         # 6 + 9 + 4
        assert u["reasoning_tokens"] == 32      # thoughtsTokenCount 7 + 19 + 6
        assert u["total_tokens"] == 90          # vendor-stated totals (include thoughts)


# --------------------------------------------------------------------------- discipline / held lines
class TestHeldLines:
    def test_never_prices(self):
        # No cost/price/dollar/budget anywhere in the emitted structure (the bright line).
        blob = json.dumps(_analyze(OPENAI_RESPONSES)).lower()
        for banned in ("cost", "price", "dollar", "usd", "$", "budget", "expensive"):
            assert banned not in blob, banned

    @pytest.mark.parametrize("bad", [
        {"input_tokens": "lots"},                 # non-int
        {"input_tokens": -5},                     # negative
        {"input_tokens": 10 ** 15},               # absurd
        {"input_tokens": [1, 2, 3]},              # wrong type
        {"input_tokens": None},                   # null
    ])
    def test_untrusted_usage_never_crashes_and_is_bounded(self, bad):
        text = "\n".join(json.dumps(o) for o in [
            {"role": "user", "content": "hello please help me out here today"},
            {"id": "msg_z", "role": "assistant", "model": "claude-opus-4-8",
             "content": [{"type": "text", "text": "sure thing I can help you"}], "stop_reason": "end_turn", "usage": bad},
            {"role": "user", "content": "thank you very much for the help"},
        ])
        a = _analyze(text)          # must not raise
        if a and a.get("usage"):
            v = a["usage"]["input_tokens"]
            assert v is None or (isinstance(v, int) and 0 <= v < 10 ** 13)


# --------------------------------------------------------------------------- review hardening (4-leg)
class TestReviewHardening:
    """Locks the four-leg review findings (leg-1 in-house swarm + leg-2 OpenAI)."""

    def test_non_token_usage_dict_does_not_fire(self):
        # leg-1/leg-2 FP: a dict merely NAMED `usage` but carrying no recognized token key
        # (telemetry/quota) must NOT be treated as an AI usage block.
        text = "\n".join(json.dumps(o) for o in [
            {"speaker": "a", "text": "hello there how are you doing today"},
            {"speaker": "b", "text": "i am well thanks, usage was high today", "usage": {"cpu": 5, "memory": 200}},
            {"speaker": "a", "text": "that is good to hear my friend indeed"},
        ])
        assert _analyze(text) is None

    def test_bare_generic_fingerprint_without_usage_does_not_fire(self):
        # leg-1: `object:"response"` / bare `msg_` id are generic — must not fire without real usage.
        text = "\n".join(json.dumps(o) for o in [
            {"object": "response", "role": "user", "content": "hi there please help me out"},
            {"id": "msg_00042", "role": "assistant", "content": "sure thing I can help you today"},
            {"role": "user", "content": "thanks that is really very helpful of you"},
        ])
        assert _analyze(text) is None

    def test_object_types_cardinality_capped(self):
        # leg-1: object_types must be bounded (was the lone uncapped surfaced set).
        from file_observer.scanner import AI_SESSION_MAX_OBJECT_TYPES
        lines = [json.dumps({"role": "user", "content": "hi please help me out today"}),
                 json.dumps({"id": "msg_x", "role": "assistant", "content": "ok I can help",
                             "usage": {"input_tokens": 5, "output_tokens": 3}})]
        lines += [json.dumps({"object": f"t{i}", "usage": {"input_tokens": 1}}) for i in range(500)]
        a = _analyze("\n".join(lines))
        assert a is not None and len(a["object_types"]) <= AI_SESSION_MAX_OBJECT_TYPES

    def test_deeply_nested_json_line_never_crashes(self):
        # leg-1: a bounded-size but deeply-nested line raises RecursionError in json.loads — caught.
        deep = "[" * 4000 + "]" * 4000
        text = "\n".join([
            json.dumps({"id": "msg_a", "role": "assistant", "content": "hello I can help you",
                        "usage": {"input_tokens": 5, "output_tokens": 3}}),
            deep,
            json.dumps({"role": "user", "content": "thanks very much for the help today"}),
            json.dumps({"role": "user", "content": "one more question for you please friend"}),
        ])
        a = _analyze(text)  # must not raise
        assert a is None or a["usage"]["input_tokens"] == 5

    def test_models_deduped_on_truncated_value(self):
        from file_observer.scanner import AI_SESSION_MAX_STR
        long_a = "m" * AI_SESSION_MAX_STR + "AAA"
        long_b = "m" * AI_SESSION_MAX_STR + "BBB"   # distinct, share the first MAX_STR chars
        text = "\n".join(json.dumps(o) for o in [
            {"role": "user", "content": "hello please help me out here today"},
            {"id": "msg_1", "role": "assistant", "model": long_a, "content": "one",
             "usage": {"input_tokens": 5, "output_tokens": 2}},
            {"id": "msg_2", "role": "assistant", "model": long_b, "content": "two",
             "usage": {"input_tokens": 6, "output_tokens": 3}},
        ])
        models = _analyze(text)["models"]
        assert len(models) == len(set(models)), models   # no duplicate truncated entries

    def test_internal_usage_cap_sets_truncated(self, monkeypatch):
        # leg-4 (Codex P2 + CodeRabbit MAJOR, converged): hitting the in-memory usage-dict cap — not
        # just the 64MB byte cap — must flag `truncated` (partial sums honest at EVERY layer).
        import file_observer.scanner as S
        monkeypatch.setattr(S, "AI_SESSION_MAX_USAGE_DICTS", 3)
        lines = []
        for i in range(6):
            lines.append(json.dumps({"role": "user", "content": f"question {i} please help me here today"}))
            lines.append(json.dumps({"id": f"msg_{i}", "role": "assistant", "content": "ok here you go now",
                                     "usage": {"input_tokens": 10, "output_tokens": 5}}))
        u = _analyze("\n".join(lines))["usage"]
        assert u["truncated"] is True
        assert u["turns_with_usage"] == 3   # capped, not the full 6

    def test_pretty_printed_single_document_parsed(self):
        # leg-4 (gemini HIGH): a pretty-printed single JSON doc (array of turns) must be parsed as one
        # value via the whole-doc-first path, not lost to premature line-by-line parsing.
        doc = json.dumps([
            {"id": "msg_1", "role": "assistant", "model": "claude-opus-4-8", "content": "hi there friend",
             "usage": {"input_tokens": 10, "output_tokens": 5}},
            {"role": "user", "content": "thanks so much for the help today"},
            {"id": "msg_2", "role": "assistant", "content": "you are very welcome indeed",
             "usage": {"input_tokens": 8, "output_tokens": 4}},
        ], indent=2)
        a = _analyze(doc)
        assert a is not None
        assert a["vendor"] == "anthropic"
        assert a["usage"]["input_tokens"] == 18   # both turns summed from the outer structure

    def test_id_prefix_consistent_with_vendor(self):
        # leg-1: on a mixed log, id_prefix must not contradict the vendor decision.
        text = "\n".join(json.dumps(o) for o in [
            {"role": "user", "content": "hi there please help me with this today"},
            {"id": "chatcmpl-1", "object": "chat.completion", "model": "gpt-4o",
             "choices": [{"message": {"role": "assistant", "content": "sure I can help"}}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
            {"id": "msg_stray", "role": "assistant", "content": "an unrelated anthropic-looking id"},
            {"role": "user", "content": "thanks that is helpful to me indeed"},
        ])
        a = _analyze(text)
        assert a["vendor"] == "openai"
        assert a["id_prefix"] in ("chatcmpl-", None)   # never "msg_" while vendor is openai


# --------------------------------------------------------------------------- e2e (scan → manifest)
class TestEndToEnd:
    def test_claude_code_emits_ai_session_namespace(self, tmp_path):
        rec, _ = _scan(tmp_path, "session.jsonl", CLAUDE_CODE)
        assert rec.is_chatlog is True
        ns = (rec.specialist_metadata or {}).get(AI_SESSION_NAMESPACE)
        assert ns is not None
        assert ns["vendor"] == "anthropic"
        assert ns["usage"]["input_tokens"] == 30

    def test_plain_chatlog_no_ai_session(self, tmp_path):
        rec, _ = _scan(tmp_path, "convo.jsonl", CONVOKIT)
        assert rec.is_chatlog is True                      # still a chatlog
        assert not (rec.specialist_metadata or {}).get(AI_SESSION_NAMESPACE)

    def test_specialists_off_no_ai_session(self, tmp_path):
        rec, _ = _scan(tmp_path, "session.jsonl", CLAUDE_CODE, specialists=False)
        assert not (rec.specialist_metadata or {}).get(AI_SESSION_NAMESPACE)

    def test_vector_registered_with_rules_hash(self, tmp_path):
        _, m = _scan(tmp_path, "session.jsonl", CLAUDE_CODE)
        from file_observer.scanner import compute_rules_hash
        vec = next((v for v in m.vectors_collected if v["vector_id"] == AI_SESSION_VECTOR_ID), None)
        assert vec is not None
        assert vec["rules_hash"] == compute_rules_hash(ai_session_rules_fingerprint())
        assert vec["method_version"] >= 1
        assert vec["applied_to_count"] >= 1

    def test_full_file_read_not_truncated_to_baseline_window(self, tmp_path):
        # A1 (leg-1 headline): a session larger than the ~64KB baseline window must report the FULL
        # usage totals via the bounded-deviation full-file read, not a silently-partial windowed sum.
        N = 1200  # >64KB of JSONL (each pair ~200B) — far past baseline_max_bytes
        lines = []
        for i in range(N):
            user = {"type": "user", "message": {"role": "user",
                    "content": [{"type": "text", "text": f"question number {i} please help me with this"}]},
                    "sessionId": "s", "parentUuid": None, "cwd": "/x"}
            asst = {"type": "assistant", "message": {"id": f"msg_{i}", "role": "assistant",
                    "model": "claude-opus-4-8",
                    "content": [{"type": "text", "text": f"answer number {i} here it is"}],
                    "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5}},
                    "sessionId": "s"}
            lines.append(json.dumps(user))
            lines.append(json.dumps(asst))
        rec, _ = _scan(tmp_path, "big.jsonl", "\n".join(lines))
        u = rec.specialist_metadata["ai_session"]["usage"]
        assert u["turns_with_usage"] == N, f"windowed to {u['turns_with_usage']} of {N}"
        assert u["input_tokens"] == 10 * N
        assert u["truncated"] is False

    def test_deterministic_across_workers(self, tmp_path):
        (tmp_path / "session.jsonl").write_text(CLAUDE_CODE, encoding="utf-8")
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=1)).scan()
        m2 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.manifest_checksum == m2.manifest_checksum


# --------------------------------------------------------------------------- schema surface
def test_ai_session_in_schema_as_provisional():
    # leg-4/CodeRabbit: the test name says "in_schema" — actually ASSERT on the generated schema
    # document (the discarded lookup gave no regression signal; the test passed even if ai_session
    # were absent from --schema).
    doc = build_schema_document()
    # per-namespace field-stability lives under specialists.fields[ns] (the original code looked in
    # ["namespaces"] — the wrong key — so its lookup silently returned None and asserted nothing).
    ns_fields = doc.get("specialists", {}).get("fields", {})
    assert AI_SESSION_NAMESPACE in ns_fields, "ai_session namespace missing from the --schema document"
    fields = ns_fields[AI_SESSION_NAMESPACE]
    assert fields, "ai_session has no fields in --schema"
    assert all(f.get("stability") == "provisional" for f in fields), \
        "every ai_session field must be annotated provisional in --schema"
    # and the schema must agree EXACTLY with the code registry — not just "present" (leg-4/CodeRabbit:
    # otherwise --schema could silently drop a registered ai_session field and the test would pass).
    from file_observer.scanner import SPECIALIST_FIELDS, PROVISIONAL_SPECIALIST_FIELDS
    assert AI_SESSION_NAMESPACE in SPECIALIST_FIELDS
    assert {f["name"] for f in fields} == set(SPECIALIST_FIELDS[AI_SESSION_NAMESPACE]), \
        "--schema ai_session fields must exactly match SPECIALIST_FIELDS (no field dropped/added)"
    assert any(ns == AI_SESSION_NAMESPACE for ns, _ in PROVISIONAL_SPECIALIST_FIELDS)


def test_rules_fingerprint_is_stable_string():
    fp = ai_session_rules_fingerprint()
    assert isinstance(fp, str) and len(fp) > 0
