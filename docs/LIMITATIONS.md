# Limitations

File Observer is an **observation layer**. It reports what it can see, within
declared bounds, deterministically. This document states plainly what it does
**not** do, so consumers can apply their own judgment on top of its output.

## It does not make threat or content judgments

`safety_flags` (`has_javascript`, `has_macros`, `has_ole_objects`,
`has_external_references`, `extraction_permission_bypassed` — v1.12) are
**structural observations, not threat assessments**. A flag means "this structure was observed," not "this file is
dangerous." File Observer never quarantines, scores, or verdicts a file. Apply
your own threat model to the observations.

## It observes within bounds — null means "not seen here," not "not present"

Observation is bounded by design:

- Content preview is capped (default 1000 chars).
- Baseline text analysis reads a bounded window (`baseline_max_bytes`, default
  64 KB).
- Specialist extraction reads within a budget (`specialist_budget`, default
  128 KB; some formats declare larger deviations).
- **Office/ODF metadata is bounded to containers whose ZIP central directory falls within the budget (~128 KB).** The OOXML/ODF extractors (`.docx`/`.xlsx`/`.pptx`/`.odt`/`.ods`/`.odp`) read a bounded head of the ZIP; a ZIP stores its central directory at the *end* of the archive, so a file larger than the budget has its directory beyond the read window and returns `null` metadata (honest null = not observed within bounds, never a wrong value). This bound also caps the central-directory parse against a malicious huge-directory ZIP. Real presentations (image-heavy, often > 128 KB) are the common case to hit this. A bounded *tail*-read of the central directory — handling large files while still capping against a directory-bomb — is a noted future enhancement across all office formats (v1.24 surfaced it via four-reviewer convergence).

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

### Specialist maturity tiers

Not all specialists are equally reliable — some read a deterministic binary
structure, others parse a legacy container or a sample-bounded regex. This table
tiers them so consumers can weight the fields accordingly (and is the human
companion to `quality.specialist_stats`, which reports per-tool attempted/
succeeded/failed counts for the *actual* scan):

| Tier | Specialist (format → fields) | Why |
|---|---|---|
| **Mature** | `image_structure` (PNG/JP2 → width/height/bit_depth, dimensions only; JPEG/HEIC/HEIF/AVIF/TIFF → + EXIF make/model/orientation/datetime/GPS-presence); `video_structure` (MP4/MOV/M4V → codec/duration/dimensions/creation_date + QuickTime make/model/GPS-presence, v1.17–1.20); `spreadsheet_structure` (XLSX/ODS → sheet_names/header_rows/application); `document_extraction` (DOCX/ODT → title/author/word_count/heading_count/application); `presentation_structure` (PPTX/ODP → slide_count/title/author/application, v1.24); `email_envelope` (EML → headers; MSG → headers/date via MAPI) | Deterministic header / ISOBMFF box / OOXML-ZIP / ODF / stdlib reads, validated on real corpora (e.g. MSG ~99.9% on 3,220 real files; video matched `exiftool` exactly on 61/61 real `.mov`). |
| **Good (dep- or form-gated)** | `pdf_extraction` (PDF → page_count/producer); `audio_structure` (MP3 → format/bitrate/duration + ID3 tags, v1.25) | PDF: read by following the PDF's own index (v1.7) + decoding object streams (v1.8) — **mature with `pypdf`**; the stdlib fallback recovers most object-stream PDFs but nulls ~12% (exotic predictors) and `/Info` (producer/title) — never a wrong value, just null. MP3: ID3v2 tags + a bounded MPEG frame-header parse (Xing VBR or CBR estimate); a headerless `.mp3` (or one not content-typed `audio/mpeg`) stays honest-null under the tight guard. |
| **Best-effort** | `spreadsheet_structure` (XLS → sheet_names via OLE2/BIFF8); `document_extraction` (DOC → title/author/application via OLE2 SummaryInformation; RTF → title/author via `{\info}` regex on the sample); `presentation_structure` (PPT → title/author/application/slide_count via OLE2 Summary/DocumentSummaryInformation, v1.25) | Legacy binary containers / a sample-bounded regex — lower and more variable coverage than their OOXML/ODF siblings. |
| **Heuristic** | `chatlog_signals` (content-detected `is_chatlog` + turn/speaker structure) | A content heuristic with documented false-positive/negative classes (see "Chatlog detection" below), not a structural guarantee. |

