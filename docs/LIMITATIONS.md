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

The declared dependencies are `python-magic` and `chardet`. `python-magic` binds the
**libmagic** system library — and *libmagic itself is optional as of v1.3*: when it's
absent (Windows, minimal containers), the built-in pure-Python content sniff covers a
range of common binary formats before falling back to extension inference. Optional
*extras* widen coverage further:

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

## PDF metadata is read from the head + a bounded tail (v1.5)

The PDF specialist reads the **whole file** (capped at 64 MB) for `page_count`
and `/Info` (producer/title), and a head+tail window for the font/image markers
(`text_detected`, `requires_vision`). It does **not** decompress streams.
`page_count` is anchored to the `/Type /Pages` page tree (so bookmark/`/Outlines`
counts aren't mistaken for pages), and `producer`/`title` honor balanced and
escaped parens. These are reliable for PDFs whose page tree / Info are
**uncompressed** (the common case). Residuals:
- **PDF 1.5+ object-stream** PDFs compress the page tree / Info / `/Font` refs
  into streams → `page_count` is **null** (an honest "not observed" — never a
  wrong value), `producer`/`title` may be null, and `text_detected` may be
  `false` even for a text PDF.
- PDFs **larger than 64 MB** fall back to the head+tail window (the root page
  tree could be in the unread middle → null).
- Encrypted PDFs: `/Info` strings are encrypted, so they're reported as null.
`requires_vision` is conservative: it flags a PDF only when text/font markers are
absent AND image markers are present. Reliable extraction for object-stream PDFs
would require a full PDF parser, deliberately out of scope (stdlib only).

## Provenance vector reports what's observable, not ground truth (v1.6)

The corpus-scoped `provenance` vector normalizes producer/creator strings into
toolchains, counts production years, and classifies digitization origin. Its
inputs are the already-extracted specialist metadata, so it inherits those
residuals and adds a few of its own:
- **Digitization inherits the PDF object-stream blind spot.** `born_digital` /
  `scanned` lean on `text_detected` / `requires_vision`; an object-stream PDF
  whose `/Font` refs are compressed can read as no-text and be classed `unknown`
  (or `scanned` if image markers are present). The OCR-producer fingerprint
  (`ocr_detected`) is the only digitization signal independent of stream
  decompression. Treat the counts as a floor, not a census.
- **`applied_to_count` = files that contributed a *toolchain*** (a non-empty
  producer/creator/application). The `digitization` and `production_years` blocks
  have their own, generally larger, populations (a PDF with no producer still
  classifies digitization). Don't divide one block by `applied_to_count`.
- **Legacy OLE2 `.doc` / `.xls` carry no `application`** — only PDF (producer/
  creator) and OOXML (`docProps/app.xml`) feed the vector (fork B scope). A
  legacy-Office-heavy corpus will under-count toolchains; OLE2/EML producing-app
  harvest is deferred to a later minor.
- **The toolchain table is a closed, versioned dictionary.** Unknown producers
  pass through with a mechanical version-suffix strip (so versions group); they
  are never dropped. Editing the table changes the vector's `rules_hash` (and
  thus its identity digest) — expansion is a deliberate, versioned change.

## MIME detection is a signal, not a correction

MIME type is detected by a cascade (v1.3): content via libmagic → a built-in
pure-Python magic-signature sniff (when libmagic is absent) → extension-based
inference. The `signal_provenance.trigger` records which tier produced it
(`libmagic` / `magic_signature_fallback` / `extension_fallback`). When content
and extension disagree, File Observer **reports the mismatch** as a signal
(`mime_analysis.matches_extension`) — it does not rename, re-route, or "fix" the file.

## Chatlog detection has known false negatives (v1.4)

`is_chatlog` is a content-based heuristic. v1.4.0 added a content-shape gate (a
turn must read like an *utterance* — function word, sentence punctuation, or
length) to stop recurring *data* labels (`Item:`/`Price:`) being mistaken for
speakers. That gate has three accepted, documented blind spots:

- **Ultra-terse contentless dialogue** — an exchange of bare one-word turns
  (`Human: hi` / `Assistant: hello` / `Human: bye`) is *irreducibly* ambiguous
  with a small key-value block; it carries no function word, punctuation, or
  length, so it is **not** flagged. Real conversations are substantive and detect
  normally; this affects only degenerate inputs.
- **All-distinct multi-party roll-call** — detection requires at least one
  recurring speaker, so a transcript where every participant speaks exactly once
  is **not** flagged. Real multi-party dialogue almost always has speakers recur.
- **`Q:`/`A:`-labeled published interviews** — these are excluded along with FAQs
  (a FAQ and an interview are structurally identical); interviews labeled with
  identities (`Interviewer:`/`Guest:`/names) are unaffected.
- **Screenplay/script-style transcripts with the speaker on its own line**
  (`Alice:` then the utterance on the *next* line) — the content-shape signal
  needs the turn's text on the same line as its label, so a label-on-own-line
  prose transcript *without* markdown section structure is not flagged. (When
  such a transcript also has markdown headers, the structure rule still catches
  it.) Same-line `Speaker: text` — the overwhelmingly common form — is unaffected.

It also has one accepted **false positive** class: a document whose recurring
capitalized labels carry sentence content but are a *taxonomy*, not speakers —
headerless release notes (`Feature:`/`Bugfix:`), meeting minutes
(`Action:`/`Decision:`), or labels sprinkled through prose (`Aside:`/`Sidebar:`).
These are structurally identical to dialogue (the irreducible `Key:value`↔dialogue
ambiguity) and may be flagged `is_chatlog=true`. Version-tagged changelogs and the
known changelog/admonition vocabularies are still rejected.

These are deliberate trade-offs to keep false positives low. As always, a null or
absent `is_chatlog` means "not detected within these rules," not "not a conversation."

---

*If a limitation here conflicts with observed behavior, the behavior is the
bug — please report it (see [SECURITY.md](../SECURITY.md) for security-relevant
reports). For what consumers *can* rely on, see
[PUBLIC_CONTRACT.md](PUBLIC_CONTRACT.md).*
