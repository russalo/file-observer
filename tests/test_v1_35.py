"""v1.35 — AI-session per-model usage attribution (increment 3). Falsify-first.

Today's `ai_session.usage` sums across the WHOLE session; a blended (opus+haiku) session reports one
indivisible number. v1.35 adds a provisional `ai_session.usage_by_model` — a deterministic list (real
models sorted, null bucket last) of per-model token-usage SUMS, keyed on the model CO-LOCATED with each
usage dict (measure_per_model_usage_2026-07-08.md: Claude `message.model` / OpenAI `response.model` /
Gemini `modelVersion`, all 100% co-located).

Contracts:
  - INVARIANT: `usage` == elementwise sum of `usage_by_model` (the tested v1.33 session path untouched);
  - model VERBATIM incl. markers (`<synthetic>`); model-less usage-turns → the `model: null` bucket;
  - deterministic order (real sorted, null last); bounded on hostile model-cardinality; NEVER priced.

Version axes: SCANNER 1.34.0→1.35.0 · LOGIC 1.18.0→1.19.0 · SCHEMA 1.20→1.21 · ai_session mv 1→2.
"""
from __future__ import annotations

import json
from pathlib import Path


from file_observer.scanner import (
    Scanner, ScannerConfig,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
    AI_SESSION_METHOD_VERSION, AI_SESSION_MAX_MODELS,
    AI_SESSION_USAGE_KINDS,
    ai_session_rules_fingerprint,
    build_schema_document,
)


def _analyze(text: str) -> dict | None:
    sc = Scanner(source_dir=Path("."), config=ScannerConfig(enable_specialists=True))
    return sc._extract_ai_session(text)


def _scan(tmp_path: Path, name: str, content: str):
    (tmp_path / name).write_text(content, encoding="utf-8")
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    return next(r for r in m.files if r.path.endswith(name)), m


def _jsonl(objs): return "\n".join(json.dumps(o) for o in objs)


def _assert_invariant(ai):
    """usage == elementwise sum of usage_by_model — the load-bearing contract."""
    usage = ai["usage"]; ubm = ai["usage_by_model"]
    for kind in AI_SESSION_USAGE_KINDS:
        per = [e[kind] for e in ubm if e.get(kind) is not None]
        summed = sum(per) if per else None
        assert usage.get(kind) == summed, f"{kind}: session {usage.get(kind)} != sum-of-models {summed}"
    assert usage["turns_with_usage"] == sum(e["turns_with_usage"] for e in ubm)


