# v1.2 Spec Compliance Report

**Report Date:** 2026-05-31
**Spec:** docs/v1.2.0_RFC_Specification.md (Approved 2026-05-31)
**Implementation:** src/file_observer/scanner.py (v1.2.0)
**Prior Compliance:** docs/COMPLIANCE-v1.1.md (v1.1 — 28 requirements, all PASS)

---

## 1. Executive Summary

- **Spec:** v1.2.0 RFC — chatlog generalized & hardened detection + per-speaker structure.
- **Schema Version:** 1.2 (additive — new `chatlog` namespace fields + optional `ErrorRecord.detail`).
- **Overall:** COMPLETE — all §9 acceptance criteria met. Detection generalized across conversational schemas; markdown false positives sharply reduced; per-speaker structure added (provisional).
- **Test Count:** 595 passed, 1 skipped (was 580; +13 in `tests/test_v1_2.py`, +2 FP-guard tests in `test_unit.py`).
- **Critical Deviations:** None.
- **Behavioral change:** `LOGIC_VERSION` 1.0.0→1.1.0 and chatlog `method_version` 3→4 (detection logic + field set changed) — expected and signalled, not a contract break.

---

## 2. Generalized Conversational Detection (§2)

| # | Requirement | Implementation / evidence | Status |
|---|---|---|---|
| 1 | Recognize role keys (type/role/from/speaker/author) + content keys (text/value/content/message/body) | `CHATLOG_ROLE_FIELD_KEYS` / `CHATLOG_CONTENT_FIELD_KEYS`; `_is_message_like` | **PASS** |
| 2 | Utterance-per-line JSONL (ConvoKit) | `test_convokit_speaker_text_jsonl`; live ConvoKit utterances detected | **PASS** |
| 3 | Array-of-messages (ShareGPT from/value) | `_count_message_like` recursion + regex fallback; `test_sharegpt_from_value_json_array`; live ShareGPT detected | **PASS** |
| 4 | Nested message trees (oasst prompt.role+replies) | recursive walk; `test_oasst_nested_tree_jsonl`; live oasst1 detected | **PASS** |
| 5 | `.json` is a content-gated candidate; plain `.json` not flagged | gate adds `.json`; `test_json_extension_is_a_candidate`, `test_plain_config_json_not_flagged` | **PASS** |
| 6 | Embedded speaker dialogue in a JSON string (hh-rlhf) | `_string_has_speaker_dialogue`; `test_hh_rlhf_embedded_dialogue`; live hh-rlhf detected | **PASS** |
| 7 | Legacy `type: user/assistant` still detected (no regression) | `test_user_assistant_still_detected`; Claude/Sentinel 100% preserved | **PASS** |
| 8 | Deterministic — pure function of the bounded sample | regex/parse over `text` only; no state | **PASS** |

**Measured (live corpora):** all five previously-missed schemas (ConvoKit, movie, oasst1, hh-rlhf, ShareGPT) now detected; Claude 40 / Sentinel 3 preserved.

---

## 3. False-Positive Reduction (§3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 9 | Tighten `.md`/`.txt` structure rules; FP down, TP preserved | Rules 2/3 (H3≥5 / dividers≥3) now require a co-signal: 2+ speaker labels **or** 2+ date-stamped headers (`CHATLOG_DATE_HEADER_RE`). Prose docs have neither. | **PASS** |
| 10 | Measured FP drop + no TP regression | **FastAPI `.md` is_chatlog: 587 → ~21 (~96% drop); AutoGPT similar.** Dated-journal + transcript detection preserved (`test_five_h3_headers_triggers`, `test_three_dash_dividers_triggers`, realistic journal). Bare-structure no longer flags (`test_generic_h3_headers_no_cosignal_does_not_trigger`, headers fixture). | **PASS** |

---

## 4. Extraction Error Hygiene (§4)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 11 | Chatlog failures carry a non-empty `detail` | Added `ErrorRecord.detail` (optional, default None); chatlog probe-failed records now set `{reason, mime_type/text_chars, ...}`. `test_error_record_supports_detail` | **PASS** |

---

## 5. Per-Speaker Turn Structure (§5, provisional)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 12 | `speaker_turn_counts` {speaker: count}, sorted | computed from the unified speaker sequence (both JSON + prose modes); `test_speaker_turn_counts_and_alternation` | **PASS** |
| 13 | `speaker_turn_chars` per-speaker {avg,max,min} | from attributed turn lengths | **PASS** |
| 14 | `alternation` (longest_single_speaker_run, speaker_change_ratio) | deterministic over the speaker sequence | **PASS** |
| 15 | Pure observation — no authority/canon judgment | counts/attribution only; word-twisting study deferred (§10) | **PASS** |
| 16 | Present in both JSON and prose modes | `test_fields_present_in_prose_mode` | **PASS** |

---

## 6. Versions & Backward Compatibility (§6, §7)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 17 | SCHEMA 1.1→1.2, SCANNER 1.1.0→1.2.0, LOGIC 1.0.0→1.1.0, chatlog method_version 4 | constants + docstring + pyproject | **PASS** |
| 18 | `is_chatlog` field shape unchanged (flagging changes are LOGIC-tracked) | field unchanged; detection behavior moved under `LOGIC_VERSION` | **PASS** |
| 19 | New fields additive & provisional in PUBLIC_CONTRACT §2.4 | §2.4 lists `speaker_turn_counts`, `speaker_turn_chars`, `alternation`, `ErrorRecord.detail` | **PASS** |
| 20 | No existing field removed/renamed/retyped | additive only | **PASS** |

---

## 7. Validation (§8) & Acceptance (§9)

- Detection matrix run across the assembled corpus library (TP/FP/FN). Before/after captured in §2–§3.
- New tests for each schema, the `.json` gate, FP guards, per-speaker fields, and error detail (`tests/test_v1_2.py`, 13 tests).
- All prior tests pass (595 total); legacy `type: user/assistant` fixtures still detect.
- `twine check` PASSED; build produces `file_observer-1.2.0`.
- HISTORY / CONVENTIONS / README / PUBLIC_CONTRACT updated.

---

## 8. Compliance Verdict

**PASS — 20 requirements verified, 0 failures, 0 deviations.**

v1.2 turns the chatlog vector from one-schema-only into robust coverage across the real conversational ecosystem, cuts the markdown false-positive rate ~96%, and lays the per-speaker structural foundation for Project Sentinel — additively, with the contract intact. The word-twisting/authority study (consuming the new per-speaker structure) is deferred to future analysis against the manually-tagged RPG corpus.
