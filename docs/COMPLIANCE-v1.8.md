# v1.8.0 Spec Compliance Report

**Report Date:** 2026-06-04
**Spec:** docs/v1.8.0_RFC_Specification.md
**Implementation:** src/file_observer/scanner.py (v1.8.0)
**Prior:** COMPLIANCE-v1.7.md (structural-anchor reader)

---

## 1. Executive Summary

- **Feature:** decode **object-stream PDFs** (PDF 1.5+ with the page tree compressed
  into an `/ObjStm`) that v1.7 left `page_count = null`. A tiered cascade fills them:
  **`pypdf` (tier 1, optional) → stdlib in-house decoder (tier 2) → null** — so the
  recovery works **whether or not** the optional dependency is installed. Closes the
  post-v1.5 three-minor arc (provenance → structural road → decode the index).
- **Versions:** SCANNER 1.7.0→**1.8.0**; **LOGIC unchanged (1.4.0)** — decode is
  specialist extraction, not routing; SCHEMA 1.6→**1.7** (additive provisional
  `pdf.parser` = `pypdf`/`stdlib`/`none`). `pypdf` is an optional dep
  (`file-observer[pdf]`), gated like `olefile`.
- **Overall:** COMPLETE. Decision (RFC §4): **B with an A fallback**, measured-first.
- **Tests:** 757 passed, 1 skipped (+8 in `tests/test_v1_8.py`).

## 2. Requirements (RFC §2–§6)

| Req | Implementation | Status |
|---|---|---|
| Tiered cascade pypdf → stdlib → null | `_pdf_decode_compressed` | PASS |
| Tier 1: optional pypdf, gated import, page_count + /Info only | `_pdf_via_pypdf` (pypdf gated like olefile) | PASS |
| Tier 2: stdlib decode (zlib + predictor + /W xref + /ObjStm) | `_pdf_via_stdlib` + helpers | PASS |
| Stdlib scoped to common cases; null (never wrong) on exotic | predictor/`/W` guards → None | PASS |
| Stdlib cross-validated against pypdf oracle (0 disagreements) | corpus check (§3) | PASS |
| Additive only — fill nulls, never override a v1.7 value | `_extract_pdf_metadata` guard | PASS |
| Observe-only: page_count + /Info, no text/structure | scoped wrapper | PASS |
| Provisional `pdf.parser` (pypdf/stdlib/none) | `_extract_pdf_metadata` | PASS |
| LOGIC unchanged (no routing change) | LOGIC 1.4.0 | PASS |
| Optional dep recorded; core install lean | `[pdf]` extra; gated import | PASS |
| No field removed/renamed/retyped | additive `pdf.parser` only | PASS |

## 3. Falsification & validation (measure-first, oracle-validated)

**Step 1 — pypdf-as-oracle payoff (before building).** On `corpora_infra` (655 PDFs):
of the **300** object-stream PDFs v1.7 left null, pypdf recovers **300/300 (100%)**,
with **0 read failures**; and pypdf **agrees with v1.7 on 282/282 (100%)** classic
PDFs — a flawless oracle.

**Step 2 — stdlib decoder, validated against the oracle.** Falsify-first
`tests/test_v1_8.py`: byte-accurate object-stream fixtures (xref stream + page tree
in an `/ObjStm`) that v1.7 nulls (asserted in-place) and pypdf reads. The decoder is
gated by **exact agreement with pypdf** — on 371 real object-stream corpus PDFs the
ported tier 2 **recovers 328, nulls 43 (scoped-out), and DISAGREES on 0**. It may
return null where pypdf succeeds; it never returns a different value.

**Step 3 — additive, zero regression.** On `corpora_infra`, `page_count != None`
rises **355 → 653** (with pypdf) / **355 → 616** (stdlib fallback, no dep), and
**0** of v1.7's non-null `page_count`/`producer` values changed. `producer` coverage
rises 320 → 602 (pypdf also fills compressed `/Info`).

**Step 4 — dependency-presence matrix.** Each fixture with pypdf importable AND
force-absent (monkeypatch) → the cascade picks the right tier and the values agree
(`test_pypdf_present_uses_tier1`, `test_pypdf_absent_falls_to_stdlib`).

**Residual (documented):** 2 empty-password-encrypted object-stream PDFs stay null
(the decode is gated on `not encrypted`; pypdf *could* decrypt them — a conservative
scope choice). Tier 2 nulls ~12% of object-stream PDFs (exotic predictors/filters) —
honest, never wrong.

## 4. Review findings & resolution

Four review legs (empirical sweep, in-house multi-agent `/code-review`, Gemini
cross-model, PR bots + CI).

