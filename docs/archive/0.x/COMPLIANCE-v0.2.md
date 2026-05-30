# v0.2 Spec Compliance Report

**Report Date:** 2026-04-07
**Spec:** docs/v0.2Spec.md
**Implementation:** src/scanner/scanner.py
**Prior Compliance:** docs/COMPLIANCE.md (v0.1 — all requirements PASS)

---

## 1. Executive Summary

- **Spec Version:** v0.2 Design Document (2026-04-06)
- **Implementation Version:** 0.2.0 (from pyproject.toml)
- **Overall Compliance Assessment:** COMPLETE — all three phases implemented and tested. All 10 functional scope items addressed. All acceptance criteria from §10 satisfied.
- **High-Level Findings:**
  - Phase 1 (Accessibility): manifest metadata, stats, routing summary, and JSONL output are implemented and tested.
  - Phase 2 (Operability): `.scannerignore`, incremental/delta scanning, and manifest checksum are implemented and tested.
  - Phase 3 (Bounded Expansion): MIME mismatch signaling, PDF specialist metadata probe, and formal `.html`/`.htm` support are implemented and tested.
  - v0.1 guarantees remain intact — all 176 pre-existing tests continue to pass.
  - 37 new tests added for Phase 3 features, bringing total to 213.
  - Determinism preserved across all new features.
- **Critical Deviations:**
  - None identified. All MUST-level requirements are satisfied.
- **Design Principle Adherence:**
  - Scanner v0.2 remains: deterministic, read-only, non-semantic, non-classifying, non-mutating, non-OCR.

---

## 2. Requirement Compliance Matrix

### 2.1 Section 2.1 — Primary Objectives (§2.1)

| # | Requirement (MUST) | Spec Section | Implementation Location | Status | Justification |
|---|---|---|---|---|---|
| 1 | Preserve full v0.1 correctness and compliance | §2.1 | All v0.1 code paths unchanged; 176 pre-existing tests pass | **PASS** | v0.1 compliance report (docs/COMPLIANCE.md) remains valid. No v0.1 behavior was altered. |
| 2 | Improve manifest usability for downstream systems | §2.1 | `ScanMeta`, `ScanStats`, `RoutingSummary` dataclasses; `manifest_to_jsonl()` | **PASS** | Manifest-level metadata, stats, routing summary, and JSONL output all implemented. |
| 3 | Add operational metadata for auditing and orchestration | §2.1 | `ScanMeta.scan_id`, `ScanMeta.config`, `manifest_checksum` | **PASS** | UUID scan ID, runtime config snapshot, and SHA-256 manifest checksum present. |
| 4 | Support efficient re-scanning workflows | §2.1 | `DeltaRecord`, `_compute_delta()` line 328, `--previous-manifest` CLI flag | **PASS** | Delta scanning compares against previous manifest by checksum. |
| 5 | Allow limited, bounded exploration of adjacent formats and specialist metadata | §2.1 | `MimeAnalysisRecord` line 135, `extract_specialist_metadata()` line 576, `.html`/`.htm` in `SUPPORTED_EXTENSIONS` line 31 | **PASS** | MIME mismatch signaling, PDF metadata probe, and HTML formal support implemented. |

### 2.2 Section 2.2 — Secondary Objectives (§2.2)

| # | Requirement (SHOULD) | Spec Section | Implementation Location | Status | Justification |
|---|---|---|---|---|---|
| 6 | Reduce friction for scanning real-world repos and working directories | §2.2 | `.scannerignore` support, `_load_ignore_patterns()` line 243, `_is_ignored()` line 260 | **PASS** | Ignore rules support vendor dirs, build artifacts, user-defined patterns. |
| 7 | Expose mismatch/anomaly signals without interpreting them | §2.2 | `MimeAnalysisRecord` line 135, `analyze_mime()` line 562 | **PASS** | MIME mismatch exposed as descriptive record; no interpretation or blocking. |
| 8 | Provide optional outputs suitable for streaming workflows | §2.2 | `manifest_to_jsonl()` line 880, `--format jsonl` CLI flag | **PASS** | NDJSON/JSONL output with header line + one record per line. |

### 2.3 Section 2.3 — Non-Goals (§2.3)

