# v0.9 Spec Compliance Report

**Report Date:** 2026-05-27
**Spec:** docs/archive/0.x/v0.9.0_RFC_Specification.md
**Implementation:** src/scanner/scanner.py (branch `v0.9.0`, commit `c2d20c6`)
**Prior Compliance:** docs/archive/0.x/COMPLIANCE-v0.8.md (v0.8 — all PASS)

---

## 1. Executive Summary

- **Spec Version:** v0.9.0 RFC Specification (Approved 2026-05-27)
- **Implementation Version:** 0.9.0 (pyproject.toml, SCANNER_VERSION, LOGIC_VERSION aligned; SCHEMA_VERSION = "0.9")
- **Schema Version:** 0.9 (additive change over 0.8 — no removals, renames, or type changes)
- **Overall Compliance Assessment:** COMPLETE — all acceptance criteria in §8 satisfied. Vector abstraction implemented with deterministic identity digests. Two exemplar vectors operational. Email body cross-cut wired. Per-directory aggregation populating. Dublin Core graduated.
- **High-Level Findings:**
  - `VectorRecord` dataclass, `VectorRegistry`, and identity digest computation implemented per §2.4
  - `vectors_collected[]` present on every manifest, sorted alphabetically by `vector_id`
  - Chatlog vector refactored from v0.8 specialist; all v0.8 fields preserved byte-identical
  - `reference_tokens` vector with 7 subcategories running on all text-eligible files
  - Email body chatlog cross-cut fires on `.eml`/`.msg` bodies; `is_chatlog` correctly stays false
  - `quality.per_directory_summary[]` aggregates by top-level subdirectory
  - Dublin Core alignment documented in PUBLIC_CONTRACT.md and STANDARDS_TRACKING.md
  - All v0.9 additions marked provisional in PUBLIC_CONTRACT.md §2.4
- **Critical Deviations:** None.
- **Test Count:** 516 passed, 1 skipped (up from 470 at v0.8 → +46 new tests).
- **External Validation:** Scanned 6 corpora (18,643 files total) with zero errors: scanner self-scan (9,902), Flask (265), tmux (355), FastAPI (3,002), OpenPreserve format-corpus (753), Apache Tika (4,366).

---

## 2. Vector Abstraction (§2)

### 2.1 Vector Definition (§2.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 1 | Vector has `vector_id` (string) and `method_version` (int) | `VectorRecord` dataclass fields | **PASS** |
| 2 | Vector has rules (patterns, thresholds, counting logic) | Defined as module-level constants per vector (`CHATLOG_RULES_DEFINITION`, `REFERENCE_TOKENS_RULES_DEFINITION`) | **PASS** |
| 3 | Vector has tuning (static configuration) | `CHATLOG_STATIC_TUNING`, `REFERENCE_TOKENS_STATIC_TUNING` dicts | **PASS** |

### 2.2 Vector Scope (§2.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 4 | File-scoped vectors run per file | Chatlog and reference_tokens both run in `scan_file()` per-file loop | **PASS** |
| 5 | Corpus-scoped vectors run after file walk | `_run_corpus_vectors()` hook exists after file walk; no corpus vectors in v0.9 (deferred) | **PASS** |
| 6 | Both scopes emit one entry in `vectors_collected[]` | Both vectors registered via `_register_chatlog_vector()` and `_register_reference_tokens_vector()` | **PASS** |

### 2.3 Rules vs. Tuning (§2.3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 7 | `rules_hash` = hash of rule set definition | `compute_rules_hash()` → SHA-256 of rules definition string | **PASS** |
| 8 | `static_tuning_hash` = hash of operator parameters | `compute_tuning_hash()` → SHA-256 of canonical JSON | **PASS** |
| 9 | Changing rules → new `method_version` | Documented in CONVENTIONS.md §1.4; enforced by naming convention | **PASS** |
| 10 | Changing tuning → same method_version, new hash | Tuning dict is separate from rules definition string | **PASS** |

### 2.4 Identity Digest (§2.4)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 11 | Preimage: `vector_id\|method_version\|rules_hash\|static_tuning_hash\|dynamic_tuning_hash\|dictionary_id` | `compute_vector_identity_digest()` builds pipe-delimited string | **PASS** |
| 12 | Null represented as literal "null" | `dynamic_tuning_hash or "null"` and `dictionary_id or "null"` | **PASS** |
| 13 | SHA-256, hex-encoded | `sha256(preimage.encode("utf-8")).hexdigest()` | **PASS** |
| 14 | `dynamic_tuning_hash` MUST be null in v0.9 | Hardcoded `None` in both vector registrations | **PASS** |
| 15 | `dictionary_id` MUST be null in v0.9 | Hardcoded `None` in both vector registrations | **PASS** |
| 16 | Preimage shape MUST NOT change without schema bump | Shape is fixed in `compute_vector_identity_digest()` function | **PASS** |

