# v1.7.0 Spec Compliance Report

**Report Date:** 2026-06-03
**Spec:** docs/v1.7.0_RFC_Specification.md
**Implementation:** src/file_observer/scanner.py (v1.7.0)
**Prior:** COMPLIANCE-v1.6.md (production-provenance vector)

---

## 1. Executive Summary

- **Feature:** a **structural-anchor reader** for PDF — follow the file's own index
  (`startxref` → latest trailer → root catalog → page tree), parsing the classic
  xref table for object offsets and following `/Prev` across incremental updates,
  instead of v1.5's "read ≤64 MB and regex-scan a window". Generalizes the
  tail-index lesson OLE2 (v0.7.1) and PDF (v1.5) each learned per-format.
- **Versions:** SCANNER 1.6.0→**1.7.0**; **LOGIC unchanged (1.4.0)** — index reads
  are specialist extraction, not routing (the `requires_vision` marker window is
  untouched); SCHEMA 1.5→**1.6** (additive provisional `pdf.xref_type`); new
  `signal_provenance.trigger` value `structural_anchor`.
- **Overall:** COMPLETE. Falsify-first; validated on `corpora_infra` (§3).
- **Tests:** 742 passed, 1 skipped (+8 in `tests/test_v1_7.py`). Goldens unchanged
  (PDF specialist is gated; goldens run default config).

## 2. Requirements (RFC §2–§7)

| Req | Implementation | Status |
|---|---|---|
| Declared structural-anchor table, keyed off format ID | `STRUCTURAL_ANCHORS` | PASS |
| PDF index via `startxref` → trailer → root → page tree | `_pdf_anchor` + `_parse_classic_xref` | PASS |
| Parse classic xref table → object→offset map (resolve by offset) | `_parse_classic_xref` / `_resolve_obj_region` | PASS |
| Follow `/Prev` (incremental updates), bounded, latest-wins | `_parse_classic_xref` (PDF_XREF_PREV_HOPS) | PASS |
| Root count, not max over superseded fragments | `_pdf_count_via_map` | PASS |
| xref-stream: read plaintext dict for /Root,/Info; recover producer | `_pdf_anchor` (stream branch) + `_locate_regular_obj` | PASS |
| `page_count` for compressed object-stream page trees → null (→ v1.8) | honest null | PASS |
| Provisional `pdf.xref_type` (classic/stream/none) | `_extract_pdf_metadata` | PASS |
| Graceful fallback to v1.5 window on broken/absent anchor (never raise) | field-by-field fallback | PASS |
| LOGIC unchanged (no routing change; marker window untouched) | LOGIC 1.4.0 | PASS |
| > FULL_READ_CAP PDFs resolved by offset-seek (not whole-file read) | `_resolve_obj_region` seek | PASS |
| ZIP/OLE2 documented as already-structural, no behavior change | `STRUCTURAL_ANCHORS` (doc only) | PASS |
| No field removed/renamed/retyped | additive `xref_type` only | PASS |

## 3. Falsification & validation

Falsify-first (`tests/test_v1_7.py`, written failing-first against v1.5 — 5 of 8
failed before the implementation, proving they exercise new behavior): byte-accurate
synthetic PDFs with real xref tables —
- **incremental update** (superseded `/Count 10` + current root `/Count 3` → assert
  the root wins, the bug v1.5's `max(/Count)` exhibits);
- **xref stream** (assert `xref_type=stream` + producer recovered from the plaintext
  dict);
- **broken `startxref`** (assert graceful fallback, no raise);
- **linearized / two `startxref`** (assert the last one wins);
- **> cap** (pad the page tree past the head sample + tail window, cap below file
  size → assert the offset-seek still resolves where v1.5 returns null).

Real-data validation (`corpora_infra`, 655 PDFs): **0 `page_count` changes, 0
`producer` changes vs v1.6** — zero regression (v1.5's whole-file scan already
covered single-revision classic PDFs ≤64 MB, the common case). The win is precision
on incremental updates (unit-proven; not exercised by this corpus), efficiency,
altitude, and the v1.8 setup — reported plainly per the RFC, even though it is a
near-zero real-data diff. **New observable:** `xref_type` reveals **373/655 (57%)
object-stream** — the population whose compressed page tree returns `page_count=null`
and that sizes the v1.8 decision.

The full empirical sweep (restored to v1.7 and extended to track `corpora_infra` +
the new `pdf_signal` dimension) self-compares **NO DRIFT**; across the four
previously-unswept releases (v1.4→v1.7) it confirms **zero detection drift** in
chatlog/polyglot/format_sig/mime on ~18k real files.

## 4. Review findings & resolution

Four review legs (empirical sweep [done — NO DRIFT], in-house multi-agent
`/code-review`, Gemini cross-model, PR bots + CI). _In-house + Gemini + bots to be
completed on the PR; all CONFIRMED findings fixed before merge._

## 5. Backward Compatibility

- New provisional `specialist_metadata.pdf.xref_type` (classic/stream/none). No
  existing field removed/renamed/retyped. SCHEMA 1.5→1.6 (additive). LOGIC unchanged
  → no routing/output change for existing fields; on the corpus, `page_count` and
  `producer` are byte-identical to v1.6 (zero regression).
- New `signal_provenance.trigger` value `structural_anchor` (a new value of an
  existing free-string field, not a new field/type).
- v1.0 public contract holds.