| # | MUST NOT | Spec Section | Status | Justification |
|---|---|---|---|---|
| 9 | Perform classification | §2.3 | **PASS** | No classification code present. |
| 10 | Infer document meaning | §2.3 | **PASS** | No inference code present. |
| 11 | Rank importance | §2.3 | **PASS** | No ranking code present. |
| 12 | Create semantic summaries | §2.3 | **PASS** | No summarization code present. |
| 13 | Generate embeddings | §2.3 | **PASS** | No embedding code present. |
| 14 | Run OCR | §2.3 | **PASS** | No OCR libraries imported or invoked. |
| 15 | Mutate source files | §2.3 | **PASS** | All file access is read-only. |
| 16 | Link files into graphs | §2.3 | **PASS** | No graph/link code present. |
| 17 | Make ingestion decisions | §2.3 | **PASS** | No ingestion logic present. |
| 18 | Execute downstream routing | §2.3 | **PASS** | Routing summary is descriptive only. |

---

## 3. Track A — Accessibility and Operability

### 3.1 Manifest Metadata Block (§5.1.1)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 19 | `scan_id` MUST be unique per scan execution | `ScanMeta.scan_id`, line 283: `str(uuid.uuid4())` | **PASS** | UUID4 generates unique ID per scan. |
| 20 | `config` MUST reflect actual runtime configuration | `ScanMeta.config`, line 286: `asdict(self.config)` | **PASS** | Runtime `ScannerConfig` serialized directly. |
| 21 | Metadata MUST be deterministic except for `scan_id` and `generated_at` | `ScanMeta` dataclass line 180 | **PASS** | `config` and `source_dir` are deterministic; only `scan_id` and `generated_at` vary. |

**Proposed shape compliance:**

| Field | Spec Shape | Implementation | Match |
|---|---|---|---|
| `scan_id` | `"uuid"` | `str(uuid.uuid4())` | Yes |
| `generated_at` | ISO-8601 | `now_iso()` — UTC ISO-8601 | Yes |
| `source_dir` | path string | `str(self.source_dir)` — resolved absolute path | Yes |
| `config.preview_max_chars` | int | From `ScannerConfig` | Yes |
| `config.sample_size` | int | From `ScannerConfig` | Yes |
| `config.enable_specialists` | bool | From `ScannerConfig` | Yes |
| `config.exclude_hidden` | bool | From `ScannerConfig` | Yes |
| `config.format` | string | From `ScannerConfig` | Yes |

### 3.2 Manifest Statistics (§5.1.2)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 22 | Stats MUST be derived directly from scanned records | `_compute_stats()` line 304 | **PASS** | Iterates over `records` list using comprehensions. |
| 23 | Stats MUST be deterministic | `_compute_stats()` line 304 | **PASS** | Pure function of records; no randomness. |
| 24 | Stats MUST NOT require additional file reads | `_compute_stats()` line 304 | **PASS** | Uses only `FileRecord` attributes already computed. |

**Proposed shape compliance:**

| Field | Spec Shape | Implementation | Match |
|---|---|---|---|
| `total_files` | int | `len(records)` | Yes |
| `supported_files` | int | Count where `r.extension in SUPPORTED_EXTENSIONS` | Yes |
| `unsupported_files` | int | `total - supported` | Yes |
| `text_files` | int | Count where `not r.is_binary` | Yes |
| `binary_files` | int | Count where `r.is_binary` | Yes |
| `requires_vision` | int | Count where `r.requires_vision` | Yes |
| `requires_specialist_tool` | int | Count where `r.requires_specialist_tool` | Yes |

### 3.3 Routing Summary (§5.1.3)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 25 | Block MUST be descriptive only | `_compute_routing_summary()` line 320 | **PASS** | Counts only; no actions taken. |
| 26 | MUST NOT choose or execute downstream actions | `_compute_routing_summary()` line 320 | **PASS** | Returns `RoutingSummary` dataclass with counts only. |
| 27 | MUST derive only from existing per-file fields | `_compute_routing_summary()` line 320 | **PASS** | Uses `is_binary`, `requires_vision`, `requires_specialist_tool` from `FileRecord`. |

