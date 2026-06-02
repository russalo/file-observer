# v1.4.0 Spec Compliance Report

**Report Date:** 2026-06-02
**Spec:** docs/v1.4.0_RFC_Specification.md
**Implementation:** src/file_observer/scanner.py (v1.4.0)
**Prior:** COMPLIANCE-v1.3.md (pure-Python MIME fallback)

---

## 1. Executive Summary

- **Feature:** content-shape chatlog detection gate — an ADDITIVE layer over the
  retained v1.2.4 machinery (stop-list → count floor). The prose rule gains
  `utterance_ratio ≥ 0.6` (function-word / punctuation / length arms), an
  FP-lexicon dominance rule, a density floor, a version/date structure
  vote-against, and a FAQ complete-set exclusion. Provisional `content_shape`
  (`utterance_ratio`/`density`) surfaced in chatlog metadata.
- **Versions:** SCANNER 1.3.0→1.4.0; **LOGIC 1.2.0→1.3.0** (detection routing);
  SCHEMA 1.2→**1.3** (additive `content_shape`); chatlog method_version 8→**9**.
- **Overall:** COMPLETE. Built falsify-first; all §10 corpus cases pass (27/27
  reference + parity), full suite green (684 passed, 1 skipped).
- **The headline honest finding (§3):** on **3,032 real doc+chat files the change
  is a 0-diff wash vs v1.2.4** — it changes behavior only on adversarial inputs
  (the real-world benefit is small; the value is adversarial-FP robustness).

## 2. Requirements (§2–§7)