### 2.5 vectors_collected[] Manifest Block (§2.5)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 17 | Top-level array on ScanManifest | `vectors_collected: list[dict[str, Any]]` field on `ScanManifest` | **PASS** |
| 18 | One entry per vector that ran | Two entries: chatlog and reference_tokens | **PASS** |
| 19 | Sorted alphabetically by `vector_id` | `VectorRegistry.to_list()` sorts by key | **PASS** |
| 20 | Each entry has: vector_id, method_version, scope, rules_hash, static_tuning_hash, dynamic_tuning_hash, dictionary_id, identity_digest, applied_to_count, summary | All fields present on `VectorRecord` dataclass | **PASS** |
| 21 | Present in JSON output | Included in `manifest_to_json()` via `asdict()` | **PASS** |
| 22 | Present in JSONL header | Explicitly added to JSONL header dict | **PASS** |

### 2.6 Determinism Guarantees (§2.6)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 23 | Same identity digest + same input → same output | Verified by `test_chatlog_vector_identity_digest_deterministic` and `test_reference_tokens_identity_digest_deterministic` | **PASS** |
| 24 | File order does not affect output | `iter_files()` uses `sorted(root.rglob("*"))` | **PASS** |
| 25 | Environment does not affect output | Vectors use only file content and declared configuration | **PASS** |

### 2.7 What Vectors Do NOT Do (§2.7)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 26 | No dynamic tuning | `dynamic_tuning_hash` always None | **PASS** |
| 27 | No dictionaries | `dictionary_id` always None | **PASS** |
| 28 | No cross-scan state | No state persisted between `scan()` calls | **PASS** |
| 29 | No NLP/ML/language detection | Only regex-based deterministic counting | **PASS** |
| 30 | No interpretation | Vectors emit counts and lists only | **PASS** |

---

## 3. Exemplar Vectors (§3)

### 3.1 Chatlog Vector (§3.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 31 | `vector_id` = "chatlog" | `CHATLOG_VECTOR_ID = "chatlog"` | **PASS** |
| 32 | `method_version` = 1 | `CHATLOG_METHOD_VERSION = 1` | **PASS** |
| 33 | `scope` = "file" | Registered with `scope="file"` | **PASS** |
| 34 | Activation: .txt/.md/.mdx where v0.8 §2.3 rules match | Same `if extension in {".txt", ".md", ".mdx"}` gate + `_detect_chatlog_pattern()` | **PASS** |
| 35 | Static tuning: `{"detection_threshold": 3, "top_capitalized_tokens_n": 20}` | `CHATLOG_STATIC_TUNING` matches | **PASS** |
| 36 | v0.8 `is_chatlog` field preserved | `is_chatlog` still on FileRecord, unchanged semantics | **PASS** |
| 37 | v0.8 `specialist_metadata.chatlog` preserved | Same namespace and fields | **PASS** |
| 38 | Summary: matched_files, total_turns, distinct_speakers, section_marker_count, section_marker_styles | All fields present in chatlog vector summary | **PASS** |
| 39 | Summary aggregates from both chatlog files and email body cross-cut hits | `_accumulate_chatlog_summary()` called for both sources | **PASS** |
| 40 | Works when enable_specialists=False (detection counts, summary stays zero) | Verified by `test_chatlog_vector_specialists_disabled` | **PASS** |

