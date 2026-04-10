# v0.6 Spec Compliance Report

**Report Date:** 2026-04-10
**Spec:** docs/v0.6.0_RFC_Specification.md
**Implementation:** src/scanner/scanner.py
**Prior Compliance:** docs/COMPLIANCE-v0.5.md (v0.5 — all requirements PASS)

---

## 1. Executive Summary

- **Spec Version:** v0.6.0 RFC Specification (2026-04-09)
- **Implementation Version:** 0.6.0 (pyproject.toml, SCANNER_VERSION aligned)
- **Schema Version:** 0.6
- **Overall Compliance Assessment:** COMPLETE — all three features implemented and tested. All acceptance criteria satisfied.
- **High-Level Findings:**
  - Configurable extraction depth with per-extension overrides and named profiles
  - Structural file signatures with polyglot detection on every file
  - Data integrity envelope with chain of custody and HMAC-SHA256 signing
  - Specialist MIME guard prevents wrong-format extraction
  - Signing key excluded from serialized manifest config (PR review fix)
  - All v0.5 guarantees preserved. 363 tests.
- **Critical Deviations:** None.
- **Security Fix:** `signing_key` and `signing_key_id` excluded from `meta.config` serialization to prevent credential leakage to manifest output.

---

## 2. Feature A — Configurable Extraction Depth (§2)

### 2.1 specialist_budget (§2.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 1 | Replaces hardcoded 128KB deviation | `ScannerConfig.specialist_budget = 131072`; passed to `_extract_xlsx_metadata(path, budget)` and `_extract_docx_metadata(path, budget)` | **PASS** |
| 2 | Recorded in meta.config | Present via filtered `asdict(self.config)` | **PASS** |
| 3 | Recorded in provenance `detail.read_budget_bytes` | `prov_detail["read_budget_bytes"] = eff["specialist_budget"]` | **PASS** |

### 2.2 extension_overrides (§2.3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 4 | Overrides apply to baseline_max_bytes, specialist_budget, preview_max_chars | `effective_for()` merges all three from override dict | **PASS** |
| 5 | Overrides MUST NOT apply to sample_size | `effective_for()` only resolves three named fields; sample_size not included | **PASS** |
| 6 | Effective config resolved at start of scan_file() | `eff = self.config.effective_for(extension)` before any extraction | **PASS** |
| 7 | Effective baseline_max_bytes >= sample_size | `max(base["baseline_max_bytes"], self.sample_size)` in `effective_for()` | **PASS** |
| 8 | extension_overrides appears in meta.config | Present via config serialization | **PASS** |

### 2.3 Named Profiles (§2.4)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 9 | fast_sort: 8192 baseline, specialists off | `SCAN_PROFILES["fast_sort"]` matches | **PASS** |
| 10 | general: 65536 baseline, specialists off | `SCAN_PROFILES["general"]` matches | **PASS** |
| 11 | deep_extract: 1MB baseline, 512KB specialist, specialists on | `SCAN_PROFILES["deep_extract"]` matches | **PASS** |
| 12 | Profiles are sugar — set config values only | Profiles are dicts applied to ScannerConfig fields | **PASS** |
| 13 | --override applies after profile | CLI parses overrides after profile application | **PASS** |

---

## 3. Feature B — Structural File Signatures (§3)

### 3.1 file_signature (§3.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 14 | First 16 bytes as lowercase hex | `scan_signatures()`: `sample[:sig_len].hex()` | **PASS** |
| 15 | magic_length = number of bytes captured | `min(16, len(sample))` | **PASS** |
| 16 | null for zero-byte files | `if not sample: return None, [], False` | **PASS** |
| 17 | Extracted from existing sample buffer | Uses `sample` parameter, no additional reads | **PASS** |

### 3.2 format_signatures (§3.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 18 | All recognized signatures found in sample | Scans `MAGIC_SIGNATURES` table against sample | **PASS** |
| 19 | Scanned against built-in signature table | `MAGIC_SIGNATURES` constant — 9 patterns (PNG, JPEG, PDF, ZIP, OLE, RTF, GIF x2, RIFF) | **PASS** |
| 20 | Sorted by offset | `found.sort(key=lambda x: x["offset"])` | **PASS** |
| 21 | Empty list when no signatures match | Returns `[]` | **PASS** |

### 3.3 is_polyglot (§3.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 22 | True when multiple distinct formats detected | `is_polyglot = len(seen_formats) > 1` | **PASS** |
| 23 | False otherwise | Default | **PASS** |