**Proposed shape compliance:**

| Field | Spec Shape | Implementation | Match |
|---|---|---|---|
| `baseline_ready` | int | `not is_binary and not requires_specialist_tool` | Yes |
| `binary_only` | int | `is_binary and not requires_vision and not requires_specialist_tool` | Yes |
| `requires_vision` | int | `requires_vision` | Yes |
| `requires_specialist_tool` | int | `requires_specialist_tool` | Yes |

### 3.4 Output Format Options (§5.1.4)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 28 | JSON remains default | `ScannerConfig.format = "json"` line 231, `main()` line 897 | **PASS** | Default format is `"json"`. |
| 29 | JSONL MUST preserve full per-record fidelity | `manifest_to_jsonl()` line 880: uses `asdict(record)` per file | **PASS** | Each line is a full `FileRecord` serialized identically to JSON output. |
| 30 | JSONL mode MAY emit manifest metadata separately; behavior must be documented | `manifest_to_jsonl()` line 880: header line with meta/stats/routing/delta/checksum, then one line per file | **PASS** | Header/body strategy. Header is first line containing all manifest-level fields. |

### 3.5 Field Grouping for Usability (§5.1.5)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 31 | MUST NOT destabilize existing contract unless versioned | `FileRecord` dataclass line 152 | **PASS** | New fields (`mime_analysis`, `specialist_metadata`) are additive. No existing fields removed or renamed. Backward-compatible extension. |

---

## 4. Track B — Operational Efficiency

### 4.1 Ignore Rules (§5.2.1)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 32 | Ignore behavior MUST be deterministic | `_is_ignored()` line 260 | **PASS** | Pattern matching via `fnmatch` is deterministic for identical patterns and paths. |
| 33 | Pattern format SHOULD be simple and documented | `.scannerignore` format: one pattern per line, `#` comments, blank lines ignored, `/` suffix for directories | **PASS** | Simple glob-style patterns. |
| 34 | Hidden file exclusion and ignore patterns MUST coexist predictably | `iter_files()` line 365: hidden check runs first, then ignore check | **PASS** | Both filters applied independently. Tested in `TestScannerIgnore.test_ignore_coexists_with_exclude_hidden`. |
| 35 | Source files excluded by ignore rules MUST NOT appear in the manifest | `iter_files()` line 373: `continue` skips ignored files before `yield` | **PASS** | Ignored files never yielded, never scanned, never in manifest. |

**Exclusion coverage:**

| Pattern Type | Example | Tested |
|---|---|---|
| Vendor directories | `node_modules/` | `test_ignore_directory` |
| File extensions | `*.log` | `test_ignore_by_extension` |
| Comments/blanks | `# comment`, blank lines | `test_ignore_comments_and_blanks` |
| Custom ignore path | `--ignore-file custom.ignore` | `test_explicit_ignore_file_path` |

### 4.2 Incremental / Delta Scanning (§5.2.2)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 36 | Delta detection MUST be based on deterministic signals | `_compute_delta()` line 328 | **PASS** | Comparison uses `path` (identity) and `checksum_sha256` (content hash). |
| 37 | Checksum SHOULD be primary identity for file content changes | `_compute_delta()` line 349: `current_files[p] != prev_files[p]` compares checksums | **PASS** | SHA-256 checksum comparison for modified detection. |
| 38 | Path MUST participate in added/removed detection | `_compute_delta()` lines 346-347: `p not in prev_files`, `p not in current_files` | **PASS** | Path presence/absence determines added/removed. |
| 39 | Unchanged files MAY skip deeper reprocessing | Not implemented (all files fully scanned) | **N/A** | Optimization deferred; spec says MAY. Correctness prioritized per §5.2.2 constraint. |
| 40 | Behavior MUST be correct before optimized | `_compute_delta()` performs full scan + comparison | **PASS** | All files fully scanned; delta is post-hoc comparison. |
| 41 | Incremental scanning must not alter correctness guarantees | Delta is computed after full scan; does not gate scanning | **PASS** | Delta block is additive metadata; scan pipeline unchanged. |

**Proposed shape compliance:**