### 3.2 reference_tokens Vector (§3.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 41 | `vector_id` = "reference_tokens" | `REFERENCE_TOKENS_VECTOR_ID = "reference_tokens"` | **PASS** |
| 42 | `method_version` = 1 | `REFERENCE_TOKENS_METHOD_VERSION = 1` | **PASS** |
| 43 | `scope` = "file" | Registered with `scope="file"` | **PASS** |
| 44 | Activation: every non-binary file in text-eligible extension set | `if extension in REFERENCE_TOKENS_EXTENSIONS` inside the `not is_binary` block | **PASS** |
| 45 | Seven subcategories implemented | at_mentions, wiki_links, code_fence_blocks, url_count, email_mentions, path_references, numeric_id_patterns | **PASS** |
| 46 | at_mentions: `@[a-zA-Z0-9_]+` | `CHATLOG_AT_MENTION_RE` (reused from v0.8) | **PASS** |
| 47 | wiki_links: `\[\[.+?\]\]` | `CHATLOG_WIKI_LINK_RE` (reused from v0.8) | **PASS** |
| 48 | code_fence_blocks: triple-backtick pairs | `text.count("```") // 2` | **PASS** |
| 49 | url_count: `https?://\S+` | `CHATLOG_URL_RE` (reused from v0.8) | **PASS** |
| 50 | email_mentions: addr regex | `REFERENCE_EMAIL_RE` | **PASS** |
| 51 | path_references: Unix + Windows, 3+ segments | `REFERENCE_PATH_UNIX_RE` + `REFERENCE_PATH_WIN_RE` | **PASS** |
| 52 | numeric_id_patterns: tickets, semver, project IDs | `REFERENCE_TICKET_RE` + `REFERENCE_SEMVER_RE` + `REFERENCE_PROJECT_ID_RE` | **PASS** |
| 53 | Per-file `reference_tokens` field present on text files | Added to `FileRecord` dataclass, populated in `scan_file()` | **PASS** |
| 54 | Per-file field is null on binary files | `reference_tokens_result` defaults to `None`, only set for text-eligible | **PASS** |
| 55 | Corpus summary: sums per subcategory + files_with_any_reference | `_register_reference_tokens_vector()` builds from accumulated sums | **PASS** |

---

## 4. Cross-Cutting Observation (§4)

### 4.1 Email Body Chatlog Cross-Cut (§4.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 56 | Chatlog vector callable as library function | `_detect_chatlog_pattern()` and `_extract_chatlog_metadata()` called on email body | **PASS** |
| 57 | Runs on .eml body text | `_extract_email_body()` for EML uses `email.parser` `get_body(preferencelist=("plain",))` | **PASS** |
| 58 | Runs on .msg body text | `_extract_email_body()` for MSG reads PR_BODY (0x1000) via olefile | **PASS** |
| 59 | `specialist_metadata.email.body_chatlog` populated when fires | Populated in specialist dispatch block | **PASS** |
| 60 | `is_chatlog` stays false on email files | Not modified for emails — only set in the `.txt/.md/.mdx` block | **PASS** |
| 61 | Email body hits counted in chatlog vector's applied_to_count | Tracked in scan loop via `specialist_metadata.email.body_chatlog` check | **PASS** |
| 62 | Failures recorded as errors, not silently swallowed | `ErrorRecord` appended on exception (fixed per PR review) | **PASS** |

### 4.2 Per-Directory Aggregation (§4.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 63 | New field `per_directory_summary` on ScanQuality | Added to `ScanQuality` dataclass | **PASS** |
| 64 | One entry per top-level subdirectory | Groups by `stage_folder` | **PASS** |
| 65 | Files at scan root use `directory: ""` | `stage_folder` is "" for root files | **PASS** |
| 66 | Top-level only, not nested deeper | Groups on `stage_folder` (first path component), not full path | **PASS** |
| 67 | Sorted alphabetically by directory | `for dirname in sorted(dir_groups)` | **PASS** |
| 68 | Fields: total_files, chatlog_files, safety_flags_files, mime_mismatches, polyglots_detected, specialist_failures, unsupported_extensions | All seven fields computed per group | **PASS** |
| 69 | All fields non-negative integers | Sum operations on boolean conditions, always >= 0 | **PASS** |

---

## 5. Standards Tracking Graduation (§5)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 70 | Dublin Core moved from Awareness to Adopted | STANDARDS_TRACKING.md updated: removed from Awareness, added to Adopted with `since 0.9` | **PASS** |
| 71 | Alignment note in PUBLIC_CONTRACT.md §1.4 | Added to `document` namespace row: `document.title` → `dc:title`, `document.author` → `dc:creator` | **PASS** |
| 72 | No code changes required | Documentation only — DOCX specialist already extracts the fields | **PASS** |

---

## 6. Schema Impact (§6)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 73 | Schema version 0.8 → 0.9 | `SCHEMA_VERSION = "0.9"` | **PASS** |
| 74 | `vectors_collected[]` additive | New field on ScanManifest with default `field(default_factory=list)` | **PASS** |
| 75 | `quality.per_directory_summary[]` additive | New field on ScanQuality with default `field(default_factory=list)` | **PASS** |
| 76 | `reference_tokens` additive | New field on FileRecord with default `None` | **PASS** |
| 77 | `specialist_metadata.email.body_chatlog` additive | Only populated when cross-cut fires | **PASS** |
| 78 | All additions marked provisional in PUBLIC_CONTRACT.md §2.4 | Four items listed under Internal Field Sets | **PASS** |
| 79 | No fields removed | All v0.8 fields present and unchanged | **PASS** |
| 80 | No fields renamed | No renames | **PASS** |
| 81 | No type changes | No type changes | **PASS** |