Tiers describe *reliability*, not *value* — a best-effort field is still a real
observation when present, and null always means "not observed within bounds."

## Optional dependencies degrade gracefully, not silently

The declared dependencies are `python-magic` and `chardet`. `python-magic` binds the
**libmagic** system library — and *libmagic itself is optional as of v1.3*: when it's
absent (Windows, minimal containers), the built-in pure-Python content sniff covers a
range of common binary formats before falling back to extension inference.

**Windows:** `python-magic` is **not** installed on Windows (a `platform_system`
dependency marker). The wheel ships without a libmagic DLL, and python-magic's
import-time library search *hangs* on a Windows box with no libmagic — which would hang
`import file_observer.scanner` itself. So on Windows `pip install file-observer` skips
it and the pure-Python MIME fallback engages automatically (it just works). Windows
users who want libmagic-grade content MIME can install `python-magic-bin` (it bundles
the DLL). One-shot scanning is otherwise fully cross-platform.

Optional *extras* widen coverage further:

- **PyYAML** — frontmatter parsing
- **olefile** — OLE2 specialists (`.msg`, `.doc`, `.xls`, `.ppt`)
- **defusedxml** — hardened XML parsing (stdlib fallback is used if absent, with
  a documented risk)
- **pypdf** (`file-observer[pdf]`) — object-stream PDF `page_count`/`/Info`
  (tier 1; the stdlib fallback recovers most common cases when absent)
- **watchfiles** (`file-observer[watch]`) — backend for `--watch` continuous
  mode. When absent, `--watch` prints an actionable error and exits; one-shot
  scans are unaffected. **`--watch` is validated on POSIX** — its graceful
  shutdown is SIGTERM/SIGINT-based; on Windows that signal model differs, so the
  continuous mode is untested there (one-shot scanning is fully cross-platform).

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

**Parallelism does not affect output (v1.9).** `--workers N` scans files in
parallel across processes, but the manifest is **byte-identical regardless of N** —
`--workers` and `--progress` are runtime-only controls, never recorded in the
manifest, and the per-file pass is order-preserving. The cost is memory: each
worker holds the per-file footprint (a PDF may be read whole, capped 64 MB), so a
high `--workers` on a corpus of large files can use up to ~`N ×` that transient
memory. Lower `--workers` if memory-constrained; output is unchanged either way.

**`--watch` does not change output (v1.11).** `--watch` runs file-observer
continuously, rescanning on FS events and emitting each scan's delta as one
JSONL line on stdout. The contract: **each individual scan in the stream is
byte-identical to a one-shot `file-observer` invocation against the same
filesystem state.** `--watch`, `--watch-debounce-ms`, and
`--watch-include-files` are runtime-only — never recorded in the manifest. The
stream itself is non-deterministic *across runs* by design (filesystem events
are temporal), but every emitted scan is fully deterministic for its trigger
moment.

