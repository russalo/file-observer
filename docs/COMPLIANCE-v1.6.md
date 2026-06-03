# v1.6.0 Spec Compliance Report

**Report Date:** 2026-06-03
**Spec:** docs/v1.6.0_RFC_Specification.md
**Implementation:** src/file_observer/scanner.py (v1.6.0)
**Prior:** COMPLIANCE-v1.5.md (PDF specialist head+tail / whole-file read)

---

## 1. Executive Summary

- **Feature:** a corpus-scoped **`provenance` vector** — normalized production
  toolchain (producer/creator), production era (creation_date), and digitization
  origin (born-digital / scanned / OCR'd). Complements `author_aggregate` (WHO
  authored); this is WHAT-TOOL / WHEN / digitization. First of the post-v1.5
  three-minor arc; surfaced by the v1.5 PDF-work provenance findings.
- **Versions:** SCANNER 1.5.0→**1.6.0**; **LOGIC unchanged (1.4.0)** — pure
  aggregation, no routing change (like the v1.1 corpus-intelligence vectors);
  SCHEMA 1.4→**1.5** (additive `provenance` vector); vector `method_version` **1**.
- **Overall:** COMPLETE. Falsify-first; validated on `corpora_infra` (§3).
- **Tests:** 724 passed, 1 skipped (+11 in `tests/test_v1_6.py`). Goldens
  unchanged (provenance is specialist-gated, absent from default-config goldens).

## 2. Requirements (§2–§7)

| Req | Implementation | Status |
|---|---|---|
| Corpus-scoped `provenance` vector, modeled on author_aggregate | `_run_provenance` | PASS |
| toolchains: normalized producer/creator, top-N | `_normalize_toolchain` + `Counter` | PASS |
| Closed, ordered, first-match normalization table (the dictionary) | `PROVENANCE_TOOLCHAIN_RULES` | PASS |
| Unknown producers passed through, version suffix stripped | `PROVENANCE_VERSION_SUFFIX_RE` | PASS |
| production_years from `creation_date` | `_run_provenance` | PASS |
| digitization born_digital/scanned/ocr_detected/unknown (reuse v1.5 signals + OCR fingerprints) | `_classify_digitization` | PASS |
| Cross-format: PDF producer + OOXML `app.xml` `<Application>` (docx/xlsx) | `_extract_docx/xlsx_metadata` `application` | PASS |
| Corpus-only (no per-file block) — fork A | `_run_provenance` (vector only) | PASS |
| Pure observation — no LOGIC change | LOGIC 1.4.0 unchanged | PASS |
| Deterministic identity digest | `compute_vector_identity_digest` | PASS |
| No field removed/renamed/retyped | additive vector only | PASS |

## 3. Falsification & validation

Falsify-first (`tests/test_v1_6.py`): normalization (each table row; OCR flag;
unknown version-strip passthrough), digitization classification, the vector
summary (toolchains/years/digitization counts), empty-corpus zero registration,
determinism, OOXML `app.xml` extraction, and coexistence with author_aggregate.

Real-data validation (`corpora_infra`, 320 PDFs) reproduced the Wayne-K facts
(§1 of the RFC) — and, per the recurring lesson, the re-scan caught two bugs the
ASCII synthetic cases missed:
- **UTF-16BE *literal* `/Info` strings** decoded as latin-1 → mojibake
  (`þÿ M i c r o s o f t …`), so they didn't normalize. Fixed: a shared
  `_decode_pdf_bytes` (FEFF/FFFE/null → UTF-16) for BOTH the literal and hex
  paths. Guard: `test_utf16be_literal_producer_decoded`.
- **Messy version suffix** (`doPDF Ver 7.2 Build 367 (Windows … Version:`) not
  stripped — the strip regex's char class blocked colons. Fixed: permissive
  `.*$`. Guard: `test_messy_version_suffix_stripped`.

## 4. Review findings & resolution

Three review legs (in-house multi-agent `/code-review`, Gemini cross-model, PR
bots + CI).

