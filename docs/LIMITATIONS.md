# Limitations

File Observer is an **observation layer**. It reports what it can see, within
declared bounds, deterministically. This document states plainly what it does
**not** do, so consumers can apply their own judgment on top of its output.

## It does not make threat or content judgments

`safety_flags` (`has_javascript`, `has_macros`, `has_ole_objects`,
`has_external_references`) are **structural observations, not threat
assessments**. A flag means "this structure was observed," not "this file is
dangerous." File Observer never quarantines, scores, or verdicts a file. Apply
your own threat model to the observations.

## It observes within bounds — null means "not seen here," not "not present"

Observation is bounded by design:

- Content preview is capped (default 1000 chars).
- Baseline text analysis reads a bounded window (`baseline_max_bytes`, default
  64 KB).
- Specialist extraction reads within a budget (`specialist_budget`, default
  128 KB; some formats declare larger deviations).

A `null` or absent field means the signal was **not observed within those
bounds** — not that it is absent from the file. Raising the limits (see the
configurable-depth options) may surface more, at a cost.

## It is not a parser or full-content extractor

Specialist tools extract **envelopes and structural signals** (e.g. PDF page
count, email headers, spreadsheet sheet names, document title/author) on a
best-effort basis within their budget. File Observer does not guarantee:

- complete or correct extraction of document bodies,
- recovery of malformed, encrypted, or corrupt files,
- OCR, ingestion, embeddings, or classification — these are downstream concerns,
  out of scope by design.

When a specialist cannot extract a field within bounds, the field is null and
(where relevant) a non-fatal error is recorded; the scan continues.

## Optional dependencies degrade gracefully, not silently

Core operation needs only `chardet`. `python-magic`/`libmagic` sharpens content-based
MIME detection but is **optional as of v1.3** — without it, a built-in pure-Python
content sniff covers ~20 common formats before falling back to extension inference.
Optional packages widen coverage:

- **python-magic** (`libmagic`) — content-based MIME for the full format range (pure-Python sniff covers common formats when absent)
- **PyYAML** — frontmatter parsing
- **olefile** — OLE2 specialists (`.msg`, `.doc`, `.xls`)
- **defusedxml** — hardened XML parsing (stdlib fallback is used if absent, with
  a documented risk)

When an optional dependency is missing, the related signals are reduced or
skipped — the scan still completes. The manifest's `context` records dependency
versions so that any variance is explainable.

## Determinism is scoped to the ScanContext

Identical inputs plus an identical `ScanContext` produce an identical manifest
(the `manifest_checksum` excludes only the volatile `scan_id` and
`generated_at`). Across environments, output may differ — but only in ways
explained by the `context`: dependency versions, Python version, platform, and
`logic_version`. Determinism is a contract *within* a context, not a promise
that every machine produces byte-identical results regardless of environment.

## MIME detection is a signal, not a correction

MIME type is detected by a cascade (v1.3): content via libmagic → a built-in
pure-Python magic-signature sniff (when libmagic is absent) → extension-based
inference. The `signal_provenance.trigger` records which tier produced it
(`libmagic` / `magic_signature_fallback` / `extension_fallback`). When content
and extension disagree, File Observer **reports the mismatch** as a signal
(`mime_analysis.matches_extension`) — it does not rename, re-route, or "fix" the file.

---

*If a limitation here conflicts with observed behavior, the behavior is the
bug — please report it (see [SECURITY.md](../SECURITY.md) for security-relevant
reports). For what consumers *can* rely on, see
[PUBLIC_CONTRACT.md](PUBLIC_CONTRACT.md).*
