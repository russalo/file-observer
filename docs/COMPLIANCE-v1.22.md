# Compliance — file-observer v1.22.0

Maps the [v1.22.0 RFC](v1.22.0_RFC_Specification.md) to evidence. Written before merge
(CONVENTIONS release checklist). **Verdict: compliant.**

## Capability (RFC §2) → implementation

| Requirement | Implementation | Status |
|---|---|---|
| `unsupported_extension` fires ONLY on genuine non-identification | `scan_file`: `content_identified = non-octet AND trigger != extension_fallback AND not read_failed`; `recognized = content_identified AND (binary OR text-passes-veto)`; emit iff `ext not in SUPPORTED AND not recognized` | **Met** |
| Binary positively-identified → recognized | a content-derived non-octet non-text MIME → `recognized` (no veto — signature match is a positive ID) | **Met** |
| Text behavior byte-identical to v1.21 | text MIMEs still gated by the BOM/printable-ratio veto (the lying-`text/plain` arm); `_is_recognized_text`/`looks_like_text`/`_detect_unicode_bom` unchanged | **Met** |
| §6.2a no-libmagic gap KEPT | `trigger != extension_fallback` — a binary the sniff can't match falls to extension-fallback and stays flagged | **Met** |
| Recognition ≠ extraction | gate touches only the error emission; no specialist dispatch / field change | **Met** (byte-identical specialist output) |
| `supported` single source of truth | `_compute_stats`: `not-flagged-unsupported AND not-stat-failure` (replaces the `_is_recognized_text` re-derivation that under-counted recognized binary) | **Met** |

## Acceptance bar (RFC §4, falsify-first) → `tests/test_v1_22.py` (9 tests, written failing-first)

| # | Clause | Test | Result |
|---|---|---|---|
| 1 | identified binary not flagged + counted supported | `TestBinaryRecognized::test_identified_binary_not_flagged` / `_counts_supported` (real ZIP, unlisted ext) | ✅ |
| 2 | octet-stream still flagged | `TestStillFlagged::test_octet_stream_still_flagged` | ✅ |
| 3 | extension-fallback still flagged (§6.2a) | `TestStillFlagged::test_extension_fallback_still_flagged` (no-libmagic, non-AVI bytes named `.avi`) | ✅ |
| 4 | text byte-identical to v1.21 | `TestTextUnchangedFromV121` + full `test_v1_21` suite still green | ✅ |
| 5 | recognition ≠ extraction | `TestBinaryRecognized::test_recognition_is_not_extraction` | ✅ |
| 6 | workers byte-identical | `TestDeterminism::test_workers_byte_identical` | ✅ |
| 7 | version surfaces | `test_version_surfaces` (SCANNER 1.22.0 / LOGIC 1.12.0 / SCHEMA 1.13) | ✅ |

Full suite: **1061 passed.** SCHEMA.md regenerated; all drift-guards (README, contract-doc,
version-sync, SCHEMA.md) green.

## Four-leg decorrelated review

| Leg | What | Result |
|---|---|---|
| 1 · in-house (inline, no fan-out per ops directive) | multi-angle: gate truth-table, counter stat-failure carve-out, None-handling, determinism, clean-vs-degraded interaction | **No findings.** Confirmed: correctly-named binary → clean+supported; misnamed binary → supported but degraded-via-mismatch (the honest content-vs-extension signal, not the spurious flag) |
| 2 · Gemini cross-model (`gem.sh` flash, post-sunset) | falsify-first on the diff: bypass / text-regression / counter-miscount / determinism | **No findings** — confirmed the text/binary split + the supported counter |
| 3 · empirical corpus sweep | drift on tracked signals (mime/format_sig/chatlog/polyglot, libmagic on+off) + Layer-A workers-equality + the candidate-A harvest | **Clean.** **Layer-A: workers=4 byte-identical to serial on all corpora.** **Zero drift on every tracked detection signal** — the only diff is the new `format_gaps` corpus (no baseline; benign) — confirming v1.22 changes an error code's firing, not any tracked detection signal (held even vs a 1.15.0 baseline: the 1.15→1.22 span was all extraction/error changes). **Candidate-A harvest collapsed 944→4** recognized-but-flagged (139/143 remaining are genuinely octet-stream): the fix landed; the 4 are the §6.2a residual (a flagged non-octet file can only be extension-fallback or veto-failed text — never content-identified binary, by the gate's construction), correctly kept. Baseline re-anchored to 1.22.0 (it had been stale at 1.15.0). |
| 4 · PR bots (Codex / Gemini Code Assist / Copilot) | on PR open | _(triaged-and-grounded before merge)_ |

## CI matrix (the cross-platform reviewer, v1.15)
The ubuntu/macOS/Windows + forced-no-libmagic matrix caught what the local run (Linux + libmagic)
couldn't: `test_recognized_text_still_recognized` asserted an UNLISTED-extension prose file types
`text/*`, which is true only with libmagic — on the no-libmagic path the pure-Python sniff matches
only BINARY signatures, so signatureless text with an unlisted extension falls to octet-stream and
stays flagged (the documented §6.2a gap, **production behavior unchanged by v1.22**). Fix: the test
gained `@pytest.mark.requires_libmagic` (skips on the no-libmagic job), mirroring the v1.21 text
tests. **A test-side libmagic-dependency, not a production bug** — the matrix earning its keep again.

## Version axes (RFC §5)
SCANNER 1.21.2→1.22.0; **LOGIC 1.11.0→1.12.0** (routing + counter shift); **SCHEMA unchanged 1.13**
(an existing error code fires on fewer files — no new field). README/CONVENTIONS/PUBLIC_CONTRACT §3/
HISTORY/SCHEMA.md updated.

## Residuals (non-blocking, per RFC §6/§7)
- **No-libmagic binary gap (§6.2a-class):** on the pure-Python sniff path, a binary `_sniff_mime`
  can't identify falls to extension-fallback → stays flagged. Accepted (recognition rests on content,
  not `/etc/mime.types`). The deferred **puresniff signature fold-in** (RFC §6.1) would narrow it — a
  separate measured/oracle-gated slice, not this minor.
- **Candidate B** (office/media extraction specialists) unaffected — v1.22 is recognition only.