When a file cannot be `stat()`-ed (deleted mid-scan, a TOCTOU race, a special
file), its degraded record reports `created_at` as `null` and `modified_at` as
`""` (empty string, matching the `checksum_sha256: ""` on the same record) —
never the wall-clock scan time — so the manifest stays reproducible across runs
even on that error path (v1.8.2). Its `path` is the full **source-relative** path
(e.g. `sub/file.txt`), consistent with every normal record (v1.9.1; earlier it was
flattened to the bare filename on that path).

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
- **The provenance vector harvests `application` from PDF + the `document` and
  `spreadsheet` namespaces only.** PDF (producer/creator), OOXML `docProps/app.xml`,
  and — since v1.10 — legacy OLE2 `.doc`/`.xls` (`SummaryInformation` PIDSI_APPNAME)
  feed `toolchains`. The **`presentation`** namespace (`.pptx`/`.ppt`) and `.eml`
  producing-app are **extracted but not yet harvested into the vector** —
  presentation→provenance harvest is deferred (it would move the provenance
  `rules_hash` for every manifest); `.eml` is unimplemented. (A real `.doc`/`.xls`/
  `.ppt` still populates `specialist_metadata.{document,spreadsheet,presentation}.application`
  when the property is set — that's the per-file field; it just doesn't yet feed the corpus vector.)
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

### Without libmagic, some signals are reduced (v1.15)

When libmagic is absent (Windows, minimal containers), MIME comes from the
pure-Python sniff or the extension tier. Two consequences are **by design**, not
bugs — the scan still completes and never aborts (bounded observation):

- **Signatureless text files read as "degraded."** A plain `.txt`/`.md`/`.toml`
  has no magic bytes for the sniff to match, so its MIME falls to the
  extension tier, which records a `mime_type_fallback` diagnostic. The file is
  fully observed; it just counts as `degraded` rather than `clean` in the
  quality block. (v1.15 registers `.toml` as `text/plain` so it is treated as
  text, not misclassified as binary.)
- **`.eml` email extraction now works without libmagic (v1.15.2).** Earlier the MIME
  safety guard skipped the `.eml` specialist on the fallback path (extension-derived
  `message/rfc822` had no corroborating magic signature). v1.15.2 trusts the
  extension-derived MIME for the `email` namespace specifically — a text format has no
  magic signature even when genuine, and the stdlib email parser self-validates. The one
  caveat (observe-don't-interpret): a *misnamed* `.eml` (a non-email file given a `.eml`
  extension) will, on the no-libmagic path, be parsed by the email parser and yield
  whatever it finds — an honest "this is what the parser saw," not a verdict. With
  libmagic, the content check catches such files first.

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

## Chatlog session timestamps: recognized units + timezone assumptions (v1.34)

`chatlog.first_timestamp` / `last_timestamp` are the min/max of a session's turn
timestamps, normalized to canonical ISO-8601 UTC. Two accepted limits (both surface
as `null` or a shifted value, never a crash):

- **Epoch timestamps are read as SECONDS only.** A recognized numeric timestamp
  (`create_time`) is parsed as epoch *seconds* (the ChatGPT-export convention).
  A log stamping epoch *milliseconds* or *microseconds* is not recognized and its
  timestamps read as `null` — a fully-timestamped session then looks untimestamped.
  No measured chatlog schema uses ms/µs epochs; heuristic unit-guessing was declined
  as interpretation (fo observes, it doesn't guess the unit).
- **Naive (offset-less) timestamps are assumed UTC.** A turn timestamp with no
  timezone is treated as UTC (fo's capture-metadata stance). A log that mixes
  naive *local-time* turns with tz-aware turns can therefore order them wrongly
  by the local offset. All measured chatlog schemas are tz-aware or UTC-epoch, so
  this affects only a hypothetical mixed-convention log.

For very large sessions the axes use a head+tail read (v1.5 PDF precedent): turns are
chronological, so `first` is read from the file head and `last` from the tail. If a
log's timestamps are non-monotonic, an extreme sitting in the unread middle of a
>64 MiB file could be missed — real session logs are chronological, so this is not
observed in practice.

---

*If a limitation here conflicts with observed behavior, the behavior is the
bug — please report it (see [SECURITY.md](../SECURITY.md) for security-relevant
reports). For what consumers *can* rely on, see
[PUBLIC_CONTRACT.md](PUBLIC_CONTRACT.md).*
