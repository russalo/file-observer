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
| Markers (text/image) over a fixed head+tail window (`PDF_MARKER_BUDGET`) | `_pdf_scan_region` | PASS |
| `page_count`/`/Info` over the WHOLE file (capped 64 MB), head+tail fallback | `_pdf_full_or_region` | PASS |
| `page_count` = max `/Count` anchored to `/Type /Pages` (enclosing object, to `endobj`) | `_pdf_page_count` | PASS |
| `/Info` literal `(…)` depth-aware (balanced+escaped parens) AND hex `<…>` (FEFF/UTF-16BE; odd-len pads 0); gated on `/Encrypt` | `_extract_pdf_string`, `_pdf_literal_string` | PASS |
| Provisional `text_detected` (`/Font`/`BT` in marker window) | `_extract_pdf_metadata` | PASS |
| `requires_vision`: text → false; no-text+image → true; no markers → false (conservative) | `detect_requires_vision(path,...)` | PASS |
| Bounded-observation deviation declared (markers 128 KB head+tail; metadata whole-file ≤64 MB) | docstrings | PASS |
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

**In-house multi-agent `/code-review` (2026-06-02) — real correctness bugs my
green-checks corpus missed (builder bias again), all fixed before continuing:**

1. **`page_count` over-counted (HIGH).** `/Count` is not unique to `/Pages` —
   `/Outlines` (bookmarks), annotations, AcroForms use it too; `max(/Count)`
   grabbed the largest, so a 10-page PDF with 240 bookmarks reported 240. **This
   falsified the draft's "page_count is null, never wrong" claim** (the corpus had
   no bookmark-heavy PDFs). Fixed: anchor `/Count` to a `/Type /Pages` dict; read
   the **whole file** (capped 64 MB) in the specialist so the root page tree is
   found wherever it sits (also fixes the unread-middle *under*-count). Guards:
   `test_outlines_count_not_page_count`, `test_root_count_in_unread_middle`.
   Re-scan: `page_count` max 375, **zero** over-count suspects (was inflated).
2. **`/Info` string truncation (MEDIUM).** `Title (… \(x\) …)` truncated at the
   escaped paren. Fixed: honor PDF backslash escapes + unescape. Guard:
   `test_escaped_paren_title`.
3. **Encrypted `/Info` → ciphertext garbage.** Fixed: gate string extraction on
   `/Encrypt` (→ null). Guard: `test_encrypted_info_not_garbage`.
4. **`%PDF-` anchored at offset 0** → null version for leading-BOM PDFs. Fixed:
   search the first 1 KB. Guard: `test_pdf_version_leading_bom`.
5. **Marker-budget inconsistency** between the two tiers (could make `text_detected`
   and `requires_vision` disagree). Fixed: both use `PDF_MARKER_BUDGET` (fixed
   128 KB head+tail).
6. Added `/JBIG2Decode` to the image-marker set; fixed a latent
   `SCHEMA_VERSION >= "1.3"` string-compare in `test_v1_4` (tuple compare).

Post-fix: 709 passed, 1 skipped; corpus re-scan `requires_vision` 12,
`page_count` 353 populated (no over-counts), `producer` 320.

**Gemini cross-model (gemini-2.5-flash, 2026-06-02 — pro run hit the CLI's
`Invalid stream` flakiness; flash succeeded):**

7. **(HIGH, confirmed) page-count window too small for a flat page tree.** The
   `±256`-byte window around `/Type /Pages` missed `/Count` when a large `/Kids`
   array sat between them (a 100-kid flat tree → `/Count` ~800 B away →
   `page_count=None`). Fixed: search the **enclosing dict** (forward to `>>`,
   capped 64 KB; short backward fallback). Guard: `test_flat_page_tree_big_kids`.
8. **(preempted) ReDoS in the `/Info` escaped-string regex.** `(?:\\.|[^()])*`
   let `\` match both branches → catastrophic backtracking on `\\\\…` with no
   closing paren. Fixed to `(?:\\.|[^()\\])*` (linear; 4 000-backslash input
   returns in <1 ms).
- Documented/intentional (no change): the 64 MB whole-file cap (opt-in
  specialist, file already hashed); `>64 MB` head+tail fallback (a documented
  residual — RFC §1.2); encrypted `/Info` → null (intentional, anti-garbage);
  `sample_text_marker_density` head-only (retained legacy metric, `text_detected`
  is the real signal).

Post-Gemini: 710 passed, 1 skipped.

**PR bots — Codex, Gemini Code Assist, Copilot (PR #35, 2026-06-02):**

9. **(Gemini HIGH + Codex P2, confirmed) Nested dict hid `/Count`.** The
   page-count search stopped at the first `>>`, which a nested `/Resources<<…>>`
   in the `/Pages` object closed early → `page_count=None`. Fixed: span to
   `endobj`. Guard: `test_nested_dict_in_pages_object`.
10. **(Codex P2, confirmed) Balanced unescaped parens in `/Info` strings**
    (`Title (Report (v2) Final)`) truncated. Fixed: a depth-aware literal-string
    parser (`_pdf_literal_string`) handling balance + escapes. Guard:
    `test_balanced_parens_title`.
11. **(Gemini, confirmed) Odd-length hex string** → null. Fixed: pad a trailing
    0 per ISO 32000 §7.3.4.3. Guard: `test_odd_length_hex_string`.
12. **(Copilot ×6) DOC/CODE DRIFT from the rework** — the high-value catch again:
    RFC §2/§3, LIMITATIONS, this Requirements table, and HISTORY still described
    the *first* (head+tail-only, un-anchored `max(/Count)`, `pdf_text_in_tail`
    trigger) design, not the reworked whole-file/anchored one. All corrected.
    The unused `budget` param is now documented (caller-uniform; PDF read sizes
    use the dedicated constants by design).
- CI: a new `tests.yml` workflow runs the suite on every push/PR (it first caught
  a test depending on an untracked local fixture — fixed with a whitelisted
  `sample_*` dated fixture).

Final: **713 passed, 1 skipped**; CI green; `corpora_infra` re-scan unchanged
(requires_vision 12, page_count populated, no over-counts).

## 5. Backward Compatibility

- `requires_vision` values change for PDFs (the LOGIC bump) — many born-digital
  PDFs flip true→false. Golden fixtures unaffected (no born-digital-compressed PDF
  in the set; verified green). `routing_summary.requires_vision` drops on real PDFs.
- `page_count`/`producer`/`text_detected` newly populated where the head missed
  them — additive enrichment. `text_detected` is a new provisional field.
- No manifest field removed/renamed/retyped. v1.0 public contract holds.