| Field | Spec Shape | Implementation | Match |
|---|---|---|---|
| `previous_scan_id` | uuid string | From `prev_data["meta"]["scan_id"]` | Yes |
| `added` | sorted string array | `sorted(p for p in current if p not in prev)` | Yes |
| `modified` | sorted string array | `sorted(p for p in current if checksums differ)` | Yes |
| `unchanged` | sorted string array | `sorted(p for p in current if checksums match)` | Yes |
| `removed` | sorted string array | `sorted(p for p in prev if p not in current)` | Yes |

### 4.3 Streaming / Chunked Baseline (§5.2.3)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 42 | Preview SHOULD be extractable from a bounded prefix | `make_preview()` line 706: truncates to `preview_max_chars` | **PASS** | Preview bounded at output. |
| 43 | Baseline extraction SHOULD use streaming or chunked reads when possible | `read_sample()` line 637: 8192-byte sample for detection; `decode_text()` line 681: chardet on sample first | **PARTIAL** | Detection is sample-based. Full file read still required for preview/tag extraction. Noted in v0.1 compliance as acceptable. |
| 44 | Determinism MUST be preserved | All baseline extraction is deterministic | **PASS** | No randomness in any extraction path. |

---

## 5. Track C — Bounded Expansion

### 5.1 MIME Truth Layer (§5.3.1)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 45 | Layer MUST be descriptive only | `MimeAnalysisRecord` dataclass line 135, `analyze_mime()` line 562 | **PASS** | Record contains three descriptive fields; no actions taken based on mismatch. |
| 46 | MUST NOT block scanning | `analyze_mime()` called unconditionally; result stored but not used for gating | **PASS** | Scanning proceeds regardless of mismatch status. |
| 47 | Mismatches SHOULD be available as explicit signals | `MimeAnalysisRecord.matches_extension` field | **PASS** | Boolean flag directly indicates match/mismatch. |

**Proposed shape compliance:**

| Field | Spec Shape | Implementation | Match |
|---|---|---|---|
| `detected_mime` | string | From `detect_mime()` — content-based (python-magic) or extension fallback | Yes |
| `extension_mime` | string or null | From `mimetypes.guess_type()` — null when extension unknown | Yes |
| `matches_extension` | bool | `detected_mime == extension_mime`, or `True` when extension_mime is null | Yes |

**Mismatch signaling behavior:**

| Scenario | `matches_extension` | Rationale |
|---|---|---|
| Content MIME matches extension MIME | `True` | Normal case |
| Content MIME differs from extension MIME | `False` | Mislabeled/spoofed file |
| Extension has no known MIME | `True` | Cannot compare; no mismatch assertable |
| Content detection unavailable, extension fallback used | `True` | Both derived from extension; trivially match |

### 5.2 Specialist Metadata Expansion (§5.3.2)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 48 | Specialist tier MAY expose bounded metadata | `extract_specialist_metadata()` line 576, `_extract_pdf_metadata()` line 583 | **PASS** | PDF metadata extraction implemented when `enable_specialists=True`. |
| 49 | v0.2 MUST NOT perform OCR, full semantic parsing, layout reconstruction, table extraction, heavy content transformation, or deep document rewriting | `_extract_pdf_metadata()` line 583 | **PASS** | Extracts only from binary sample (8KB); no parsing libraries; no content transformation. |
| 50 | Specialist v0.2 may expose metadata about the file, but must not become a document processing engine | `_extract_pdf_metadata()` line 583 | **PASS** | Extracts lightweight signals (page count, text stream markers, document info strings) from the existing sample buffer. No additional file reads. |

**PDF specialist metadata fields:**

| Field | Extraction Method | Bounded | Status |
|---|---|---|---|
| `has_text_streams` | Byte pattern search in sample (`/Text`, `BT\n`, `/Font`) | Yes — sample only | **PASS** |
| `page_count` | Regex `/Count\s+(\d+)` in sample | Yes — sample only | **PASS** |
| `title` | Regex `/Title\s*\(([^)]*)\)` in sample | Yes — sample only | **PASS** |
| `author` | Regex `/Author\s*\(([^)]*)\)` in sample | Yes — sample only | **PASS** |
| `producer` | Regex `/Producer\s*\(([^)]*)\)` in sample | Yes — sample only | **PASS** |
| `creator` | Regex `/Creator\s*\(([^)]*)\)` in sample | Yes — sample only | **PASS** |
| `creation_date` | Regex `/CreationDate\s*\(([^)]*)\)` in sample | Yes — sample only | **PASS** |