| Req | Implementation | Status |
|---|---|---|
| Stop-list RETAINED (load-bearing), labels filtered before the rule | `_label_content_pairs(drop_nonspeaker=True)`, `CHATLOG_SPEAKER_STOP_LIST_CF` (full set) | PASS |
| Count floor (≥2 distinct, ≥3 total, ≥1 recurring) retained | `_prose_dialogue` §2.2.1 | PASS |
| Utterance predicate: function-word / punctuation / ≥4 words / ≥25 chars | `_is_utterance` + `CHATLOG_FUNCTION_WORDS` | PASS |
| `utterance_ratio ≥ 0.6` gate (rejects cyclic data tables) | `_prose_dialogue` | PASS |
| FP-lexicon dominance (`Added:` changelogs) | `CHATLOG_FP_LABEL_LEXICON`, ≥half distinct | PASS |
| Version-tag structure vote-against (release notes) | `CHATLOG_VERSION_HEADER_RE` (tags only; dated-journal headers excluded) | PASS |
| Density floor | PROTOTYPED, DROPPED in review (FN'd multi-line dialogue) — `density` surfaced, not gated | N/A |
| FAQ complete-set exclusion (`{question,answer,q,a,faq}`; `A:`/`B:` survives) | `CHATLOG_FAQ_LABELS` subset test | PASS |
| Rules 2/3 markdown co-signal unchanged (stop-list-filtered distinct ≥2) | restored after regression (§3) | PASS |
| JSON path parity (`_string_has_speaker_dialogue` → `_prose_dialogue`) | classmethod delegation | PASS |
| Provisional `content_shape` (null in JSONL mode) | `_chatlog_content_shape`, extraction return | PASS |
| LOGIC 1.3.0 / SCHEMA 1.3 / method_version 9 / fingerprint updated | version constants, `CHATLOG_RULES_DEFINITION` | PASS |
| No manifest field removed/renamed/retyped | additive only | PASS |

## 3. Falsification (the substance of this release)

Falsify-first per `feedback_falsify_dont_confirm`. The adversarial corpus
(`scratch/review/v1_4_corpus.py`) + old-vs-new diffs against real corpora drove
the design and overturned the approved RFC premise:

- **The "replace the stop-list" premise was FALSE.** A content-shape co-signal on
  the markdown structure rule false-positived **6 real files** (READMEs/CLAUDE.md
  with `### ` headers + doc-section labels `Usage:`/`Authorization:`) in a
  2,491-file doc corpus. The stop-list is load-bearing and was retained.
- **On real data v1.4.0 == v1.2.4: 0 detection diff across 3,032 doc+chat files.**
  The gate changes behavior only on *adversarial* inputs (cyclic data tables,
  `Q:/A:` FAQ, `Added:` changelogs, multi-version release notes) — which v1.2.4
  false-positived but which are low-incidence in practice. Net = adversarial-FP
  robustness, honestly stated, not a real-world FP reduction.
- **`utterance_ratio` alone could not separate terse dialogue from data** (both
  ≈0.0). A **function-word arm** was added — the genuine discriminator (natural
  turns carry function words; atomic values do not). It preserves realistic terse
  dialogue (incl. RPG/Sentinel); only ultra-terse contentless exchanges remain FN.
- **Accepted FNs (asserted as FNs in `test_v1_4.py`, documented in LIMITATIONS):**
  ultra-terse contentless dialogue; all-distinct multi-party roll-call (recurrence
  retained, Q3); `Q:`/`A:`-labeled published interviews (FAQ-exclusion cost, Q2).

## 4. Tests

- `tests/test_v1_4.py` (+22): rejects atomic/cyclic data, prose-label FPs, FAQ;
  admits dialogue incl. terse RPG and function-word terse; asserts the three
  documented FNs; verifies `content_shape` surfaced (prose) / null (JSONL);
  version surfaces.
- ~10 degenerate toy fixtures in the existing suite (ultra-terse `User: hi` /
  `hi/hello/bye`) updated to realistic dialogue (which detects); the ultra-terse
  behavior is now pinned as a documented FN, not asserted as a TP.
- Full suite: **684 passed, 1 skipped.** Golden: no impact (green).
- Version-surface sync guard (`test_packaging`): pyproject + docstring + constant
  all 1.4.0.

## 5. Review findings & resolution

**In-house multi-agent `/code-review` (7 finder angles, 2026-06-02) — three real
defects found and fixed; my same-line/same-density adversarial corpus had missed
all three (textbook builder bias, caught by the decorrelated review):**

1. **Label regex `\s+` crossed newlines (correctness bug).** `^...:\s+(.*)$` —
   `\s` matches `\n`, so an empty-content label (`A: \n`) consumed the *next*
   label line as its content and dropped that label. `A: \nB: \nA: \nB:`
   collapsed to 1 distinct label. **Fixed:** `[ \t]+` (horizontal whitespace).
   Guard: `test_v1_4.TestReviewRegressionGuards.test_empty_label_does_not_swallow_next_line`.
2. **Density floor false-negatived multi-line-turn dialogue.** A turn wrapping
   over 3+ lines drops density to ~0.33 → rejected; and the sprinkled-prose case
   density targeted sits at *higher* density (~0.43) than the dialogue it broke,
   so no threshold separates them. **Fixed:** density gate dropped; `density`
   still surfaced as an observation; recurring-label-in-prose joins the accepted
   recurring-taxonomy FP residual. Guard: `test_multiline_turn_dialogue`.
3. **Structure vote-against rejected dated-journal dialogue + matched bare
   numbered headings.** `## 2024-01-01 session` (a legit journal) and `## 2.1`
   wrongly voted against. **Fixed:** version-*tag* headers only (bracketed / `v` /
   3-part semver); dated changelogs still caught via FP-lexicon. Guards:
   `test_dated_journal_dialogue`, `test_version_regex_ignores_bare_numbered_headings`.

Also addressed: a static-tuning/constant drift guard (`test_static_tuning_matches_constants`,
finding F10). Lower-severity findings logged: function-word-arm could FP a
metadata table whose values contain articles (theoretical — 0 occurrences in the
3,032-file real-data diff); detection/extraction use two label regexes (divergence
only for the rare label-on-own-line format).

**Gemini cross-model pass (gemini-2.5-pro, read-only, 2026-06-02) — converged
with the in-house pass on the structure co-signal, plus one clarity nit:**

4. **(HIGH, confirmed) Markdown structure co-signal lost label-on-own-line
   transcripts.** After fix #1, the Rule 2/3 co-signal used the content-requiring
   regex, so screenplay-style `Alice:\n<utterance>` no longer supplied the
   co-signal v1.3.0 had → FN for label-on-own-line markdown transcripts.
   **Fixed:** the co-signal uses the label-only `CHATLOG_SPEAKER_LABEL_RE`
   (stop-list filtered) — it's a structure rule, not a content-shape rule.
   Guard: `test_label_on_own_line_keeps_structure_cosignal`.
5. **(LOW, confirmed) `CHATLOG_RULES_DEFINITION` referenced `nonspeaker_lexicon_ci`
   without enumerating it.** The non-speaker stop-list affects detection filtering
   and extraction but wasn't in the hashed definition. **Fixed:** added a
   `nonspeaker_ci:` enumeration so the rules_hash reflects the actual stop-list.

Final real-data diff (post all fixes): **0 detection diff vs v1.2.4** across 3,032
files. Suite: 691 passed, 1 skipped.

**PR bots (Gemini/Codex/Copilot):** _pending — trigger on the PR; CONFIRMED
findings fixed before merge._

## 6. Backward Compatibility

- v1.0 public contract holds — no field removed/renamed/retyped; `content_shape`
  is additive (provisional). `chatlog` vector identity changes (method_version 9),
  expected and correct.
- On real data, detection is unchanged vs v1.2.4 (§3).