# --- fixtures ---------------------------------------------------------------
BLENDED = _jsonl([
    {"type": "assistant", "message": {"id": "msg_1", "model": "claude-opus-4-8",
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}}},
    {"type": "assistant", "message": {"id": "msg_2", "model": "claude-opus-4-8",
        "usage": {"input_tokens": 20, "output_tokens": 7, "cache_read_input_tokens": 200}}},
    {"type": "assistant", "message": {"id": "msg_3", "model": "claude-opus-4-6",
        "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0}}},
])


class TestPerModelSplit:
    def test_blended_session_splits_by_model(self):
        ai = _analyze(BLENDED)
        assert ai is not None
        ubm = ai["usage_by_model"]
        by = {e["model"]: e for e in ubm}
        assert set(by) == {"claude-opus-4-8", "claude-opus-4-6"}
        assert by["claude-opus-4-8"]["turns_with_usage"] == 2
        assert by["claude-opus-4-8"]["input_tokens"] == 30 and by["claude-opus-4-8"]["output_tokens"] == 12
        assert by["claude-opus-4-6"]["turns_with_usage"] == 1
        assert by["claude-opus-4-6"]["input_tokens"] == 100 and by["claude-opus-4-6"]["output_tokens"] == 50

    def test_invariant_usage_equals_sum_of_models(self):
        _assert_invariant(_analyze(BLENDED))

    def test_session_usage_still_present_and_correct(self):
        # the v1.33 session path is untouched → session sums stay the blended totals
        u = _analyze(BLENDED)["usage"]
        assert u["input_tokens"] == 130 and u["output_tokens"] == 62 and u["turns_with_usage"] == 3

    def test_deterministic_order_real_sorted_null_last(self):
        text = _jsonl([
            {"message": {"id": "msg_z", "model": "zeta", "usage": {"input_tokens": 1}}},
            {"message": {"id": "msg_a", "model": "alpha", "usage": {"input_tokens": 1}}},
            {"message": {"id": "msg_n", "usage": {"input_tokens": 1}}},  # no model → null
        ])
        models = [e["model"] for e in _analyze(text)["usage_by_model"]]
        assert models == ["alpha", "zeta", None]


class TestObserveDontInterpret:
    def test_synthetic_marker_kept_verbatim(self):
        # `<synthetic>` is a real Claude Code model-field value (not a model) — fo emits it verbatim;
        # the interpreter decides what's a "real" model. Filtering would be interpretation.
        text = _jsonl([
            {"message": {"id": "msg_1", "model": "claude-opus-4-8", "usage": {"input_tokens": 10, "output_tokens": 5}}},
            {"message": {"id": "msg_2", "model": "<synthetic>", "usage": {"input_tokens": 0, "output_tokens": 0}}},
        ])
        by = {e["model"]: e for e in _analyze(text)["usage_by_model"]}
        assert "<synthetic>" in by
        assert by["<synthetic>"]["turns_with_usage"] == 1 and by["<synthetic>"]["input_tokens"] == 0

    def test_model_less_turn_goes_to_null_bucket(self):
        text = _jsonl([
            {"message": {"id": "msg_1", "model": "gpt-x", "usage": {"input_tokens": 10}}},
            {"message": {"id": "msg_2", "usage": {"input_tokens": 7}}},  # no model key
        ])
        by = {e["model"]: e for e in _analyze(text)["usage_by_model"]}
        assert None in by and by[None]["input_tokens"] == 7

    def test_empty_model_folds_to_null(self):
        # leg-4 v1.35: an empty/whitespace model string is functionally "no model" → the null bucket,
        # not its own (first-sorting) bucket.
        text = _jsonl([
            {"message": {"id": "msg_1", "model": "", "usage": {"input_tokens": 3}}},
            {"message": {"id": "msg_2", "model": "  ", "usage": {"input_tokens": 4}}},
        ])
        by = {e["model"]: e for e in _analyze(text)["usage_by_model"]}
        assert set(by) == {None} and by[None]["input_tokens"] == 7

    def test_never_priced(self):
        # The never-priced bright line = fo never DERIVES or EMITS a cost VALUE. fo's CANONICAL surface
        # (the entry keys — model/turns_with_usage/the token kinds) is a closed token-only set → price-free
        # by construction, and the values are int token counts, never a monetary float. `raw_keys` is
        # DELIBERATELY excluded: it is a VERBATIM echo of the vendor's key NAMES (no values), and scrubbing
        # it would be interpretation + break reconstructibility (observe-don't-interpret — the deeper charter).
        # A vendor's own cost-key NAME, if any, is reported as observed; no price VALUE is ever surfaced.
        # (leg-2/gem-pro asked to check raw_keys; leg-4/Codex showed that guarantee is unenforceable-by-code
        #  and would require a scrub — so the principled fix scopes never-priced to the canonical surface.)
        ai = _analyze(BLENDED)
        banned = ("price", "cost", "usd", "dollar", "$")
        for e in ai["usage_by_model"]:
            for k in e.keys():
                assert not any(b in k.lower() for b in banned), f"priced key in canonical surface: {k}"
            for kind in AI_SESSION_USAGE_KINDS:
                assert e.get(kind) is None or isinstance(e[kind], int), f"{kind} is not an int token count"


class TestCrossVendor:
    def test_openai_responses_per_model(self):
        text = _jsonl([
            {"id": "resp_1", "object": "response", "model": "gpt-5.5-2026-04-23",
             "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}},
        ])
        ai = _analyze(text)
        assert ai["usage_by_model"][0]["model"] == "gpt-5.5-2026-04-23"
        _assert_invariant(ai)

    def test_cross_vendor_single_log_splits_by_model(self):
        # leg-1 review (Finding 2): a single log mixing an Anthropic `msg_` turn and an OpenAI `resp_`
        # turn → two buckets — the realistic blended case; buckets key on the model string, vendor-agnostic.
        text = _jsonl([
            {"message": {"id": "msg_1", "model": "claude-opus-4-8", "usage": {"input_tokens": 10, "output_tokens": 5}}},
            {"id": "resp_1", "object": "response", "model": "gpt-5.5", "usage": {"input_tokens": 20, "output_tokens": 7}},
        ])
        ai = _analyze(text)
        by = {e["model"]: e for e in ai["usage_by_model"]}
        assert set(by) == {"claude-opus-4-8", "gpt-5.5"}
        _assert_invariant(ai)

    def test_gemini_generatecontent_per_model(self):
        text = _jsonl([
            {"modelVersion": "gemini-2.5-flash", "responseId": "r1",
             "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
             "candidates": [{"content": {"role": "model", "parts": [{"text": "hi"}]}}]},
        ])
        ai = _analyze(text)
        assert ai is not None and ai["usage_by_model"][0]["model"] == "gemini-2.5-flash"
        _assert_invariant(ai)


class TestBoundedAndDeterministic:
    def test_hostile_model_cardinality_is_bounded_invariant_holds(self):
        # a per-turn-unique-model log must not blow up output; overflow folds to null, sums stay complete
        text = _jsonl([
            {"message": {"id": f"msg_{i}", "model": f"model-{i:04d}", "usage": {"input_tokens": 1, "output_tokens": 1}}}
            for i in range(AI_SESSION_MAX_MODELS + 20)
        ])
        ai = _analyze(text)
        assert len(ai["usage_by_model"]) <= AI_SESSION_MAX_MODELS + 1   # + the null overflow bucket
        _assert_invariant(ai)   # every token still counted

    def test_workers_byte_identical(self, tmp_path):
        (tmp_path / "s.jsonl").write_text(BLENDED, encoding="utf-8")
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=1)).scan()
        m2 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.manifest_checksum == m2.manifest_checksum

    def test_e2e_scan_surfaces_usage_by_model(self, tmp_path):
        # a full is_chatlog-tripping session log surfaces usage_by_model in the manifest
        log = _jsonl([
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi please help me out today"}]},
             "parentUuid": None, "sessionId": "s", "cwd": "/x", "version": "2.1"},
            {"type": "assistant", "message": {"id": "msg_1", "role": "assistant", "model": "claude-opus-4-8",
                "content": [{"type": "text", "text": "sure I can help you with that"}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5}}, "sessionId": "s"},
            {"type": "assistant", "message": {"id": "msg_2", "role": "assistant", "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "and here is a quick follow up for you"}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 4, "output_tokens": 2}}, "sessionId": "s"},
        ])
        rec, _ = _scan(tmp_path, "s.jsonl", log)
        ubm = rec.specialist_metadata["ai_session"]["usage_by_model"]
        assert {e["model"] for e in ubm} == {"claude-opus-4-8", "claude-haiku-4-5"}


class TestVersioningAndSchema:
    def test_version_floor(self):
        def _v(s): return tuple(int(p) for p in s.split("."))
        assert _v(SCANNER_VERSION) >= (1, 35, 0)
        assert _v(LOGIC_VERSION) >= (1, 19, 0)
        assert _v(SCHEMA_VERSION) >= (1, 21)
        assert AI_SESSION_METHOD_VERSION >= 2

    def test_rules_fingerprint_covers_per_model_rule(self):
        # leg-1 review (Finding 1/3): max_models GATES the per-model output (bucket cardinality) and the
        # raw-key list — they MUST be in the live fingerprint so a future edit moves rules_hash, closing
        # the silent-rule-drift class (the v1.6 rules-fingerprint lens; the doc claim "feeds the rules_hash").
        fp = ai_session_rules_fingerprint()
        assert "max_models=" in fp, "AI_SESSION_MAX_MODELS gates per-model output but is absent from the fingerprint"
        assert "max_raw_keys=" in fp
        assert "per_model=" in fp
        assert "ai_session/v2" in fp   # rules-version marker moved with the new per-model rule

    def test_usage_by_model_is_provisional_in_schema(self):
        doc = build_schema_document()
        st = next(f["stability"] for f in doc["specialists"]["fields"]["ai_session"] if f["name"] == "usage_by_model")
        assert st == "provisional"
