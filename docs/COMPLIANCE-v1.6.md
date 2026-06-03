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
bots + CI). _To be completed on the PR; all CONFIRMED findings fixed before merge._

## 5. Backward Compatibility

- New `provenance` vector in `vectors_collected[]` (provisional). No existing
  field removed/renamed/retyped. SCHEMA 1.4→1.5 (additive). LOGIC unchanged →
  no routing/output change for existing fields.
- OOXML specialists gain an additive `application` field (docx/xlsx).
- v1.0 public contract holds.
