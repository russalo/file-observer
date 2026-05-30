# v0.5 Spec Compliance Report

**Report Date:** 2026-04-09
**Spec:** docs/v0.5.0_RFC_Specification.md
**Implementation:** src/scanner/scanner.py
**Prior Compliance:** docs/COMPLIANCE-v0.3.md (v0.3 — all requirements PASS)

---

## 1. Executive Summary

- **Spec Version:** v0.5.0 RFC Specification (2026-04-09)
- **Implementation Version:** 0.5.0 (pyproject.toml, SCANNER_VERSION, LOGIC_VERSION all aligned)
- **Overall Compliance Assessment:** COMPLETE — all three phases implemented and tested. All acceptance criteria satisfied. This is the last breaking release before v1.0 schema freeze.
- **High-Level Findings:**
  - `schema_version` field present on every manifest (`"0.5"`)
  - Specialist metadata namespaced by format category (pdf/image/email/spreadsheet/document)
  - Baseline reads capped at `baseline_max_bytes` (64KB default)
  - Frontmatter and PDF text markers handle CRLF
  - Path normalization uses `as_posix()` throughout
  - ZIP entry validation rejects drive letters, mixed separators, current-dir references
  - XML/TOML parse failures recorded as errors (no longer silent)
  - Specialist null results logged
  - Structural provenance added for title and document_keys
  - Truncated-file guard prevents false parse errors on files larger than baseline cap
- **Critical Deviations:** None.
- **All v0.1–v0.4 guarantees preserved.** 336 tests passing.

---

## 2. Schema Changes (§2)

### 2.1 Schema Version Field (§2.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 1 | `schema_version` MUST be `"0.5"` | `SCHEMA_VERSION = "0.5"` line 74; `ScanManifest.schema_version` | **PASS** |
| 2 | MUST be included in deterministic checksum preimage | `compute_manifest_checksum()` — `schema_version` is part of `asdict(manifest)` | **PASS** |
| 3 | v1.0 will bump to `"1.0"` with no other shape change | Documented in v1.0.0_RFC_DRAFT.md | **PASS** (design) |

### 2.2 Namespaced Specialist Metadata (§2.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 4 | `specialist_metadata` namespaced by format category | `SPECIALIST_NAMESPACE` dict maps extensions to namespace keys; `scan_file()` wraps raw metadata in `{ns: raw_metadata}` | **PASS** |
| 5 | `null` when specialists disabled or no specialist applies | Unchanged from v0.4 | **PASS** |
| 6 | Exactly one key (the namespace) when populated | `specialist_metadata = {ns: raw_metadata}` — single key | **PASS** |
| 7 | Namespace keys stable across minor versions | Documented as contract in v0.5 RFC | **PASS** |

**Namespace registry compliance:**

| Namespace | Extensions | Fields present | Status |
|---|---|---|---|
| `pdf` | `.pdf` | has_text_streams, page_count, title, author, producer, creator, creation_date, encrypted, pdf_version, sample_text_marker_density | **PASS** |
| `image` | `.png`, `.jpg`, `.jpeg` | width, height, bit_depth (PNG) / width, height (JPEG) | **PASS** |
| `email` | `.msg`, `.eml` | subject, from, to, date, message_id, has_attachments | **PASS** |
| `spreadsheet` | `.xlsx` | sheet_names, header_rows | **PASS** |
| `document` | `.docx`, `.doc`, `.rtf` | title, author, word_count (DOCX), heading_count (DOCX) | **PASS** |

### 2.3 Configurable Baseline Depth (§2.3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 8 | `baseline_max_bytes` defaults to 65536 (64KB) | `ScannerConfig.baseline_max_bytes = 65536` | **PASS** |
| 9 | `decode_text()` reads at most `baseline_max_bytes` | `f.read(max_bytes)` where `max_bytes = max(baseline_max_bytes, sample_size)` | **PASS** |
| 10 | `hash_file()` continues to stream full file | Unchanged — reads in 1MB chunks | **PASS** |
| 11 | `baseline_max_bytes` >= `sample_size` enforced | `max(self.config.baseline_max_bytes, self.config.sample_size)` | **PASS** |
| 12 | `baseline_max_bytes` recorded in `meta.config` | Present via `asdict(self.config)` | **PASS** |

---

## 3. Cross-Platform Hardening (§3)

### 3.1 CRLF Handling (§3.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 13 | `FRONTMATTER_RE` uses `\r?\n` | `r"\A---\r?\n(.*?)\r?\n---\r?\n"` | **PASS** |
| 14 | `FRONTMATTER_OPEN_RE` uses `\r?\n` | `r"\A---\r?\n"` | **PASS** |
| 15 | PDF text markers include `BT\r\n` | Added to both `_extract_pdf_metadata` and `detect_requires_vision` | **PASS** |
| 16 | Line-based parsing normalizes line endings | Malformed frontmatter split uses `text.replace("\r\n", "\n")` | **PASS** |