**Gating behavior:**
- `specialist_metadata` is `None` when `enable_specialists=False` (default).
- `specialist_metadata` is `None` for non-PDF files even when specialists enabled.
- `specialist_metadata` is a dict for PDF files when specialists enabled.
- Extraction failures are caught and recorded as `ERR_SPECIALIST_PROBE_FAILED` errors.

### 5.3 Controlled File Type Expansion (§5.3.3)

| # | Requirement | Implementation Location | Status | Justification |
|---|---|---|---|---|
| 51 | New types should only be added if baseline decoding is straightforward | `.html`/`.htm` in `SUPPORTED_EXTENSIONS` line 31 | **PASS** | HTML is plain text; decoded by existing baseline cascade. |
| 52 | Structural signals must be deterministic | `extract_html_title()` line 772, `detect_technology()` line 822 | **PASS** | Regex-based extraction; deterministic. |
| 53 | No heavy new dependencies required | HTML processing uses only stdlib `re` module | **PASS** | No new imports. |
| 54 | Do not expand formats merely for coverage | `.html`/`.htm` only | **PASS** | Only HTML added; high downstream value for web-adjacent project repos. `.xml` and `.toml` deferred. |

**Condition checklist for `.html`/`.htm`:**

| Condition | Met | Details |
|---|---|---|
| Baseline decoding straightforward | Yes | Text file; existing encoding cascade works. |
| Structural signals deterministic | Yes | `extract_html_title()` via regex. |
| No heavy new dependencies | Yes | stdlib `re` only. |
| Behavior clearly specified | Yes | Title extraction, technology hints, tag extraction. |

---

## 6. Data Model Additions (§6)

### 6.1 Manifest-Level Additions (§6.1)

| Field | Spec | Implementation | Status |
|---|---|---|---|
| `scan_id` | string (uuid) | `ScanMeta.scan_id` line 181 | **PASS** |
| `meta` | dict | `ScanMeta` dataclass line 180, nested in `ScanManifest` | **PASS** |
| `stats` | dict | `ScanStats` dataclass line 188, nested in `ScanManifest` | **PASS** |
| `routing_summary` | dict | `RoutingSummary` dataclass line 199, nested in `ScanManifest` | **PASS** |
| `delta` | dict or null | `DeltaRecord` dataclass line 207, nullable in `ScanManifest` | **PASS** |

### 6.2 File-Level Additions (§6.2)

| Field | Spec | Implementation | Status |
|---|---|---|---|
| `mime_analysis` | `MimeAnalysisRecord` or null | `MimeAnalysisRecord` dataclass line 135; field on `FileRecord` line 174 | **PASS** |
| `specialist_metadata` | dict or null | `dict[str, Any] | None` field on `FileRecord` line 175 | **PASS** |

---

## 7. Determinism and Integrity (§7)

### 7.1 Determinism Requirements (§7.1)

| Requirement | Implementation | Status | Justification |
|---|---|---|---|
| Deterministic file ordering | `iter_files()` line 365: `sorted(root.rglob("*"))` | **PASS** | Sorted iteration. |
| Deterministic arrays and summaries | All list outputs sorted; stats derived from sorted records | **PASS** | Tags, assets, frontmatter keys, document keys, technology hints — all sorted. |
| Deterministic delta comparison | `_compute_delta()` line 328: all delta lists sorted | **PASS** | `sorted()` applied to added, removed, modified, unchanged. |
| Deterministic manifest statistics | `_compute_stats()` line 304: pure function of records | **PASS** | No randomness. |
| Deterministic mismatch signaling | `analyze_mime()` line 562: `mimetypes.guess_type()` + content detection both deterministic | **PASS** | Same file always produces same MIME analysis. |

### 7.2 Integrity Metadata (§7.2)

