# v0.8 Spec Compliance Report

**Report Date:** 2026-04-10
**Spec:** docs/v0.8.0_RFC_Specification.md
**Implementation:** src/scanner/scanner.py (branch `v0.8.0`, commit `54f8f4a`)
**Prior Compliance:** docs/COMPLIANCE-v0.6.md (v0.6 — all PASS). v0.7.0 and v0.7.1/.2 patches have no compliance reports; see HISTORY.md "Compliance Report Gaps."

---

## 1. Executive Summary

- **Spec Version:** v0.8.0 RFC Specification (Approved 2026-04-10)
- **Implementation Version:** 0.8.0 (pyproject.toml, SCANNER_VERSION, LOGIC_VERSION aligned; SCHEMA_VERSION = "0.8")
- **Schema Version:** 0.8 (additive change over 0.7 — no removals, renames, or type changes)
- **Overall Compliance Assessment:** COMPLETE — all acceptance criteria in §7 satisfied. All 11 specialist metadata fields produce the specified types and values. Detection rules match spec wording exactly after PR #9 review tightening. The chatlog specialist is the first content-detected (not extension-based) dispatch in the scanner, and its activation, extraction, provenance, and quality counter all route through production paths.
- **High-Level Findings:**
  - `is_chatlog` flag added to `FileRecord` with correct default, always present.
  - Detection runs on `.txt` / `.md` / `.mdx` even when `enable_specialists=False` (cheap regex pass on decoded baseline text).
  - All 11 specialist metadata fields implemented with deterministic output and the sort orders specified in §2.5.
  - `quality.chatlog_files` counter correctly aggregates per-file detections.
  - `.md` and `.mdx` registered in `mimetypes` so the no-libmagic fallback path does not mark them binary.
  - 6 new regex constants, 1 new MIME guard entry, 2 new module identity constants, 1 new quality field, 1 new FileRecord field.
  - 3 new fixture files in `tests/fixtures/edge_cases/`.
- **Critical Deviations:** One intentional deviation from spec §5.1 — fake-extension registration avoided in favor of module-level constants. Documented in §6 below.
- **Test Count:** 470 passed, 1 skipped (up from 402 at the start of v0.8 work → +68 tests of which 62 are chatlog-specific and 6 are PR review regression guards).

---

## 2. Classification and Detection (§2.2, §2.3)

### 2.1 Classification (§2.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 1 | `is_binary: false` for chatlog-eligible files | Text files (.txt/.md/.mdx) that pass binary detection | **PASS** |
| 2 | `requires_specialist_tool: true` when chatlog activates | `scan_file()` overrides to `True` on `is_chatlog` activation, with provenance re-recorded under trigger `chatlog_activation` | **PASS** |
| 3 | `specialist_tool = "chatlog_signals"` when chatlog activates | `scan_file()` overrides to `CHATLOG_TOOL` on activation | **PASS** |
| 4 | Namespace is `chatlog` | `CHATLOG_NAMESPACE = "chatlog"` constant; used as the key in `specialist_metadata` | **PASS** |