### 3.2 Path Normalization (§3.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 17 | Use `Path.as_posix()` instead of `str.replace("\\", "/")` | All three occurrences replaced: `_is_ignored`, `scan_file` error path, `scan_file` normal path | **PASS** |

### 3.3 ZIP Entry Validation (§3.3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 18 | Reject drive letter paths | `if len(normalized) > 1 and normalized[1] == ":"` | **PASS** |
| 19 | Normalize mixed separators | `normalized = name.replace("\\", "/")` before all checks | **PASS** |
| 20 | Reject current-directory references | `normalized.startswith("./") or "/./" in normalized` | **PASS** |

### 3.4 Documentation (§3.4)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 21 | `exclude_hidden` documented as Unix dot-prefix only | README Platform notes section | **PASS** |
| 22 | `python-magic-bin` recommended for Windows | README Platform notes section | **PASS** |

---

## 4. Silent Failure Fixes (§4)

### 4.1 XML Parse Failures (§4.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 23 | Record `xml_parse_failed` when `xml_fromstring()` raises | Error recorded in `scan_file()` after `extract_xml_keys()` returns empty | **PASS** |
| 24 | Only record when file was NOT truncated by baseline cap | `file_was_truncated = stat.st_size > max(baseline_max_bytes, sample_size)` guard | **PASS** |
| 25 | `structural.document_keys` MUST be `[]` on failure | `extract_xml_keys()` returns `[]` on exception | **PASS** |

### 4.2 TOML Parse Failures (§4.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 26 | Record `toml_parse_failed` when `tomllib.loads()` raises | Error recorded with truncation guard | **PASS** |
| 27 | Only record when file was NOT truncated | Same `file_was_truncated` guard as XML | **PASS** |

### 4.3 Specialist Null Results (§4.3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 28 | Record `specialist_probe_failed` when specialist returns `None` for registered tool | `if raw_metadata is None and extension in SPECIALIST_TOOLS` → error appended | **PASS** |

---

## 5. Provenance Updates (§5)

### 5.1 Namespaced Keys (§5.1)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 29 | Provenance keys use namespaced paths | `specialist_metadata.pdf.page_count` (not `specialist_metadata.page_count`) | **PASS** |

### 5.2 Recommended Provenance (§5.2)

| Field | Method | Trigger | Status |
|---|---|---|---|
| `structural.title` (markdown) | `extract_md_title` | `markdown_h1` | **PASS** |
| `structural.title` (HTML) | `extract_html_title` | `html_title_tag` | **PASS** |
| `structural.document_keys` (JSON) | `extract_json_keys` | `json_loads` | **PASS** |
| `structural.document_keys` (YAML) | `extract_yaml_keys` | `yaml_line_parse` | **PASS** |
| `structural.document_keys` (XML) | `extract_xml_keys` | `xml_etree` | **PASS** |
| `structural.document_keys` (TOML) | `extract_toml_keys` | `tomllib` | **PASS** |

---

## 6. Acceptance Criteria (§7)

| Criterion | Status |
|---|---|
| `schema_version` is `"0.5"` on every manifest | **PASS** |
| `specialist_metadata` is namespaced | **PASS** |
| `baseline_max_bytes` defaults to 64KB and caps text extraction | **PASS** |
| Frontmatter and PDF markers handle CRLF | **PASS** |
| Paths use `as_posix()` | **PASS** |
| ZIP validation rejects drive letters and mixed traversal | **PASS** |
| XML/TOML failures produce error records | **PASS** |
| Provenance keys use namespaced specialist paths | **PASS** |
| All tests pass | **PASS** (336 passed, 1 skipped) |
| Platform limitations documented | **PASS** |

---

## 7. Test Summary

| Module | Tests |
|---|---|
| `test_unit.py` | 182 |
| `test_integration.py` | 52 |
| `test_golden.py` | 8 |
| `test_edge_cases.py` | 95 |
| **Total** | **337** (336 passed, 1 skipped — no .doc fixtures) |

---

## 8. Summary Table

| Category | PASS | PARTIAL | FAIL |
|---|---|---|---|
| Schema changes | 12 | 0 | 0 |
| Cross-platform hardening | 10 | 0 | 0 |
| Silent failure fixes | 6 | 0 | 0 |
| Provenance updates | 8 | 0 | 0 |
| **Total** | **36** | **0** | **0** |

**Overall Assessment:** v0.5.0 is complete. The manifest shape is ready for v1.0 schema freeze. All breaking changes have landed. From here, v1.0 is a version bump and a compatibility policy — no code changes.
