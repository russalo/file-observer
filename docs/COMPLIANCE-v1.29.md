# COMPLIANCE — v1.29.0

**Release:** Chatlog detection recognizes agentic (tool-turn) sessions
**RFC:** [v1.29.0_RFC_Specification.md](v1.29.0_RFC_Specification.md)
**Version axes:** SCANNER 1.28.1→1.29.0 · LOGIC 1.14.1→**1.15.0** · SCHEMA unchanged **1.16** · chatlog method_version 9→**10**
**Date:** 2026-06-27

## RFC requirement → evidence

| RFC § | Requirement | Evidence |
|---|---|---|
| §3.1 | Turn recognized when conversational role + a text-bearing block OR a distinctive agentic block | `_message_role_content` rewritten (two arms); `tests/test_v1_29.py::test_agentic_session_detected`, `test_agentic_fixture_shape`, `test_untyped_text_blocks_still_detected` |
| §3.1 | Distinctive set `{thinking, tool_use, tool_result}` (image/document dropped — leg-1 §8.1 reversal) | `CHATLOG_AGENTIC_BLOCK_TYPES`; `test_block_types_are_the_distinctive_set` |
| §3.2 | Distinctive-vocabulary gate, NOT "any content" — FP-clean vs structured JSON incl. galleries/doc-stores | `test_toolturn_gate_rejects_structured_json` + `test_generic_block_types_do_not_false_fire`; falsify-first probe `scratch/falsify_toolturn_gate.py` |
| §3.2 | Strict superset of the prior gate → 0 regressions, no True→False | Corpus validation: 23/28 → 26/28 fire; **0 regressions** across 28 logs; untyped-text backward-compat restored; 2 remaining misses are tiny stubs |
| §3.3 | Block-type set feeds `rules_hash` (determinism) | Appended to `CHATLOG_RULES_DEFINITION` derived from the live `CHATLOG_AGENTIC_BLOCK_TYPES`; `test_block_type_set_feeds_rules_hash` |
| §4 | Extraction extends: turn-counting signals count tool turns | `test_extraction_counts_tool_turns` (turn_count==5, speaker counts incl. tool turns) |
| §4 | Prose signals stay authored-language only (text+thinking; tool I/O excluded) | `test_prose_signals_exclude_tool_io` (tool_use/tool_result → empty prose; thinking → prose) |
| §5 | `is_chatlog` strictly additive (no True→False) | Validation: 0 regressions; superset gate |
| §6 | Determinism / workers byte-identical | workers=1-vs-4 byte-identical on a real agentic log (manifest_checksum `e228a564…`) |
| §6 | No regression on string-content formats | `test_no_regression_on_sharegpt`, `test_no_regression_on_string_jsonl` |

## Test outcome

- `tests/test_v1_29.py` — **12 passed** (falsify-first + recovery + extraction + determinism).
- Full suite — **1207 passed**, 0 failures.
- Version-surface + doc drift guards updated and green (SCANNER/LOGIC/method_version pins, README, PUBLIC_CONTRACT §3, CONVENTIONS §1.1, SCHEMA.md + manifest.schema.json regenerated).

## Measure-first / falsify-first (the de-risk that preceded the RFC)

- Real-corpus measurement: `scratch/chatlog_corpus_findings_2026-06-27.md` — 5/28 FN (3 real, 2 tiny stubs), 0 FP; root cause grounded (text-centric counting, not the read window — two false leads ruled out).
- Falsify-first probe: `scratch/falsify_toolturn_gate.py` — broke the naive LOOSE gate (false-fired on all 4 adversarial fixtures), validated TIGHT (recover 3, 0 regress, 0 FP).

## Four-leg review

| Leg | Status |
|---|---|
| In-house multi-agent swarm | ✅ **2 HIGH findings, both fixed** — (1) untyped-text-block regression (True→False): text-bearing arm restored; (2) image/document FP surface (galleries/doc-stores/telemetry): generic types dropped, set narrowed to distinctive `{thinking,tool_use,tool_result}`. Both grounded against the parent commit before fixing; falsify-first corpus extended. Findings logged in `scratch/review/v1.29_findings.md`. |
| Gemini cross-model | ✅ **PRO (Gemini 3.1 Pro via Antigravity `agy`) red-team — 5 findings, grounded:** **3 actioned** — F3A (pure tool-execution log false-fires, all-empty prose) → detection now requires ≥1 prose turn; F1 (sibling `message` prose lost behind an empty `content` agentic block) → recognition no longer short-circuits; F3B (image/document caption fires the text-bearing arm) → generic-block captions excluded. **3 refuted by repro** — F2A (claimed crash on string blocks: the `isinstance(b, dict)` guard is present), F2B (nested `{message:{text}}`: pre-existing, non-standard), F4 (frozenset nondeterminism: output iterates the ordered block list, not the set; rules_hash uses `sorted()`). flash (`gemini` CLI) timed out; PRO covered the leg. Logged in `scratch/review/v1.29_findings.md`. |
| Empirical corpus sweep | ✅ 28-log recover/regress validation (3 recovered, 0 regressed; 26/28 unchanged through both review rounds) + workers=1-vs-4 byte-identical on a real agentic log |
| PR bots (Codex / Gemini / Copilot) | _(fire on PR open)_ |

_(PR-bot leg completes at PR; findings logged in `scratch/review/`.)_