### 2.2 Detection Rules (§2.3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 5 | Activates for `.txt`, `.md`, `.mdx` only | `scan_file()`: `if extension in {".txt", ".md", ".mdx"}:` gate around detection | **PASS** |
| 6 | Does NOT activate based on extension alone | Detection also requires a content-pattern match inside `_detect_chatlog_pattern` | **PASS** |
| 7 | Rule 1: 3+ lines matching `^([A-Z][a-zA-Z0-9_]{0,15}):\s` | `CHATLOG_SPEAKER_LABEL_RE` + `len(findall) >= 3` | **PASS** |
| 8 | Rule 2: 3+ `### ` headers | `CHATLOG_H3_HEADER_RE = ^### ` with `re.MULTILINE`, line-anchored. *(Tightened from a substring count in response to PR #9 comment 5.)* | **PASS** |
| 9 | Rule 3: 3+ `---` section dividers | `CHATLOG_SECTION_DIVIDER_RE = ^-{3,}\s*$`. *(Tightened from matching other divider characters in response to PR #9 comment 1 — see §6.)* | **PASS** |
| 10 | Any one rule triggers activation | `_detect_chatlog_pattern` returns `True` on first matching rule | **PASS** |
| 11 | Detection runs when `enable_specialists=False` | Wired into the text-handling block, not the specialist block. Verified by `test_detection_runs_with_specialists_disabled`. | **PASS** |
| 12 | Non-matching files fall back to standard baseline/structural processing | When `is_chatlog=False`, scan_file continues with existing per-extension extraction (.md frontmatter, .html title, etc.) | **PASS** |

---

## 3. Specialist Metadata Shape (§2.4, §2.5, §2.6)

### 3.1 Field Presence and Types (§2.5)

| # | Field | Type | Implementation | Status |
|---|---|---|---|---|
| 13 | `turn_count` | int | Raw match count of `CHATLOG_SPEAKER_LABEL_RE` (NOT frequency-filtered) | **PASS** |
| 14 | `speaker_labels` | sorted list[str] | `Counter` over raw matches, filtered to tokens with count ≥ 3 per §2.6, `sorted()` | **PASS** |
| 15 | `section_marker_count` | int | Sum of pure-divider matches (`CHATLOG_PURE_DIVIDER_RE`) and markdown header matches (`CHATLOG_MD_HEADER_RE`) | **PASS** |
| 16 | `section_marker_styles` | sorted list[str] | `set` of normalized styles (3-char divider form + `#`/`## `/`### ` etc.), then `sorted()` | **PASS** |
| 17 | `avg_turn_chars` | int | Sum of character distances between consecutive raw speaker labels / count | **PASS** |
| 18 | `max_turn_chars` | int | Max of same distances | **PASS** |
| 19 | `min_turn_chars` | int | Min of same distances | **PASS** |
| 20 | `reference_tokens.at_mentions` | int | `CHATLOG_AT_MENTION_RE` count | **PASS** |
| 21 | `reference_tokens.wiki_links` | int | `CHATLOG_WIKI_LINK_RE` count | **PASS** |
| 22 | `reference_tokens.code_fence_blocks` | int | `text.count("```") // 2` (pairs) | **PASS** |
| 23 | `reference_tokens.url_count` | int | `CHATLOG_URL_RE` count | **PASS** |
| 24 | `top_capitalized_tokens` | list[str] | Top N (default 20) qualifying tokens, sorted by `(-freq, alpha)` | **PASS** |
| 25 | `capitalized_token_count` | int | Cardinality of the qualifying set (length 3+ and frequency 3+) | **PASS** |
| 26 | `vocabulary_size_estimate` | int | Count of distinct lowercase word tokens after lowercasing the whole text (single-character tokens included) | **PASS** |

### 3.2 Sort Orders (§2.5)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 27 | `speaker_labels` sorted alphabetically | `sorted(label for label, count in label_counts.items() if count >= 3)` | **PASS** — verified by `test_speaker_labels_sorted_alphabetically` |
| 28 | `section_marker_styles` sorted | `sorted(section_marker_styles_set)` | **PASS** — verified by `test_section_marker_styles_sorted` |
| 29 | `top_capitalized_tokens` by frequency desc, alphabetical secondary | `qualifying_caps.sort(key=lambda tc: (-tc[1], tc[0]))` | **PASS** — verified by `test_top_capitalized_tokens_sorted_by_frequency_desc` and `test_top_capitalized_tokens_alphabetical_secondary` |

### 3.3 Extraction Rules (§2.6)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 30 | Operates on `decode_text()` bounded text | `_extract_chatlog_metadata(text)` receives the decoded string, no file I/O | **PASS** |
| 31 | Speaker labels must repeat 3+ times to be listed | `if count >= 3` filter inside the speaker label Counter comprehension | **PASS** — verified by `test_speaker_labels_filtered_to_3_plus_repetition` |
| 32 | Capitalized tokens must be length 3+ and freq 3+ | `\b[A-Z][a-zA-Z0-9_]{2,}\b` regex (length 3+) + `if count >= 3` filter | **PASS** — verified by `test_capitalized_tokens_filtered_by_length` and `test_capitalized_tokens_filtered_by_frequency` |
| 33 | Section markers detected by both regexes | `CHATLOG_PURE_DIVIDER_RE` for pure divider lines, `CHATLOG_MD_HEADER_RE` for markdown headers; both feed `section_marker_count` and `section_marker_styles` | **PASS** |
| 34 | No streaming, no full-file reads | `_extract_chatlog_metadata` operates entirely on the `text` parameter | **PASS** |

### 3.4 Default Top-N (§2.5)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 35 | N=20 default for top_capitalized_tokens | `_CHATLOG_TOP_TOKENS_N = 20` class constant used in slice | **PASS** — verified by `test_top_capitalized_tokens_capped_at_default_n` |

### 3.5 What the Specialist Does NOT Do (§2.7)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 36 | No NLP, POS tagging, entity recognition | None present in `_extract_chatlog_metadata` | **PASS** |
| 37 | No conversation summarization | None present | **PASS** |
| 38 | No language detection | None present | **PASS** |
| 39 | No sentiment analysis | None present | **PASS** |
| 40 | No cross-file comparison | Function is stateless; receives one text, returns one dict | **PASS** |
| 41 | No interpretation of what tokens "mean" | Returns raw tokens and counts; consumer decides meaning | **PASS** |

---

## 4. Schema Impact (§5)

### 4.1 Additive Changes

| # | Field | Location | Type | Status |
|---|---|---|---|---|
| 42 | `is_chatlog` | `FileRecord` | `bool = False` (defaulted) | **PASS** |
| 43 | `specialist_metadata.chatlog` | `FileRecord.specialist_metadata` | dict (11 fields) when `enable_specialists=True` and detection fires | **PASS** |
| 44 | `quality.chatlog_files` | `ScanQuality` | `int = 0` (defaulted) | **PASS** |

No fields removed, renamed, or retyped. Schema version is `"0.8"`.

### 4.2 SPECIALIST_MIME_GUARD Entry (§5.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 45 | Accepts `text/plain` | `SPECIALIST_MIME_GUARD["chatlog"]` contains it | **PASS** |
| 46 | Accepts `text/markdown` | Same | **PASS** |
| 47 | Accepts `text/x-markdown` | Same | **PASS** |
| 48 | MIME guard enforced before extraction | `if mime_type not in chatlog_guard:` check inside `scan_file()` records a skipped error and does not call the extractor | **PASS** |

---

## 5. Phases and Acceptance Criteria (§6, §7)

### 5.1 Phase Completion (§6)

| Phase | Scope | Commit | Status |
|---|---|---|---|
| Phase 1 | `is_chatlog` field + detection rules + wiring | `0eb863f` | **COMPLETE** |
| Docs refresh | CLAUDE.md + scratch notes | `f8a3ed1` + `3dc2a5a` | **COMPLETE** |
| Phase 2 | `_extract_chatlog_metadata` + content-based dispatch + per-field provenance | `96d9e95` | **COMPLETE** |
| Phase 3 | `quality.chatlog_files` counter | `24491aa` | **COMPLETE** |
| Phase 4 | Version bump, fixtures, HISTORY + CONVENTIONS updates | `4d9912e` | **COMPLETE** |
| PR review fixes | 5 spec-alignment corrections from review bots | `54f8f4a` | **COMPLETE** |

### 5.2 Acceptance Criteria (§7)

| # | Criterion | Status |
|---|---|---|
| 49 | `is_chatlog` field present on every FileRecord | **PASS** — dataclass field with default False, always serialized |
| 50 | Detection rules correctly identify conversational text patterns | **PASS** — 11 unit tests in `TestDetectChatlogPattern` + fixture tests |
| 51 | `_extract_chatlog_metadata()` produces all specified fields | **PASS** — `test_minimal_chatlog_all_fields_present` iterates every field |
| 52 | All chatlog fields are deterministic | **PASS** — `test_deterministic_output` compares two extractions of the same text |
| 53 | Top capitalized tokens sorted by frequency descending, alphabetical secondary | **PASS** — two dedicated tests |
| 54 | Speaker labels list sorted alphabetically | **PASS** — dedicated test |
| 55 | Section marker styles list sorted | **PASS** — dedicated test |
| 56 | Specialist MIME guard accepts text MIME types | **PASS** — 3 MIME types in the guard set |
| 57 | `quality.chatlog_files` count is correct | **PASS** — `test_chatlog_files_counter_counts_detections` verifies mixed-corpus counting |
| 58 | All v0.7 tests pass unchanged | **PASS** — pre-v0.8 tests all still green (no modifications to v0.7 test assertions beyond the version bump) |
| 59 | `schema_version` is `"0.8"` | **PASS** — `SCHEMA_VERSION = "0.8"` constant; manifest field populated correctly |

---

## 6. Deviations from Spec

### 6.1 SPECIALIST_TOOLS registration (§5.1)

**Spec §5.1 suggestion:**
```python
SPECIALIST_TOOLS[".chatlog"] = "chatlog_signals"  # NOT a real extension — see below
```

**Implementation decision:** NOT taken. Used module-level constants instead:
```python
CHATLOG_NAMESPACE = "chatlog"
CHATLOG_TOOL = "chatlog_signals"
```

**Reasoning:** `SPECIALIST_TOOLS` is an extension-keyed dict consulted by `scan_file()` at universal tier via `SPECIALIST_TOOLS.get(extension)`. Registering a fake `.chatlog` key would leak into inventory queries and, more importantly, risk accidental extension-based routing if any real file ever happened to use that extension. The content-detected nature of the chatlog dispatch is preserved more honestly with standalone constants that never flow through the extension-keyed lookup at all.

The spec's own comment acknowledges this is "NOT a real extension," implying the spec author was already uncomfortable with the fake-key pattern and flagging it as a discussion point rather than a hard requirement. The CONVENTIONS.md §4.2 inventory is updated to reflect the standalone constants instead of treating this as a gap.

**Impact:** None on consumers (manifest output is identical). Minor impact on internal inventory — `SPECIALIST_TOOLS` count stays at 10 entries / 6 namespaces rather than gaining a 11th fake entry.

### 6.2 PR review tightenings

Five items surfaced during PR #9 review that brought the initial implementation into stricter alignment with the spec. All accepted:

| # | Issue | Initial behavior | Spec-aligned behavior |
|---|---|---|---|
| 1 | Detection rule 3 breadth | `CHATLOG_SECTION_DIVIDER_RE` matched `^[-=*#]{3,}\s*$` | Tightened to `^-{3,}\s*$` (dashes only per spec §2.3 rule 3). Extraction regex unchanged. |
| 2 | Vocab undercount | Regex required 2+ chars (`\b[a-z][a-z0-9]{1,}\b`) | Allows 1+ chars (`\b[a-z][a-z0-9]*\b`) so "a"/"i" count |
| 3 | Fixture test encoding | Implicit platform encoding | Explicit `encoding="utf-8"` on both read and write |
| 4 | `.mdx` + no libmagic | Would resolve to `application/octet-stream` → marked binary → text decode skipped | `mimetypes.add_type("text/markdown", ".mdx")` at module load |
| 5 | Rule 2 substring match | `text.count("### ")` caught inline/code mentions | Line-anchored `^### ` regex |

Each tightening has a corresponding regression guard test. See PR #9 comment from 2026-04-10 for the full summary. Commit `54f8f4a`.

### 6.3 MSG body extraction (§5 implicit)

**Observation:** The v0.8 spec describes the chatlog specialist as the first content-detected dispatch, targeting text files. `.msg` / `.eml` files are extension-driven specialists that currently extract only envelope metadata (subject, from, to, date, message_id, has_attachments). The spec does not require body-level chatlog detection on email files.

**Implementation status:** Not implemented. Email body extraction is a natural Phase 5 / v0.9 follow-on — the same chatlog rules could apply to `PR_BODY` / `PR_HTML` content — but is out of scope for v0.8.

**Impact:** None. A v0.8 claim that is deliberately narrow.

---

## 7. Test Summary

| Module | Tests |
|---|---|
| `test_unit.py` | 316 |
| `test_integration.py` | 52 |
| `test_golden.py` | 8 |
| `test_edge_cases.py` | 95 |
| **Total** | **471 collected (470 passed, 1 skipped)** |

The skipped test is `test_doc_extracts_from_real_fixtures`, which no-ops when no real `.doc` fixtures are present in `tests/fixtures/`. Same skip condition as v0.6 / v0.7.

### 7.1 Chatlog-specific test counts (new in v0.8)

| Test class | Tests | Coverage |
|---|---|---|
| `TestDetectChatlogPattern` | 14 | Phase 1 detection rules, thresholds, edge cases, regression guards for PR #9 comments 1 and 5 |
| `TestIsChatlogIntegration` | 7 | Phase 1 end-to-end: flag, provenance, enable_specialists=False path, JSON round-trip |
| `TestExtractChatlogMetadata` | 24 | Phase 2 extraction: every field, sort orders, filters, determinism |
| `TestChatlogSpecialistIntegration` | 7 | Phase 2 end-to-end: specialist_metadata populated, specialist_tool flag set, per-field provenance, MIME guard |
| `TestScanQualityChatlogFiles` | 5 | Phase 3 quality counter |
| `TestChatlogFixtures` | 3 | Phase 4 fixture files exercised end-to-end |
| `TestMarkdownMimetypeRegistration` | 2 | PR #9 comment 4 regression guard |
| `TestVocabularySizeEstimateSingleChar` | 2 | PR #9 comment 2 regression guard |
| **Total chatlog-specific** | **64** | |

---

## 8. Summary Table

| Category | PASS | PARTIAL | FAIL |
|---|---|---|---|
| Classification + routing (§2.2) | 4 | 0 | 0 |
| Detection rules (§2.3) | 8 | 0 | 0 |
| Metadata field shape (§2.5) | 14 | 0 | 0 |
| Sort orders (§2.5) | 3 | 0 | 0 |
| Extraction rules (§2.6) | 5 | 0 | 0 |
| Top-N default (§2.5) | 1 | 0 | 0 |
| Negative constraints (§2.7) | 6 | 0 | 0 |
| Schema impact (§5) | 3 | 0 | 0 |
| MIME guard (§5.2) | 4 | 0 | 0 |
| Acceptance criteria (§7) | 11 | 0 | 0 |
| **Total** | **59** | **0** | **0** |

**Overall Assessment:** v0.8.0 is complete and compliant with the RFC. The chatlog specialist is the first content-detected dispatch in the scanner and establishes the pattern for future content-based classification work. One intentional deviation from §5.1 (fake-extension registration) is documented above. Five spec-alignment corrections from PR #9 review have been applied and guarded by regression tests. No outstanding failures, no partial implementations, no known gaps within the v0.8.0 scope.

v0.8 opens the door to Round 2 of the Wayne K discipline on real chatlog corpora — with the metadata shape now stable, drift detection by a stateful consumer becomes a straightforward diff operation over sequential manifests.