**Leg — in-house multi-agent `/code-review` (done).** 7 finder angles → verify.
CONFIRMED findings fixed; 757 tests, corpus re-validated (653/616, oracle parity
0 disagreements — all behavior-preserving):
- **`pypdf` not in `ScanContext` (HIGH — doc-ahead-of-code, the v1.7-trigger class):**
  the docs claimed pypdf joins `ScanContext`, but `_build_context` didn't record it —
  a real determinism gap (pypdf presence/version changes `parser`/`page_count`/
  `producer` but wasn't in the context that explains cross-environment variance).
  Fixed: `deps["pypdf"] = {available, version}`.
- **Redundant whole-file reads (CONFIRMED, converged):** the stdlib decoder did its
  own `path.read_bytes()` and pypdf re-opened the path, ignoring the `whole` bytes
  `_extract_pdf_metadata` already read. Fixed: thread `whole` through the cascade —
  the stdlib tier reuses it, pypdf reads it via `io.BytesIO` (also removes any
  file-handle concern). Behavior-preserving (653/616 unchanged).
- **`_pdf_resolve_via_map` lacked the `endobj` trim** that `_resolve_obj_region` has
  (asymmetric robustness — could match a stale key in junk before `endobj`). Fixed
  for parity.
- **Stale module-docstring `Spec:`** (still v1.7.0) → v1.8.0 (removed the dup).
- Tidied: predictor loop bound to the standard `range(0, len(raw), stride)` idiom.
- **Documented / accepted (state the trade-off):** tier 2 (stdlib) fills `page_count`
  only, not `/Info` — so `producer` may be null without pypdf; this variance is now
  contractually explained by the `pypdf` ScanContext dependency (a parked residual:
  `/Info`-via-stdlib). The `not encrypted` gate skips empty-password-encrypted PDFs
  pypdf could decrypt (2 corpus PDFs) — a deliberate conservative scope. The exotic
  predictors (avg/paeth/TIFF) the stdlib decoder nulls are oracle-clean (0 disagree).

**Leg — Gemini cross-model (done).** pro + flash, v1.8-refreshed guardrail.
- **zlib decompression bomb (HIGH, pro+flash converged):** the stdlib decoder's
  `zlib.decompress(body)` was unbounded — a small flate stream expanding to GBs
  exhausts memory (the scanner reads *untrusted* files). Fixed: `_safe_inflate`
  (`decompressobj().decompress(body, cap)` + `unconsumed_tail` check) caps a single
  stream at 64 MB (`PDF_INFLATE_CAP`), refusing a bomb → null, no OOM — same
  discipline as the existing `_ZIP_MAX_DECOMPRESS`. Guard:
  `test_safe_inflate_refuses_bomb`. Re-validated: legit PDFs unaffected (653, oracle
  parity 0 disagreements).
- **Accepted/documented (scoped-out → null, never wrong):** indirect `/Length`
  (`/Length 5 0 R`, not resolved); a malformed `/ObjStm` header (odd/non-int pairs →
  caught by the top-level guard → null). Both are oracle-clean (0 disagreements) and
  recovered by pypdf; added to LIMITATIONS.

**Leg — PR bots + CI (done, PR #41).** CI green.
- **`_safe_inflate` false-positive (HIGH, gemini) — a bug in the leg-2 bomb fix:**
  keying the bomb check on `unconsumed_tail` would wrongly refuse a VALID stream that
  has trailing bytes after the zlib data (common in PDF stream bodies). Fixed: key on
  `not d.eof` (stream didn't finish within the cap). Guard extended:
  `test_safe_inflate_refuses_bomb` now asserts trailing-garbage is tolerated.
- **codex (P2) — run the cascade when page_count is present but /Info compressed:**
  valid in theory, but **measured-negligible** — exactly 1 corpus PDF is in that state
  (stream + page_count + no producer), and pypdf has no producer for it either (0
  recoverable). Declined with data: broadening the trigger would run pypdf on more
  PDFs for zero payoff (efficiency). Documented as a measured residual.

## 5. Backward Compatibility

- New provisional `specialist_metadata.pdf.parser` (`pypdf`/`stdlib`/`none`). No
  existing field removed/renamed/retyped. SCHEMA 1.6→1.7 (additive). LOGIC unchanged
  → existing routing/values unchanged; `page_count`/`producer` are strictly additive
  (null → value), never changed.
- New optional dependency `pypdf` (`file-observer[pdf]`, BSD); core install adds
  nothing. `ScanContext` records its version when present (like libmagic/chardet);
  the stdlib fallback is deterministic by `LOGIC_VERSION`.
- v1.0 public contract holds.