**Leg 1 — in-house multi-agent `/code-review` (done).** 7 finder angles → verify.
CONFIRMED/PLAUSIBLE findings, all fixed falsify-first (failing input constructed
first), then re-validated on `corpora_infra` (Wayne-K facts unchanged):
- **`_decode_pdf_bytes` NUL regression (v1.5).** The `b"\x00" in raw` → UTF-16
  heuristic mojibake-d latin-1 producers with a stray/trailing NUL (e.g. null-
  terminated `doPDF 7.2\x00`). Fixed: parity-based detection (UTF-16-BE/LE only
  when the high bytes on one parity are *all* NUL). Guard:
  `test_null_terminated_latin1_producer_not_mojibaked`. On the re-scan `doPDF`
  now normalizes cleanly.
- **Determinism gap (same class chatlog's STATIC_TUNING had).** The toolchain
  table + version-suffix regex weren't in `rules_hash`, so a table edit didn't
  move the identity digest, and `test_deterministic_identity` was a tautology.
  Fixed: `provenance_rules_fingerprint()` derives the hashed string from the live
  table (can't drift); guard `TestDeterminismContract` proves an add / rename /
  OCR-flip / regex change each moves the hash.
- **`toolchains` ordering non-canonical.** `Counter.most_common` left ties in
  path order. Fixed: sort `(-count, name)` like `author_aggregate`. Guard:
  `test_toolchains_canonically_ordered`.
- **`scan` catch-all over-matched** (`Scansoft`, `ScanGauge`, `PDFScanner`).
  Fixed: word-anchored device terms (`\bscanner\b|\bcopier\b|imagerunner|…`);
  the corpus had zero real `Scanner/MFP` hits, so this is pure FP safety. Guard:
  `test_scan_substring_not_overmatched`.
- **`creation_date` bypassed shared decode + balanced-paren parse.** Fixed: route
  through `_extract_pdf_string`.
- **`lib[er]*office` sloppy char class** → `libre?office`.
- **Documented (not code) — intended scope / inherited residuals:** digitization
  inherits the PDF object-stream blind spot; `applied_to_count` = toolchain-bearing
  files (own population per block); legacy OLE2 `.doc`/`.xls` carry no `application`
  (fork B). All recorded in LIMITATIONS.md → "Provenance vector reports what's
  observable, not ground truth."
- **Test gaps closed:** doc/spreadsheet harvest branch (end-to-end docx scan),
  hex-UTF16 producer, producer→creator fallback.

Tests: **732 passed, 1 skipped** (+8 over the pre-review count). Goldens unchanged.

**Leg 2 — Gemini cross-model (done).** Self-contained prompt (full bodies of every
changed function inlined; no file reads), reviewed with the v1.6-refreshed guardrail
(reachability×blast-radius rubric + required `trigger` field + full-context clause).
- **gemini-2.5-pro (OAuth):** 1 finding, low — `_normalize_toolchain` returns a
  version-only producer (`"v7.2.1"`) unchanged rather than grouping it. **REFUTED on
  triage:** the stated mechanism ("regex strips `s` to empty → returns raw") is wrong —
  `PROVENANCE_VERSION_SUFFIX_RE` requires a leading `\s+` and `s` is whitespace-collapsed,
  so a position-0 version token never matches and `cleaned` is never empty for non-empty
  `s` (verified by direct call). The residual (version-only producers stay distinct) is
  the correct observe-don't-interpret behavior — faithfully reporting an un-normalizable
  producer beats collapsing distinct raw values into a nameless `""` bucket — and did not
  occur in 320 real PDFs. A textbook "model gets the mechanism wrong" catch by the
  grounding layer.
- **gemini-2.5-flash (API key):** `No substantiated findings.`
No code change from leg 2.

**Leg 3 — PR bots + CI**: _pending on the PR; all CONFIRMED findings fixed before merge._

## 5. Backward Compatibility

- New `provenance` vector in `vectors_collected[]` (provisional). No existing
  field removed/renamed/retyped. SCHEMA 1.4→1.5 (additive). LOGIC unchanged →
  no routing/output change for existing fields.
- OOXML specialists gain an additive `application` field (docx/xlsx).
- v1.0 public contract holds.
