# v1.3.0 Spec Compliance Report

**Report Date:** 2026-06-02
**Spec:** docs/v1.3.0_RFC_Specification.md
**Implementation:** src/file_observer/scanner.py (v1.3.0)
**Prior:** COMPLIANCE-v1.2.md (v1.2 + patches v1.2.1–v1.2.4)

---

## 1. Executive Summary

- **Feature:** pure-Python content-based MIME fallback (no libmagic) + RIFF disambiguation. `detect_mime` gains a magic-signature tier between libmagic and the extension fallback; `MAGIC_SIGNATURES` generalized to a multi-constraint matcher and expanded to ~24 formats.
- **Versions:** SCANNER 1.2.4→1.3.0; **LOGIC 1.1.4→1.2.0** (new MIME-detection routing); SCHEMA **unchanged 1.2** (no new manifest fields; `magic_signature_fallback` is a new *value* of the existing `signal_provenance.trigger` free-string field).
- **Overall:** COMPLETE. All §8 acceptance criteria met. Reviewed by the in-house multi-agent `/code-review` (20 agents) AND a Gemini-2.5-pro cross-model pass — both weighted to polyglot/`format_signatures` stability.
- **Tests:** 660 passed, 1 skipped (+33 in `tests/test_v1_3.py`).
- **Determinism / polyglot:** verified stable (see §3).

## 2. Requirements (§2–§6)

| Req | Implementation | Status |
|---|---|---|
| Cascade libmagic → sniff → extension → octet-stream | `detect_mime` tiers; new trigger `magic_signature_fallback` | PASS |
| Sniff runs on libmagic absent AND exception, no extra I/O | `read_sample` moved before `detect_mime`, sample passed in | PASS |
| Multi-constraint matcher, behavior-preserving for existing entries | `_signature_matches` (shared by sniff + `scan_signatures`) | PASS |
| ~24 formats incl. archives/images/data/exe/media | `MAGIC_SIGNATURES` | PASS |
| RIFF → WebP/WAV/AVI; generic `riff_container` retained, format_signatures-only | sub-types + retained generic, suppressed when a sub-type matches | PASS |
| Text-gate (§2.1) — no prose misclassification | `_sniff_mime` returns None on `looks_like_text` | PASS |
| LOGIC 1.2.0, SCHEMA 1.2 | version constants | PASS |
| No manifest field removed/renamed/retyped | additive only | PASS |

## 3. Polyglot / format_signatures stability (the headline concern)

- **No golden impact:** goldened fixtures all use pre-existing signatures; output unchanged. Verified (test_golden green).
- **RIFF single-match:** a WAV matches `audio/wav` only (generic `riff_container` suppressed) → `is_polyglot=False`. An unknown RIFF (e.g. ACON) still emits `riff_container` (continuity preserved). Verified (`test_v1_3.py`).
- **Anchored signatures don't mid-file match** (Gemini's polyglot concern, refuted): the only find-anywhere signature is the pre-existing `%PDF-`; all new signatures are offset-anchored. The expansion does not introduce polyglot instability. Verified.
- Corpus sweep: NO DRIFT on chatlog detection (the `scan_file` reorder is safe).

## 4. Review findings & resolution

Two independent reviews (in-house multi-agent + Gemini) found real issues; all CONFIRMED ones were fixed before merge:

| Finding | Resolution |
|---|---|
| HIGH — short signatures (`MZ`/`BM`/`ID3`/`BZh`) misclassify prose as binary (no-libmagic path) | **Fixed** — text-gate on `_sniff_mime` (§2.1). The RFC's "moderate FP risk, acceptable" call was overruled by the review. |
| HIGH — implementation dropped the generic `riff_container` (spec §4 said retain) → unknown RIFF lost its `format_signature` | **Fixed** — retained + suppressed-on-sub-type. Code now matches the approved spec. |
| HIGH — reason label mislabeled libmagic-present-but-empty as `libmagic_exception` | **Fixed** — distinguishes `unavailable`/`empty`/`exception`. |
| LOW — `_signature_matches((), …)` returned 0 (false match) for empty constraints | **Fixed** — guard returns `None`. |
| LOW — PUBLIC_CONTRACT not updated | **Fixed** — §3 note added (schema unchanged). |
| MEDIUM — MP4 `ftyp`@4 leaves bytes 0-3 free → theoretical polyglot co-fire | **Accepted** (Russell's call) — real co-fire near-impossible (a real file would need an offset-0 magic AND `ftyp` at byte 4). Noted. |
| LOW — fewer `mime_type_fallback` errors → lower `degraded_files` in no-libmagic scans | **Accepted** — intended improvement (detection is genuinely less degraded). |
| Gemini — expansion raises polyglot risk via mid-file matches | **Refuted** — anchored signatures can't mid-file match (see §3). |

**Process note:** the review caught a place where implementation silently deviated from the approved spec (RIFF) and an FP class the author (Claude) had dismissed in the RFC (short signatures). Both reviews — cross-model and in-house multi-agent — were necessary; they surfaced *different* issues. This is the "run both" conclusion from the v1.2.x arc, validated again.

## 5. Verdict

**PASS.** Pure-Python MIME fallback shipped additively; polyglot/`format_signatures` stability verified; all confirmed review findings resolved; v1.0 contract intact.