| Requirement | Implementation | Status | Justification |
|---|---|---|---|
| Manifest checksum present | `manifest_checksum` field on `ScanManifest` line 222 | **PASS** | SHA-256 of canonical JSON representation. |
| Checksum generation well-defined | `compute_manifest_checksum()` line 868: sets checksum to `""`, serializes with `sort_keys=True`, SHA-256 of UTF-8 bytes | **PASS** | Documented, deterministic, reproducible. |
| Checksum verifiable | Tests confirm `compute_manifest_checksum(manifest) == manifest.manifest_checksum` | **PASS** | Verified in `TestManifestChecksum.test_checksum_verifiable`. |

---

## 8. CLI and UX Additions (§8)

### 8.1 CLI Flags

| Flag | Spec (§8.2) | Implementation | Status |
|---|---|---|---|
| `--ignore-file` | Custom ignore file path | `argparse` line 919, `ScannerConfig.ignore_file` | **PASS** |
| `--previous-manifest` | Enable delta comparison | `argparse` line 920, `ScannerConfig.previous_manifest` | **PASS** |
| `--format` | `json` or `jsonl` | `argparse` line 918, choices `["json", "jsonl"]` | **PASS** |
| `--no-stats` | Optional suppression of manifest summaries | Not implemented | **NOT IMPLEMENTED** — spec lists as "candidate flag", not a requirement. Stats are always included. |

---

## 9. Testing Requirements (§9)

### 9.1 Unit Tests (§9.1)

| Required Coverage | Test Location | Status |
|---|---|---|
| Ignore rule matching | `test_edge_cases.py::TestScannerIgnore` (7 tests) | **PASS** |
| Delta classification | `test_edge_cases.py::TestDeltaScanning` (8 tests) | **PASS** |
| MIME mismatch detection | `test_edge_cases.py::TestMimeAnalysis` (7 tests), `test_unit.py::TestAnalyzeMime` (5 tests) | **PASS** |
| Manifest stats generation | `test_integration.py::TestManifestShape::test_stats_totals_consistent` | **PASS** |
| Routing summary generation | `test_integration.py::TestManifestShape::test_routing_summary_present` | **PASS** |
| JSONL serialization | `test_integration.py::TestJsonlOutput` (3 tests) | **PASS** |
| Specialist metadata extraction boundaries | `test_edge_cases.py::TestSpecialistMetadata` (7 tests), `test_unit.py::TestExtractSpecialistMetadata` (3 tests) | **PASS** |

### 9.2 Integration Tests (§9.2)

| Required Coverage | Test Location | Status |
|---|---|---|
| Scanning with ignore rules | `test_edge_cases.py::TestScannerIgnore` | **PASS** |
| Scanning with previous manifest comparison | `test_edge_cases.py::TestDeltaScanning` | **PASS** |
| Mixed supported and unsupported files | `test_integration.py::TestManifestShape::test_stats_totals_consistent` | **PASS** |
| Mismatch examples (extension vs content) | `test_edge_cases.py::TestMimeAnalysis::test_spoofed_extension_mismatch` | **PASS** |
| HTML formal support | `test_edge_cases.py::TestHtmlFormalSupport` (5 tests), `test_integration.py::TestHtmlIntegration` (3 tests) | **PASS** |

### 9.3 Golden Tests (§9.3)

| Required Coverage | Test Location | Status |
|---|---|---|
| Deterministic manifest summaries | `test_golden.py::TestDeterminism::test_repeated_scans_identical` | **PASS** |
| Deterministic delta output | `test_edge_cases.py::TestDeltaScanning::test_delta_lists_sorted` | **PASS** |
| Deterministic JSONL ordering | `test_integration.py::TestJsonlOutput::test_jsonl_records_match_json` | **PASS** |
| Identical outputs for identical inputs/config | `test_golden.py::TestDeterminism` (7 tests + 1 new MIME analysis test) | **PASS** |

### 9.4 Edge Cases (§9.4)

