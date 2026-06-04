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

When a file cannot be `stat()`-ed (deleted mid-scan, a TOCTOU race, a special
file), its degraded record reports `created_at` **and** `modified_at` as `null`
— never the wall-clock scan time — so the manifest stays reproducible across runs
even on that error path (v1.8.2).

## PDF metadata is read by following the file's structural index (v1.5 + v1.7)

The PDF specialist obtains `page_count` and `/Info` (producer/title/creation_date)
by **following the file's own index** (v1.7): `startxref` → the latest trailer →
the root catalog → the page tree, parsing the classic cross-reference table for
object offsets and following `/Prev` across incremental updates. Font/image markers
(`text_detected`, `requires_vision`) still use a head + bounded-tail window (v1.5,
unchanged). It does **not** decompress content streams. Because the count comes
from the *root the trailer points at*, an incremental update that deleted pages no
longer reports the stale (larger) superseded count, and a > 64 MB PDF is resolved
by offset-seek rather than falling back to a window. `pdf.xref_type`
(`classic`/`stream`/`none`, provisional) records which form was observed. Residuals:
- **PDF 1.5+ object-stream / xref-stream** PDFs compress the cross-reference table
  and often the page tree into streams (57% of the infra corpus). **v1.8 decodes
  them** via a cascade — optional `pypdf` (tier 1) → a stdlib in-house decoder
  (tier 2: zlib + PNG predictor + `/W` xref + `/ObjStm`) → null. So `page_count`
  (and `/Info`, via pypdf) is now recovered for these PDFs **with or without** the
  optional dependency. `pdf.parser` records the tier. Residuals:
  - The stdlib fallback is **scoped to common cases** — it returns null (never a
    wrong value; validated against pypdf as an oracle) on ~12% of object-stream
    PDFs that use exotic predictors (avg/paeth/TIFF), unusual `/W`, or an **indirect
    `/Length`** (`/Length 5 0 R`, which it doesn't resolve). It also **refuses a
    decompression bomb** (a flate stream expanding past 64 MB → null, not OOM) and,
    as of v1.8.1, an attacker `/Columns` (capped to the inflated-stream size),
    zero-width `/W [0 0 0]` xref entries, and the compositional `/Prev`-chain work
    (aggregate inflate budget) — all → null, never an unbounded alloc/loop.
    Installing `file-observer[pdf]` (pypdf) recovers the scoped-out cases too.
  - **Empty-password-encrypted** object-stream PDFs stay null — the decode is gated
    on `not encrypted` (pypdf could decrypt them; a conservative scope choice).
  - PDFs **> 64 MB**: the stdlib decoder needs the whole file in memory (skips > 64
    MB); pypdf still handles them.
  - `text_detected` may still be `false` for an object-stream text PDF (the marker
    window is byte-level — unchanged from v1.7).
- A **broken/absent `startxref`** falls back to the v1.5 whole-file window scan
  (then to the head sample); a > 64 MB PDF with no followable anchor likewise.
- Encrypted PDFs: `/Info` strings are encrypted, so they're reported as null.
`requires_vision` is conservative: it flags a PDF only when text/font markers are
absent AND image markers are present.

## The scan stays within the source tree (v1.8.1)

The directory walk follows symlinks **only when the target resolves inside the
source tree**. A symlink pointing outside (e.g. `→ /etc/passwd`) is skipped — it is
not read into the manifest — mirroring the path-traversal guard on ZIP entries
(`_is_safe_zip_entry`). This also keeps the scan deterministic (an external symlink
target that mutates between runs can't change the manifest). In-tree symlinks are
followed normally. A single unreadable file (permissions, special file) or a
maximum-length filename degrades to one `FileRecord` + `ErrorRecord`
(`universal_read_failed`) rather than aborting the whole scan.

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