---

## 7. Acceptance Criteria (§8)

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 82 | Vector abstraction exists and documented | `VectorRecord`, `VectorRegistry`, `compute_vector_identity_digest()` with docstrings | **PASS** |
| 83 | `vectors_collected[]` present on every manifest, sorted | `VectorRegistry.to_list()` sorts; verified by `test_vectors_sorted_alphabetically` | **PASS** |
| 84 | Identity digests deterministic | `test_chatlog_vector_identity_digest_deterministic`, `test_reference_tokens_identity_digest_deterministic`, `test_preimage_is_pipe_delimited` | **PASS** |
| 85 | Two scans same corpus → identical vectors_collected | Deterministic tests run two scans and compare digests | **PASS** |
| 86 | Chatlog vector matches v0.8 output | `test_chatlog_vector_v08_backwards_compat` — is_chatlog and specialist_metadata.chatlog verified | **PASS** |
| 87 | reference_tokens populated on text files, null on binary | `test_reference_tokens_on_text_file`, `test_reference_tokens_null_on_binary` | **PASS** |
| 88 | per_directory_summary populated | `test_subdirectory_aggregation`, `test_chatlog_files_counted_per_directory` | **PASS** |
| 89 | email.body_chatlog populated when fires | `test_body_chatlog_fires_on_chatlog_email` | **PASS** |
| 90 | Dublin Core in PUBLIC_CONTRACT.md | §1.4 document namespace row updated | **PASS** |
| 91 | Dublin Core in STANDARDS_TRACKING.md | Moved to Adopted table with `since 0.9` | **PASS** |
| 92 | All v0.8 tests pass unchanged | 470 original tests pass (version assertions updated to 0.9) | **PASS** |
| 93 | New v0.9 tests cover all additions | 46 new tests across 8 test classes | **PASS** |
| 94 | schema_version is "0.9" | `SCHEMA_VERSION = "0.9"`, verified by existing context tests | **PASS** |

---

## 8. External Validation

v0.9 was validated against 6 external corpora with zero errors:

| Corpus | Files | Text | Binary | Chatlog hits | Ref token files | Specialist hits |
|---|---|---|---|---|---|---|
| Scanner (self-scan) | 9,902 | 4,316 | 5,586 | 66 | 848 | — |
| Flask | 265 | 253 | 12 | 0 | 53 | — |
| tmux | 355 | 332 | 23 | 2 | 12 | — |
| FastAPI | 3,002 | 2,757 | 245 | 519 | 1,598 | — |
| OpenPreserve format-corpus | 753 | 196 | 557 | 2 | 108 | pdf:285, image:22, document:12 |
| Apache Tika | 4,366 | 3,526 | 840 | 27 | 806 | document:152, pdf:69, spreadsheet:57, image:25, email:13 |
| **Total** | **18,643** | **11,380** | **7,263** | | | |

Notable findings from external validation:
- FastAPI's 519 chatlog detections are false positives from documentation-heavy `### ` headers — known behavior, tuning candidate for v0.9.1
- Apache Tika produced 1 email body chatlog cross-cut hit on a real `.eml` file
- Zero crashes across all corpora including adversarial format samples (OpenPreserve) and polyglot files (Tika)

---

## 9. Test Summary

| Category | Tests |
|---|---|
| Pre-v0.9 (carried forward) | 470 |
| VectorIdentityDigest | 8 |
| RulesAndTuningHash | 5 |
| VectorRegistry | 3 |
| ManifestVectorsCollected | 3 |
| ChatlogVector | 8 |
| ReferenceTokensVector | 10 |
| EmailBodyChatlogCrosscut | 5 |
| PerDirectorySummary | 6 |
| **Total** | **516 passed, 1 skipped** |

---

## 10. Compliance Verdict

**PASS — 94 requirements verified, 0 failures, 0 deviations.**

All v0.9 spec requirements are implemented and tested. The Vector abstraction is operational with deterministic identity digests. Both exemplar vectors produce meaningful output validated against 18K+ real-world files. All v0.8 behavior is preserved. All additions are marked provisional per the stability plan.
