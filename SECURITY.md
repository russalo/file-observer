# Security Policy

## Scope

File Observer is an **observation-only** tool. It reads files and emits metadata. It never:
- Executes file content
- Modifies source files
- Opens network connections
- Runs embedded scripts, macros, or code found in scanned files

File Observer does not execute file content. Its attack surface is limited to parsing. A malformed file can cause a specialist to raise an exception or return incorrect metadata. When optional native dependencies are present (e.g., libmagic; optional as of v1.3, with a pure-Python fallback), parsing of untrusted input carries residual risk from those dependencies' vulnerabilities. Keep dependencies updated and consider sandboxing when scanning untrusted files.

## Reporting Vulnerabilities

If you discover a security issue, please report it privately:

- **Email:** security@russalo.com
- **Do not** open a public GitHub issue for security vulnerabilities

We will acknowledge receipt within 48 hours and provide an initial assessment within 7 days.

## Dependency Security

| Dependency | Role | Risk mitigation |
|---|---|---|
| `python-magic` / `libmagic` | MIME detection | Read-only, no execution. Fallback chain since v1.3: pure-Python magic-signature sniff → extension-based inference if libmagic is absent. **v1.15:** excluded on Windows via a `platform_system` dependency marker — python-magic's import-time libmagic search can *hang* on a Windows box without the DLL; the pure-Python fallback runs instead (Windows users wanting libmagic-grade MIME install `python-magic-bin`). |
| `chardet` | Encoding detection | Read-only. Fallback to encoding cascade if unavailable. |
| `olefile` | OLE2 parsing (.msg/.doc/.xls) | Read-only stream access. Files opened via path (not buffer) for OLE2 FAT chain traversal. |
| `purexml` | XML parsing | v1.36+: pure-stdlib, oracle-gated-to-defusedxml XML hardener (`file-observer[security]`). Blocks entity-expansion/XXE/DTD attacks AND applies structural caps (`max_depth`/`max_attributes`/`max_bytes`) — refusing pathologically-deep/oversized XML. Falls back to stdlib `xml.etree.ElementTree` when not installed (documented risk — no hardening in fallback mode). (Replaced `defusedxml` in v1.36.) |
| `PyYAML` | Frontmatter parsing | `safe_load` only. Fallback to string splitting if unavailable. |
| `pypdf` (`[pdf]` extra, v1.8) | Object-stream PDF page_count / `/Info` | **Tier-1** decode path: calls `pypdf.PdfReader` directly — that path is not bounded by our `PDF_INFLATE_CAP`; treat as **third-party residual risk** (keep pypdf updated). **Tier-2** stdlib in-house decoder is the fallback when pypdf is absent (zlib + PNG predictor + `/W` xref + `/ObjStm`, scoped to common cases — never returns a wrong value, only null on exotic predictors) and IS bounded by `PDF_INFLATE_CAP` (64 MB output cap; v1.8.1 hardening). |
| `watchfiles` (`[watch]` extra, v1.11) | FS-event backend for `--watch` | Read-only; emits FS events for the watch driver to trigger rescans. Chosen over `watchdog` after measurement (1:1 event delivery vs watchdog's 6× amplification, 43ms latency). When absent, `--watch` prints an actionable error and exits; one-shot scans unaffected. |

## Bounded Observation

All specialist extractors operate within declared bounds:
- **Default sample:** 8KB read from file head
- **OOXML deviation:** 128KB for ZIP-based formats (DOCX, XLSX) — declared, bounded
- **OLE2 deviation:** full file via path for .msg/.doc/.xls — declared, bounded by file size on disk
- **PDF whole-file read (v1.5+):** capped at 64MB for the structural reader (`PDF_FULL_READ_CAP`); over-cap PDFs are processed via pypdf when available, or yield null page_count
- **PDF decompression (v1.8.1 hardening):** every `flate` decompression is gated by `_safe_inflate` with a strict 64MB output cap (`PDF_INFLATE_CAP`); the v1.8 stdlib decoder additionally rejects attacker-controlled `/Columns` (rows can't exceed inflated stream size) and zero-width `/W [0 0 0]` xref entries (would otherwise loop unbounded); the 32-hop `/Prev` chain shares one aggregate inflate budget
- **ZIP traversal:** path components validated against traversal attacks (`_is_safe_zip_entry`), decompressed size capped at 1MB (`_safe_zip_read`)
- **Directory walk stays in-tree (v1.8.1):** symlinks whose target resolves outside the source directory are skipped (the walk never reads `/etc/passwd` via a hostile symlink), mirroring `_is_safe_zip_entry` for filesystem paths
- **Degraded records, not crashes (v1.8.1 + v1.9.1):** a single unreadable file, a max-length filename, or a TOCTOU race between discovery and read produces a `FileRecord` + `ErrorRecord` (codes `universal_stat_failed` / `universal_read_failed`) — never an aborted scan

## Safety Flags

The scanner detects structural indicators that may represent security concerns:
- `has_javascript` — PDF contains JavaScript markers
- `has_macros` — DOCX contains VBA macro binary
- `has_ole_objects` — RTF contains embedded OLE objects
- `has_external_references` — XML contains external entity declarations

These are **observations, not assessments**. The scanner reports what it sees. Consumers apply their own threat model.

## The manifest is untrusted data

File Observer never executes or interprets file content, so the **scanner** cannot be prompt-injected — a malicious instruction inside a file is just bytes to count. But the **manifest it emits is a report *about* untrusted input, and it inherits that untrust.** Several fields echo attacker-controllable bytes verbatim, so a downstream consumer (especially an LLM agent) must treat the manifest as data, never as instructions.

Two classes of field:

- **fo-derived (trusted):** counts, MIME/types, `safety_flags`, hashes, versions, structural booleans, and fo-generated identifiers — lexicon per-category counts/densities and the content-hash `dictionary_id`. File Observer generates these; they are safe to summarize. (`safety_flags` are *routing signals, not verdicts* — an absent flag means "nothing observed," never "safe.")
- **file-derived (untrusted / attacker-controllable):** `path` / filenames, `content_preview`, the `specialist_metadata` values **copied or extracted from the input** (EXIF make/model, PDF producer/title/author, email subject/from, …), `tags`, chatlog speaker labels, `fact_block` keys/values, `reference_tokens`, frontmatter. These are quoted bytes from the input (the fo-generated values inside `specialist_metadata` — the `dictionary_id` hash, counts, flags — are fo-derived, not this). An attacker who controls a filename or a metadata field can place text there that rides back into a model through the manifest — even though the file body was never opened for meaning.

**File Observer does not sanitize these fields, by design** — rewriting a value would corrupt the faithful record, and there is no safe universal sanitizer for "text a model might act on." The correct posture is on the consumer: treat file-derived fields as untrusted data (the same way you would treat the file body), and do not template them into a prompt as trusted input. When you only need the risk signal, prefer the fo-derived fields (counts, flags) over the verbatim strings.

**Safe mode (v1.40, `--trusted-only`).** When you need a manifest safe to hand straight to a model, `--trusted-only` (CLI, `ScannerConfig(trusted_only=True)`, or the MCP `trusted_only` tool param / server flag) emits a **projection** that nulls EVERY file-derived string across the whole manifest — the per-file fields **and** the manifest-level blocks (`meta.source_dir`, the `summary` prose, the `delta` / `duplicate_clusters` path lists, `per_directory_summary` directories, and the `vectors_collected` summaries — **except the `lexicon` vector's, kept since v1.44** so a consumer can route by category; those category names are consumer config, never file bytes) — keeping only fo-derived / consumer-config signal (counts, flags, hashes, enums, the lexicon category breakdown) plus a fo-derived `path_id = sha256(<relative path>)` correlation handle and a top-level `trusted_only: true` marker. It **over-suppresses by design** (fail-safe: when a field's trust is uncertain it is dropped) and **never sanitizes**. The DEFAULT manifest is unchanged (byte-identical); safe mode is a separate, opt-in output. The `--schema` output annotates every top-level field's `trust` (`fo_derived` / `file_derived`) so a consumer can build its own projection. Note the retained lexicon fields are a **`consumer_config`** class (consumer-supplied strings, never file bytes) that lives in the `--trusted-only` projection logic — it is **not** a `--schema` `trust` value (schema annotates only top-level `FileRecord` fields, and `specialist_metadata` is `mixed`); a consumer identifies the retained lexicon fields by the documented safe-mode exception, not a schema annotation.

## MCP: never pass secrets as tool arguments

An MCP tool's arguments are **constructed by the calling LLM**, so anything passed as a tool argument is, by definition, in the agent's context. Sensitive input must therefore never be a tool parameter. File Observer supplies the consumer lexicon via **server-startup `--lexicon <path>` / `--lexicon-index <path>` flags** (v1.43 accepts JSON or an EasyList-style text list, and composes several), not a per-call argument, so the lexicon *term list* never crosses the wire — only term-free derived results do (per-category counts, densities, the category names, and the content-hash `dictionary_id`). This scopes the guarantee to the lexicon *config*: a term that happens to appear in a scanned file's own content will still surface in file-derived fields like `content_preview`, exactly as any other content would — treat those as untrusted per the section above. The same rule generalizes to any secret (API keys, credentials): verify it server-side, and let the agent see only already-scoped, secret-free results.

## Supported Versions

| Version | Supported |
|---|---|
| 1.50.x | Yes (current) |
| 1.49.x | Security fixes only |
| 1.48.x | Security fixes only |
| 1.47.x | Security fixes only |
| 1.0–1.46.x | No (schema-stable but unsupported; please upgrade) |
| < 1.0 | No |