| Required Coverage | Test Location | Status |
|---|---|---|
| Spoofed extension files | `test_edge_cases.py::TestMimeAnalysis::test_spoofed_extension_mismatch` | **PASS** |
| Huge text files | `test_edge_cases.py::TestPreviewBounds` (2 tests) | **PASS** |
| Ignored directories | `test_edge_cases.py::TestScannerIgnore::test_ignore_directory` | **PASS** |
| Removed files between scans | `test_edge_cases.py::TestDeltaScanning::test_removed_file` | **PASS** |
| Malformed prior manifests | `test_edge_cases.py::TestDeltaScanning::test_malformed_previous_manifest` | **PASS** |
| Content-based MIME unavailable | `test_unit.py::TestDetectMime::test_known_extension_fallback` | **PASS** |
| Specialist dependency unavailable | Specialist gated by `enable_specialists` config (default False) | **PASS** |

---

## 10. Acceptance Criteria (§10)

| Criterion | Status | Evidence |
|---|---|---|
| v0.1 guarantees remain intact | **PASS** | All 176 pre-existing tests pass unchanged. |
| Ignore rules work predictably | **PASS** | 7 ignore tests pass (extension, directory, comments, coexistence with hidden, custom path). |
| Incremental comparison works correctly | **PASS** | 8 delta tests pass (added, modified, removed, unchanged, malformed manifest, sorted lists). |
| Manifest-level usability metadata exists | **PASS** | `ScanMeta`, `ScanStats`, `RoutingSummary` all populated and tested. |
| Routing summaries are accurate | **PASS** | Integration test verifies counts match actual file records. |
| JSONL output works | **PASS** | 3 JSONL tests pass (valid lines, header shape, record fidelity match). |
| MIME mismatch signaling is implemented | **PASS** | `MimeAnalysisRecord` on every file; 12 tests across unit/edge/integration/golden. |
| Bounded specialist metadata exists for at least one declared specialist format | **PASS** | PDF metadata (7 fields) extracted when specialists enabled; 10 tests across unit/edge. |
| All changes are tested and deterministic | **PASS** | 213 total tests pass; golden tests confirm determinism for all new features. |

---

## 11. Deferred Work (§11.2)

These items are explicitly deferred per the spec and are confirmed NOT present in the implementation:

| Item | Status |
|---|---|
| OCR | Not present |
| Semantic classification | Not present |
| Graph linkage | Not present |
| Confidence scoring | Not present |
| AI-based signal generation | Not present |
| Deep specialist content extraction | Not present |
| Parallel scanning | Not present |

---

## 12. Test Summary

| Module | Tests | Coverage |
|---|---|---|
| `test_unit.py` | 88 | Unit tests for all extraction/detection methods including `analyze_mime` and `extract_specialist_metadata` |
| `test_integration.py` | 52 | Full scan against fixtures; manifest shape, serialization, universal/baseline/routing tiers, MIME analysis, specialist metadata, HTML support |
| `test_golden.py` | 8 | Determinism verification including MIME analysis determinism |
| `test_edge_cases.py` | 65 | Edge cases for all features including Phase 3: MIME mismatch (7), specialist metadata (7), HTML support (5) |
| **Total** | **213** | |

---

## Summary Table

| Category | PASS | PARTIAL | FAIL | NOT IMPLEMENTED | N/A |
|---|---|---|---|---|---|
| MUST requirements | 28 | 0 | 0 | 0 | 0 |
| MUST NOT requirements | 12 | 0 | 0 | 0 | 0 |
| SHOULD requirements | 9 | 1 | 0 | 0 | 0 |
| MAY requirements | 3 | 0 | 0 | 0 | 1 |
| Candidate flags | 3 | 0 | 0 | 1 | 0 |
| **Total** | **55** | **1** | **0** | **1** | **1** |

**PARTIAL items:**
1. §5.2.3 Streaming/chunked baseline — detection is sample-based but full file read still required for preview/tag extraction. Acceptable per v0.1 compliance assessment.

**NOT IMPLEMENTED items:**
1. `--no-stats` CLI flag — listed as "candidate flag" in §8.2, not a requirement. Stats are always included.

**N/A items:**
1. §5.2.2 Unchanged file skip optimization — spec says MAY; correctness prioritized over optimization per spec constraint.

**Overall Assessment:** Scanner v0.2 is complete. All acceptance criteria from §10 are satisfied. All three implementation phases delivered. The implementation expands system usefulness more than it expands scanner complexity, consistent with the spec's final statement (§14).