### 3.4 Signature Table (§3.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 24 | offset=0 means file start only | `sample[offset:offset + len(pattern)] == pattern` | **PASS** |
| 25 | offset=None means scan entire sample | `sample.find(pattern)` | **PASS** |
| 26 | Table is deterministic and stable | Constant list, no runtime modification | **PASS** |

### 3.5 Specialist MIME Guard (§3.3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 27 | Skip extraction if mime_type not in guard set | `if guard and mime_type not in guard:` → skip, record error | **PASS** |
| 28 | Record specialist_probe_failed error | Error with message "mime_type X does not match expected formats" | **PASS** |
| 29 | Prevents misleading metadata | Verified: `actually_text.pdf` gets specialist skipped, metadata is null | **PASS** |

---

## 4. Feature C — Data Integrity Envelope (§4)

### 4.1 Chain of Custody (§4.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 30 | previous_manifest_checksum on DeltaRecord | `DeltaRecord.previous_manifest_checksum` field | **PASS** |
| 31 | Read from previous manifest's manifest_checksum | `prev_checksum = prev_data.get("manifest_checksum")` | **PASS** |
| 32 | Enables chain verification | Manifest N's `previous_manifest_checksum` matches manifest N-1's `manifest_checksum` | **PASS** |
| 33 | null when no previous manifest | Delta is None entirely when no previous manifest | **PASS** |

### 4.2 Manifest Signing (§4.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 34 | manifest_signature null when signing_key not set | `if self.config.signing_key:` guards signing block | **PASS** |
| 35 | manifest_signature MUST NOT be in checksum preimage | `d["manifest_signature"] = None` in `compute_manifest_checksum()` | **PASS** |
| 36 | key_id is a stable identifier, not the key itself | `signing_key_id` config field; key never in manifest | **PASS** |
| 37 | Signing deterministic: same checksum + same key = same signature | HMAC-SHA256 is deterministic; verified in `test_signature_deterministic` | **PASS** |
| 38 | HMAC-SHA256 over manifest_checksum | `hmac.new(key, checksum, "sha256")` | **PASS** |

### 4.3 Security (PR review fix)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 39 | signing_key excluded from serialized config | `meta.config` filters out `signing_key` and `signing_key_id` | **PASS** |

---

## 5. Schema Impact (§5)

| Field | Location | Type | Present | Status |
|---|---|---|---|---|
| `file_signature` | FileRecord | object or null | Yes | **PASS** |
| `format_signatures` | FileRecord | list | Yes | **PASS** |
| `is_polyglot` | FileRecord | bool | Yes | **PASS** |
| `manifest_signature` | ScanManifest | object or null | Yes | **PASS** |
| `delta.previous_manifest_checksum` | DeltaRecord | string or null | Yes | **PASS** |

No fields removed, renamed, or retyped. Schema version is `"0.6"`.

---

## 6. Acceptance Criteria (§7)

| Criterion | Status |
|---|---|
| specialist_budget configurable, replaces hardcoded deviation | **PASS** |
| extension_overrides works for baseline_max_bytes, specialist_budget, preview_max_chars | **PASS** |
| Named profiles produce correct config values | **PASS** |
| file_signature exposes first 16 bytes as hex on every file | **PASS** |
| format_signatures lists all detected signatures in sample | **PASS** |
| is_polyglot true when multiple distinct formats detected | **PASS** |
| Specialist MIME guard prevents wrong-format extraction | **PASS** |
| previous_manifest_checksum links delta scans cryptographically | **PASS** |
| manifest_signature signs the checksum when key is configured | **PASS** |
| All v0.5 tests pass without modification | **PASS** |
| schema_version is "0.6" | **PASS** |

---

## 7. Test Summary

| Module | Tests |
|---|---|
| `test_unit.py` | 208 |
| `test_integration.py` | 52 |
| `test_golden.py` | 8 |
| `test_edge_cases.py` | 95 |
| **Total** | **363** (362 passed, 1 skipped) |

---

## 8. Summary Table

| Category | PASS | PARTIAL | FAIL |
|---|---|---|---|
| Configurable depth | 13 | 0 | 0 |
| Structural signatures | 16 | 0 | 0 |
| Integrity envelope | 10 | 0 | 0 |
| **Total** | **39** | **0** | **0** |

**Overall Assessment:** v0.6.0 is complete. The scanner is now configurable (dip switches), honest about file content (structural signatures, polyglot detection), and verifiable as an integrity record (chain of custody, HMAC signing). Three features closer to 1.0 maturity.
