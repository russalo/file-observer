# v1.5.0 Spec Compliance Report

**Report Date:** 2026-06-02
**Spec:** docs/v1.5.0_RFC_Specification.md
**Implementation:** src/file_observer/scanner.py (v1.5.0)
**Prior:** COMPLIANCE-v1.4.md (content-shape chatlog gate)

---

## 1. Executive Summary

- **Fix:** the PDF specialist read only the 8 KB head, so `page_count`/`producer`
  (which live in the trailer at the file END) were null for ~all real PDFs, and
  `detect_requires_vision` mis-flagged born-digital PDFs (compressed content
  streams → no plaintext `BT`/`/Font` in the head) as needing vision. Same bug
  class the OLE2 specialists had before v0.7.1. Fix reads **head + a bounded
  tail** (stdlib, no new dependency — the file is already read for the checksum).
- **Versions:** SCANNER 1.4.0→**1.5.0**; LOGIC 1.3.0→**1.4.0** (`requires_vision`
  routing); SCHEMA 1.3→**1.4** (additive provisional `pdf.text_detected`).
- **Overall:** COMPLETE. Falsify-first; the `corpora_infra` corpus is the test bed.
- **Validated on real data (964-PDF re-scan):** `requires_vision` **310 → 12**,
  `page_count` populated **9 → 341**, `producer` **9 → 308**. 713 tests; goldens
  unchanged.

## 2. Requirements (§2–§4)

| Req | Implementation | Status |
|---|---|---|
| `_extract_pdf_metadata` reads head + bounded tail | `_pdf_scan_region(path,sample,budget)` | PASS |
| `page_count` = max `/Count` over region (root page tree) | `_extract_pdf_metadata` | PASS |
| `/Info` fields via literal `(...)` AND hex `<...>` (FEFF/UTF-16BE aware) | `_extract_pdf_string` | PASS |
| Provisional `text_detected` (`/Font`/`BT` in region) | `_extract_pdf_metadata` | PASS |
| `requires_vision`: text → false; no-text+image → true; no markers → false (conservative) | `detect_requires_vision(path,...)` | PASS |
| Bounded-observation deviation declared (head + 128 KB tail) | docstring | PASS |
| `sample_text_marker_density` retained, documented head-only | `_extract_pdf_metadata` | PASS |
| LOGIC 1.4.0 / SCHEMA 1.4 | version constants | PASS |
| No field removed/renamed/retyped | additive only | PASS |

## 3. Falsification & validation

Falsify-first (`tests/test_v1_5.py`): synthetic PDFs with metadata ONLY in the
tail (after >8 KB of marker-free filler) — the exact case the v1.4 head-only code
fails. Cases: small born-digital (head); metadata-only-in-tail (page_count 487,
producer from tail); page_count = root max (200 over 50); hex-string producer
(`<41646F6265>`→Adobe); image-only → vision; born-digital-tail → not vision;
documented-residual opaque PDF → null/false.

Real-data re-scan (the proof): the 310 born-digital false-positives flipped to
`requires_vision=False`; the remaining 12 are the genuinely scanned subset.
**No confidently-wrong value:** the big object-stream spec books return
`page_count=None` (the page tree compresses all-or-nothing, so a partial leaf
`/Count` is never surfaced as the total) — the documented residual is *null*,
not *undercount*. A false alarm during validation (California "3 pages") turned
out correct — the pieresearch mirror files are genuine 3-page excerpts.

## 4. Review findings & resolution

Three review legs (in-house multi-agent `/code-review`, Gemini cross-model, PR
bots). _To be completed on the PR; all CONFIRMED findings fixed before merge._

## 5. Backward Compatibility

- `requires_vision` values change for PDFs (the LOGIC bump) — many born-digital
  PDFs flip true→false. Golden fixtures unaffected (no born-digital-compressed PDF
  in the set; verified green). `routing_summary.requires_vision` drops on real PDFs.
- `page_count`/`producer`/`text_detected` newly populated where the head missed
  them — additive enrichment. `text_detected` is a new provisional field.
- No manifest field removed/renamed/retyped. v1.0 public contract holds.
