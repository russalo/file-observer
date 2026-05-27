# File Observer

**File observation engine for document pipeline systems.**

Recursively discovers files under a source directory, extracts universal and format-aware metadata signals, and emits a deterministic JSON manifest. File Observer is an observation layer only — it never mutates source files, performs OCR, or makes classification decisions.

| | |
|---|---|
| **Package** | `file-observer` |
| **Version** | `0.11.0` |
| **Schema** | `0.11` |
| **Python** | `>= 3.12` |
| **License** | AGPL-3.0 (dual commercial available) |
| **Spec** | [`docs/v0.11.0_RFC_Specification.md`](v0.11.0_RFC_Specification.md) (current) |
| **History** | [`docs/HISTORY.md`](HISTORY.md) — every version, patch, and compliance report |
| **Repository** | `pkp.russalo.com/scanner/` |

---

## Installation

### From source (recommended)

```bash
git clone <repository-url>
cd scanner

python -m venv .venv
source .venv/bin/activate   # Linux / macOS
# .venv\Scripts\activate    # Windows

pip install -e .
```

### With optional dependencies

```bash
# PyYAML for robust frontmatter parsing
pip install -e ".[yaml]"

# olefile for .msg / .doc / .xls envelope extraction (required for OLE2 specialists)
pip install -e ".[msg]"

# defusedxml for hardened XML parsing
pip install -e ".[security]"

# Full development environment (pytest + PyYAML + olefile + defusedxml)
pip install -e ".[dev]"
```

### System requirements

Scanner uses [`python-magic`](https://pypi.org/project/python-magic/) for content-based MIME detection, which requires `libmagic`:

```bash
# Debian / Ubuntu
sudo apt install libmagic1

# macOS
brew install libmagic

# Windows (bundled alternative)
pip install python-magic-bin
```

If `libmagic`, `chardet`, `olefile`, or `defusedxml` are unavailable, File Observer degrades gracefully: extension-based MIME fallback, a fixed encoding cascade, OLE2 specialists return None, XML uses stdlib. Dependency availability is fingerprinted in the manifest's `ScanContext.dependencies` so downstream consumers can detect environment variance.

### Platform notes

- **Windows:** Use `python-magic-bin` instead of `python-magic` (bundles libmagic DLLs). The `--exclude-hidden` flag uses Unix dot-prefix convention only; Windows NTFS hidden attributes are not detected.
- **Linux:** `created_at` is always `null` (most filesystems lack `st_birthtime`).
- **macOS:** Full feature support.

---

## Quick Start

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig, manifest_to_json

scanner = Scanner(source_dir=Path("./documents"))
manifest = scanner.scan()

print(f"Scanned {manifest.stats.total_files} files")
print(f"  Supported: {manifest.stats.supported_files}")
print(f"  Requires vision: {manifest.stats.requires_vision}")
print(f"  Clean: {manifest.quality.clean_files}")
print(f"  Chatlog-flagged: {manifest.quality.chatlog_files}")
print(manifest_to_json(manifest))
```

### CLI

```bash
# Scan current directory (fo is a shorthand alias)
file-observer
fo

# Scan with a named profile and JSONL output
fo ./project --profile deep_extract --format jsonl

# Scan with ignore rules and delta comparison
fo ./project --ignore-file .scannerignore --previous-manifest ./last.json

# Scan with specialists enabled and a signed manifest
fo /path/to/files -o ./output --specialists --signing-key-file ./secret.key --format json
```

---

## Key Features

### Observation and determinism

- **Capability-locked determinism** — identical inputs + identical `ScanContext` always produce identical manifests. Cross-environment variance is explained by dependency versions and logic version.
- **Signal provenance** — every derived field includes a structured `signal_provenance` entry tracing exactly how and why it was computed (layer, method, trigger, inputs, detail).
- **Signal layering** — every field is classified as raw (direct observation), derived (computed from raw), or semantic-local (reserved, opt-in).
- **Bounded observation** — specialist extractors operate within a bounded sample buffer by default (8KB); OOXML and OLE2 specialists declare documented deviations (read full file via path when required by the format).
- **ScanContext** — environment fingerprint: logic version, scanner version, Python version, platform, dependency versions and availability flags.

### Capability tiers

- **Universal** — every file: identity, filesystem metadata, checksum, path-derived fields, MIME analysis, structural file signatures, polyglot detection, routing flags.
- **Baseline** — text-decodeable files: encoding detection, content preview, tag extraction, frontmatter parsing, asset matching, chatlog content-based detection.
- **Structural** — text-decodeable files: title, headings, CSV headers, JSON/YAML/XML/TOML document keys, technology hints, filename dates.
- **Specialist** — format-specific extraction (opt-in via `enable_specialists=True`): PDF, PNG, JPEG, MSG, EML, XLSX, XLS, DOCX, DOC, RTF, and the content-detected chatlog specialist.

### Configurable extraction depth (v0.6)

- **`specialist_budget`** — bytes an OOXML specialist may read beyond the 8KB sample (default 128KB). Replaces the hardcoded v0.5 deviation.
- **`extension_overrides`** — per-extension overrides for `baseline_max_bytes`, `specialist_budget`, `preview_max_chars`. Apply on top of the base config via `effective_for(extension)`.
- **Named profiles** — `fast_sort` (8KB baseline, specialists off), `general` (64KB baseline, specialists off), `deep_extract` (1MB baseline, 512KB specialist, specialists on). Profiles are sugar — they set named config fields.

### Structural signatures and polyglot detection (v0.6)

- **`file_signature`** — first 16 bytes of the file as lowercase hex.
- **`format_signatures`** — list of recognized magic signatures found in the sample, sorted by offset. Current table: PNG, JPEG, PDF, ZIP, OLE2, RTF, GIF (87a / 89a), RIFF, HTML doctype, XML declaration.
- **`is_polyglot`** — `true` when multiple distinct format signatures match the same sample.

### Integrity envelope (v0.6)

- **`manifest_checksum`** — SHA-256 of the canonical manifest content (checksum field set to empty during computation).
- **`previous_manifest_checksum`** — embedded in the delta record when a previous manifest is supplied, creating a verifiable chain of custody across incremental scans.
- **`manifest_signature`** — optional HMAC-SHA256 signature over the manifest checksum using a configured `signing_key`. The key itself is never serialized to the manifest; `signing_key_id` (if set) appears in `meta.config` for key identification.

### Specialist MIME guard (v0.6)

Each specialist namespace declares the set of MIME types it accepts (e.g. `pdf` accepts `application/pdf` only). When the content MIME does not match the expected format, the specialist is skipped with a diagnostic error record. The guard also cross-checks against detected structural signatures when the MIME came from extension-based fallback, preventing a spoofed extension from forcing a wrong-format extraction.

### Safety flags (v0.7)

Per-file `safety_flags` list drawn from the sample buffer or (for DOCX macro detection) the ZIP central directory:

- **`has_javascript`** — PDF `/JavaScript` or `/JS` key in sample
- **`has_macros`** — DOCX ZIP contains a `vbaProject.bin` entry (requires `enable_specialists`)
- **`has_ole_objects`** — RTF `\object` directive in sample
- **`has_external_references`** — XML with an `<!ENTITY SYSTEM` declaration in sample

### Scan quality block (v0.7 / v0.8)

Manifest-level `ScanQuality` block aggregating per-file signals for rapid triage:

- `total_files`, `clean_files`, `degraded_files`, `error_files`
- `mime_mismatches` — per-file `mime_analysis.matches_extension == false` count
- `polyglots_detected` — per-file `is_polyglot == true` count
- `specialist_failures` — per-file error records with code `specialist_probe_failed`
- `unsupported_extensions` — per-file error records with code `unsupported_extension`
- `safety_flags` — per-file any-safety-flag count
- `chatlog_files` — per-file `is_chatlog == true` count (v0.8)

### Chatlog specialist (v0.8, content-detected)

The first **content-detected** (not extension-driven) specialist. For `.txt` / `.md` / `.mdx` files, activation is gated by three content rules:

1. 3+ lines matching the speaker label pattern `^([A-Z][a-zA-Z0-9_]{0,15}):\s`
2. 3+ `### ` headers (line-anchored)
3. 3+ `---` section dividers

Any one rule triggers `is_chatlog = true`, `specialist_tool = "chatlog_signals"`, and `requires_specialist_tool = true`. When `enable_specialists=True` and the MIME guard accepts the content type (`text/plain`, `text/markdown`, `text/x-markdown`), the extractor produces 11 drift-visible fields: turn_count, speaker_labels (sorted, ≥3-frequency filter), section_marker_count and section_marker_styles, avg/max/min turn character stats, reference_tokens (at_mentions, wiki_links, code_fence_blocks, url_count), top_capitalized_tokens (top 20 by frequency with alphabetical tiebreak), capitalized_token_count, and vocabulary_size_estimate.

Detection runs even with specialists disabled — the regex pass is cheap. v0.9.1 tuned the H3 threshold from 3 to 5 and added a speaker label stop-list to reduce documentation false positives. v0.10.1 extended chatlog detection to `.jsonl` files with JSON-aware role detection (`"type": "user"/"assistant"`).

### Vector abstraction (v0.9)

The scanner becomes a **corpus observer**. A vector is a named, uniquely-identified unit of observation with a cryptographic identity digest (SHA-256). Two scans with the same vector identity digest on the same input produce identical output.

New top-level manifest block `vectors_collected[]` carries vector identity, identity digest, and corpus-level summary for every vector that ran. Four vectors ship in v0.10:

| Vector | Scope | What it observes |
|---|---|---|
| `chatlog` | file | Conversation patterns in .txt/.md/.mdx/.jsonl — turns, speakers, section markers |
| `reference_tokens` | file | 7 subcategories: @mentions, wiki links, code fences, URLs, emails, paths, numeric IDs |
| `author_aggregate` | corpus | Cross-specialist author normalization + template-default candidate detection |
| `filename_patterns` | file | 6 boolean subcategories: date prefix, version marker, numbered revision, template name, UUID, copy suffix |

Per-file `reference_tokens` and `filename_patterns` fields added to `FileRecord`. Per-directory aggregation in `quality.per_directory_summary[]`.

### Human-readable scan summary (v0.10)

Every manifest includes a `summary` field — a deterministic Markdown paragraph answering "what did you scan and what did you find?" without requiring JSON literacy. Includes file counts, quality assessment, vector results, and top directories.

### Other observations

- **JSONL output** — streaming-friendly NDJSON format with header line + one record per file.
- **Delta scanning** — compare against a previous manifest to identify added / modified / unchanged / removed files, plus `rescan_candidates` for files with prior specialist failures.
- **Ignore rules** — `.scannerignore` file support for excluding vendor directories, build artifacts, and user-defined patterns.
- **MIME mismatch signaling** — per-file `mime_analysis` exposing content-detected vs extension-expected MIME and match status.
- **Technology detection** — ~18 patterns covering Tailwind, Bootstrap, React, Vue, Alpine, HTMX, jQuery, Svelte, Angular, Chart.js, D3, Mermaid, Docker Compose, Terraform, Ansible, GitHub Actions, and Google Fonts.
- **Sidecar detection** — checks for companion `.json` and `.md` metadata files.
- **Non-fatal error model** — a single unreadable file never halts the scan; structured `ErrorRecord` objects captured per file per stage.
- **UTF-16/UTF-32 BOM handling (v0.7.1)** — binary detection short-circuits on a leading Unicode BOM so that UTF-16 text files (which contain interleaved NULs by construction) correctly route to the baseline tier.

---

## Architecture

```
Scanner.scan()
  |
  +-- _build_context()      Environment fingerprint (versions, dependencies)
  |
  +-- iter_files()          Sorted recursive walk, ignore rules, hidden-file exclusion
  |
  +-- scan_file()           Per-file processing through capability tiers:
  |    |
  |    +-- Universal        Identity, filesystem, checksum, routing flags, MIME, signatures
  |    +-- MIME Analysis    Content vs extension MIME comparison (every file)
  |    +-- Baseline         Encoding, preview, tags, frontmatter, assets, is_chatlog
  |    +-- Structural       Title, headings, CSV headers, doc keys, tech hints (text files)
  |    +-- Specialist       Format-specific bounded metadata extraction (opt-in)
  |    +-- Provenance       Per-field derivation map (layer, method, trigger)
  |
  +-- _compute_quality()    Aggregate per-file signals into the ScanQuality block
  +-- _compute_routing_summary()
  +-- _compute_delta()      vs previous manifest, if supplied
  +-- Manifest assembly     schema_version, context, meta, stats, quality, routing, delta,
                            checksum, signature (optional), files[]
```

### Capability Tiers

| Tier | Runs for | Gated by |
|---|---|---|
| **Universal** | Every discovered file | Always |
| **Baseline** | Non-binary files | `is_binary == False` |
| **Structural** | Non-binary files (best-effort) | `is_binary == False` |
| **Specialist** | Registered extensions OR content-detected chatlog | `ScannerConfig.enable_specialists` |

### Supported File Types

Extension-keyed specialists:

| Extension | Baseline | Structural Signals | Specialist Tool |
|---|---|---|---|
| `.txt` | encoding, preview, tags, chatlog detection | technology_hints, filename_date | `chatlog_signals` (content-detected) |
| `.md` / `.mdx` | encoding, preview, tags, frontmatter, assets, chatlog detection | title, heading_structure, technology_hints, filename_date | `chatlog_signals` (content-detected) |
| `.csv` | encoding, preview, tags | csv_headers, filename_date | — |
| `.json` | encoding, preview, tags | document_keys, filename_date | validation probe (opt-in) |
| `.yaml` / `.yml` | encoding, preview, tags | document_keys, technology_hints, filename_date | — |
| `.html` / `.htm` | encoding, preview, tags | title, technology_hints, filename_date | — |
| `.xml` / `.vx` | encoding, preview, tags | document_keys (root + children), filename_date | — |
| `.toml` | encoding, preview, tags | document_keys (top-level), filename_date | — |
| `.css` | encoding, preview, tags | technology_hints, filename_date | — |
| `.pdf` | — | filename_date | `pdf_extraction` (page count, text streams, doc info, encrypted, pdf_version, sample_text_marker_density) |
| `.png` | — | filename_date | `image_structure` (width, height, bit_depth) |
| `.jpg` / `.jpeg` | — | filename_date | `image_structure` (width, height) |
| `.msg` | — | filename_date | `email_envelope` (subject, from, to, date, message_id, has_attachments) |
| `.eml` | — | filename_date | `email_envelope` (subject, from, to, date, message_id, has_attachments) |
| `.xlsx` | — | filename_date | `spreadsheet_structure` (sheet_names, header_rows, format=ooxml) |
| `.xls` | — | filename_date | `spreadsheet_structure` (sheet_names, format=biff) |
| `.docx` | — | filename_date | `document_extraction` (title, author, word_count, heading_count) |
| `.doc` | — | filename_date | `document_extraction` (title, author) |
| `.rtf` | — | filename_date | `document_extraction` (title, author) |
| `.jsonl` | encoding, preview, tags, chatlog detection, reference_tokens | document_keys, filename_date | `chatlog_signals` (JSONL role detection, v0.10.1) |

Content-detected specialist (activates when content patterns match):

| Trigger | Extensions | Tool | Namespace |
|---|---|---|---|
| 3+ speaker labels (excluding stop-list), 5+ `### ` headers, or 3+ `---` dividers | `.txt`, `.md`, `.mdx` | `chatlog_signals` | `chatlog` |
| 3+ JSON lines with `"type": "user"/"assistant"` | `.jsonl` | `chatlog_signals` | `chatlog` |

Unsupported extensions still receive universal-tier processing and are marked with an `unsupported_extension` error record.

---

## CLI Reference

```
usage: scanner [-h] [-o OUTPUT] [--specialists] [--exclude-hidden]
               [--preview-max PREVIEW_MAX] [--baseline-max-bytes BYTES]
               [--specialist-budget BYTES] [--extension-override EXT:KEY=VALUE]
               [--profile {fast_sort,general,deep_extract}]
               [--format {json,jsonl}] [--ignore-file IGNORE_FILE]
               [--previous-manifest PREVIOUS_MANIFEST]
               [--signing-key-file PATH] [--signing-key-id ID]
               [source]
```

| Argument | Description | Default |
|---|---|---|
| `source` | Source directory to scan | `.` (cwd) |
| `-o`, `--output` | Output directory for the manifest file | `<package>/manifests/` |
| `--specialists` | Enable specialist tier probes and metadata extraction | Disabled |
| `--exclude-hidden` | Skip files and directories starting with `.` | Disabled |
| `--preview-max` | Maximum characters for content preview | `1000` |
| `--baseline-max-bytes` | Maximum bytes to decode for baseline text extraction | `65536` |
| `--specialist-budget` | Maximum bytes an OOXML specialist may read | `131072` (128 KB) |
| `--extension-override` | Per-extension override, e.g. `.pdf:specialist_budget=524288` (repeatable) | None |
| `--profile` | Named scan profile (`fast_sort`, `general`, `deep_extract`) | None |
| `--format` | Output format: `json` or `jsonl` | `json` |
| `--ignore-file` | Path to ignore file (glob patterns, one per line) | `.scannerignore` in source dir |
| `--previous-manifest` | Path to previous manifest for delta comparison | None |
| `--signing-key-file` | Path to a file containing the HMAC-SHA256 signing key | None |
| `--signing-key-id` | Identifier for the signing key (appears in `meta.config`) | None |

### Examples

```bash
# Basic scan
fo ./project

# Deep scan with specialists and JSONL output
fo ./project --profile deep_extract --format jsonl

# Delta scan against a previous manifest, signed
fo ./project \
  --previous-manifest ./manifests/last.json \
  --signing-key-file ./secret.key \
  --signing-key-id key-2026

# Per-extension override: give PDFs a larger specialist budget
fo ./docs --specialists --extension-override .pdf:specialist_budget=524288

# Run directly without installing
python src/scanner/scanner.py ./project -o ./output
```

---

## API Reference

### `ScannerConfig`

```python
@dataclass
class ScannerConfig:
    preview_max_chars: int = 1000
    sample_size: int = 8192
    baseline_max_bytes: int = 65536
    specialist_budget: int = 131072
    enable_specialists: bool = False
    exclude_hidden: bool = False
    format: str = "json"
    ignore_file: str | None = None
    previous_manifest: str | None = None
    extension_overrides: dict[str, dict[str, int]] = field(default_factory=dict)
    signing_key: bytes | None = None
    signing_key_id: str | None = None
```

Configuration dataclass for tuning scanner behavior.

| Field | Type | Default | Description |
|---|---|---|---|
| `preview_max_chars` | `int` | `1000` | Maximum characters retained in `content_preview`. |
| `sample_size` | `int` | `8192` | Bytes read for binary detection and encoding inference. |
| `baseline_max_bytes` | `int` | `65536` | Maximum bytes decoded for baseline text extraction and chatlog detection. |
| `specialist_budget` | `int` | `131072` | Maximum bytes an OOXML specialist (XLSX/DOCX) may read beyond the sample. |
| `enable_specialists` | `bool` | `False` | When `True`, runs format-specific probes and extractors. |
| `exclude_hidden` | `bool` | `False` | When `True`, skips files and directories whose names begin with `.`. |
| `format` | `str` | `"json"` | Output format: `"json"` (standard manifest) or `"jsonl"` (NDJSON, one record per line). |
| `ignore_file` | `str \| None` | `None` | Path to an ignore file. When `None`, checks for `.scannerignore` in the source directory. |
| `previous_manifest` | `str \| None` | `None` | Path to a previous manifest JSON file for delta comparison. |
| `extension_overrides` | `dict` | `{}` | Per-extension overrides for `baseline_max_bytes`, `specialist_budget`, `preview_max_chars`. Applied via `effective_for(extension)`. |
| `signing_key` | `bytes \| None` | `None` | HMAC-SHA256 signing key. Never serialized to the manifest. |
| `signing_key_id` | `str \| None` | `None` | Identifier for the signing key. Appears in `meta.config` when set. |

#### `ScannerConfig.effective_for`

```python
def effective_for(self, extension: str) -> dict[str, int]
```

Returns the resolved `baseline_max_bytes`, `specialist_budget`, and `preview_max_chars` for a given extension, with `extension_overrides` applied on top of the base config.

---

### `Scanner`

```python
class Scanner:
    def __init__(self, source_dir: Path, config: ScannerConfig | None = None) -> None
```

Core scanner class. Instantiate with a source directory and optional configuration.

| Parameter | Type | Description |
|---|---|---|
| `source_dir` | `pathlib.Path` | Root directory to scan. Resolved to an absolute path on init. |
| `config` | `ScannerConfig \| None` | Scanner configuration. Uses defaults when `None`. |

**Raises:** No exceptions on construction. `libmagic` unavailability is handled gracefully.

#### `Scanner.scan`

```python
def scan(self) -> ScanManifest
```

Execute a full recursive scan and return a manifest.

| Returns | Type | Description |
|---|---|---|
| manifest | `ScanManifest` | Complete scan result with `schema_version`, `context`, `meta`, `stats`, `quality`, `routing_summary`, `delta`, `manifest_checksum`, `manifest_signature`, and `files` list. |

**Behavior:**
- Iterates all files under `source_dir` in sorted order.
- Calls `scan_file()` for each discovered file.
- A single file failure never halts the scan; errors are captured in the file's `errors` array.

#### `Scanner.scan_file`

```python
def scan_file(self, path: Path) -> FileRecord
```

Process a single file through all applicable capability tiers.

| Parameter | Type | Description |
|---|---|---|
| `path` | `pathlib.Path` | Absolute path to the file to scan. |

| Returns | Type | Description |
|---|---|---|
| record | `FileRecord` | Complete metadata record for the file. |

**Behavior:**
1. **Universal tier** — always runs: stat, checksum, MIME, signatures, polyglot, routing flags.
2. **Baseline tier** — runs for non-binary files: encoding, preview, tags, frontmatter, assets, chatlog detection.
3. **Structural tier** — runs for non-binary files: title, headings, CSV headers, document keys, technology hints.
4. **Specialist tier** — runs when `config.enable_specialists` is `True`. Extension-based dispatch for registered formats, plus content-based chatlog dispatch when `is_chatlog` fires.

If `path.stat()` or `path.relative_to()` raises an exception, a minimal error record is returned rather than propagating the exception.

#### `Scanner.iter_files`

```python
def iter_files(self, root: Path) -> Iterable[Path]
```

Yield all regular files under `root` in sorted order.

| Parameter | Type | Description |
|---|---|---|
| `root` | `pathlib.Path` | Directory to walk recursively. |

**Behavior:** When `config.exclude_hidden` is `True`, skips any file whose relative path contains a component starting with `.`.

---

### Data Classes

#### `ScanManifest`

```python
@dataclass
class ScanManifest:
    schema_version: str                     # "0.10"
    context: ScanContext                    # Environment fingerprint
    meta: ScanMeta                          # Scan ID, timestamp, source dir, config snapshot
    stats: ScanStats                        # File count summaries
    quality: ScanQuality                    # Aggregate quality signals
    routing_summary: RoutingSummary         # Aggregate routing category counts
    delta: DeltaRecord | None               # Delta vs previous manifest, or None
    manifest_checksum: str                  # SHA-256 of canonical manifest content
    manifest_signature: dict[str, str] | None   # HMAC signature envelope when signed
    files: list[FileRecord]                 # One record per discovered file
    vectors_collected: list[dict]           # v0.9: one entry per vector that ran
    summary: str                            # v0.10: human-readable scan summary
```

Top-level output container. Serializable via `manifest_to_json()` or `manifest_to_jsonl()`.

#### `ScanContext`

```python
@dataclass
class ScanContext:
    logic_version: str
    scanner_version: str
    python_version: str
    platform: str
    dependencies: dict[str, dict[str, Any]]
```

Environment fingerprint. Deliberately excludes hostname and wall-clock timestamps (not causally linked to scan outputs). Dependency block reports `available: bool` and `version: str | None` for each optional dependency (`chardet`, `magic`, `yaml`, `olefile`, `defusedxml`).

#### `ScanMeta`

```python
@dataclass
class ScanMeta:
    scan_id: str            # UUID4, unique per scan execution
    generated_at: str       # ISO-8601 UTC timestamp
    source_dir: str         # Absolute path to scanned directory
    config: dict[str, Any]  # Runtime ScannerConfig snapshot (signing_key excluded)
```

#### `ScanStats`

```python
@dataclass
class ScanStats:
    total_files: int
    supported_files: int
    unsupported_files: int
    text_files: int
    binary_files: int
    requires_vision: int
    requires_specialist_tool: int
```

#### `ScanQuality`

```python
@dataclass
class ScanQuality:
    total_files: int
    clean_files: int
    degraded_files: int
    error_files: int
    mime_mismatches: int
    polyglots_detected: int
    specialist_failures: int
    unsupported_extensions: int
    safety_flags: int
    chatlog_files: int                      # v0.8
    per_directory_summary: list[dict]       # v0.9: per top-level subdirectory counts
```

Manifest-level rollup of per-file quality signals. Useful for triage dashboards and scan-health checks without walking `files[]`.

#### `RoutingSummary`

```python
@dataclass
class RoutingSummary:
    baseline_ready: int             # Text files not needing specialist tools
    binary_only: int                # Binary files not needing vision or specialist
    requires_vision: int
    requires_specialist_tool: int
```

#### `DeltaRecord`

```python
@dataclass
class DeltaRecord:
    previous_scan_id: str                   # scan_id from the previous manifest
    previous_manifest_checksum: str | None  # checksum of the previous manifest (chain of custody)
    added: list[str]                        # Paths present now but not before
    modified: list[str]                     # Paths present in both with different checksums
    unchanged: list[str]                    # Paths present in both with matching checksums
    removed: list[str]                      # Paths present before but not now
    rescan_candidates: list[str]            # Paths with prior specialist_probe_failed errors
```

All lists are sorted. `None` when no previous manifest was provided.

#### `FileRecord`

```python
@dataclass
class FileRecord:
    path: str                           # Relative path from source root (forward slashes)
    filename: str                       # Base filename with extension
    extension: str                      # Lowercase extension including dot, or ""
    mime_type: str                      # MIME type (content-based or extension-inferred)
    size_bytes: int                     # File size from stat
    created_at: str | None              # ISO-8601 UTC birth time, or None (Linux)
    modified_at: str                    # ISO-8601 UTC modification time
    checksum_sha256: str                # Hex-encoded SHA-256 of file content
    stage_folder: str                   # First path component, or "" if at root
    directory_depth: int                # Nesting depth (0 = root level)
    encoding: str | None                # Detected encoding, "unknown", or None (binary)
    is_binary: bool                     # True if file is binary
    requires_vision: bool               # True if image-based interpretation needed
    requires_specialist_tool: bool      # True if format-specific parser needed
    specialist_tool: str | None         # Tool name or None
    sidecar_exists: bool                # True if companion .json/.md found
    frontmatter: FrontmatterRecord      # Markdown frontmatter extraction
    tags: list[str]                     # Deduplicated, sorted tags
    asset_matches: list[str]            # Local asset references from markdown
    content_preview: str | None         # First N chars of text, or None (binary)
    structural: StructuralRecord        # Structural signal extraction
    mime_analysis: MimeAnalysisRecord   # Content vs extension MIME comparison
    specialist_metadata: dict | None    # Namespaced specialist metadata, or None
    file_signature: dict | None         # First 16 bytes hex + length
    format_signatures: list[dict]       # All detected format signatures
    is_polyglot: bool                   # True when multiple distinct formats detected
    is_chatlog: bool                    # v0.8: content-detected chatlog flag
    reference_tokens: dict | None       # v0.9: seven subcategory counts (null on binary)
    filename_patterns: dict | None      # v0.10: six boolean subcategories (every file)
    safety_flags: list[str]             # has_javascript / has_macros / has_ole_objects / has_external_references
    signal_provenance: dict             # Per-field derivation map
    errors: list[ErrorRecord]           # Non-fatal errors from any tier
```

**Null semantics:**
- `created_at`: `None` when the platform does not expose `st_birthtime` (most Linux filesystems).
- `encoding`: `None` for binary files; a detected encoding string or `"unknown"` for text files.
- `specialist_tool`: `None` when no specialist applies; a tool name string when `requires_specialist_tool` is `True`.
- `content_preview`: `None` for binary files; a string (possibly empty) for text files.
- `specialist_metadata`: `None` when specialists are disabled, the file type has no metadata extractor, or extraction returned null. A namespaced dict (e.g. `{"pdf": {...}}`, `{"email": {...}}`, `{"chatlog": {...}}`) when populated.
- `file_signature`: `None` for zero-byte files; otherwise `{"magic_bytes": "<hex>", "magic_length": n}`.

**Invariants:**
- `requires_specialist_tool == True` implies `specialist_tool is not None` (and vice versa).
- `is_binary == True` implies `encoding is None` and `content_preview is None`.
- Arrays (`tags`, `asset_matches`, `errors`, `format_signatures`, `safety_flags`) are always present, never `None`.
- `mime_analysis`, `structural`, `frontmatter`, `signal_provenance` are always present, never `None`.
- `is_chatlog == True` implies the file's extension is in `.txt` / `.md` / `.mdx` / `.jsonl` AND the file is non-binary AND content detection fired.

#### `StructuralRecord`

```python
@dataclass
class StructuralRecord:
    title: str | None                  # H1 (markdown) or <title> (HTML)
    heading_structure: list[str]       # Ordered H2 headings (markdown only)
    csv_headers: list[str]             # First-row headers (CSV only)
    document_keys: list[str]           # Top-level keys (JSON/YAML/XML/TOML)
    technology_hints: list[str]        # Detected frameworks/tools
    filename_date: str | None          # YYYY-MM-DD extracted from filename
```

#### `FrontmatterRecord`

```python
@dataclass
class FrontmatterRecord:
    exists: bool = False               # True if valid --- fences found
    keys: list[str] = []               # Sorted top-level YAML keys
    raw: str | None = None             # Raw frontmatter text (preserved for malformed)
```

#### `MimeAnalysisRecord`

```python
@dataclass
class MimeAnalysisRecord:
    detected_mime: str | None   # MIME from content-based detection (or extension fallback)
    extension_mime: str | None  # MIME inferred from extension alone, or None if unknown
    matches_extension: bool     # True when detected matches extension (or extension is unknown)
```

Surfaces mismatch signals for spoofed, mislabeled, or unexpected file content without blocking scanning.

#### `ErrorRecord`

```python
@dataclass
class ErrorRecord:
    code: str       # Machine-readable error code (see Error Codes below)
    message: str    # Human-readable description
    stage: str      # "universal" | "baseline" | "structural" | "specialist"
```

---

### Functions

#### `manifest_to_json`

```python
def manifest_to_json(manifest: ScanManifest) -> str
```

Serialize a `ScanManifest` to a pretty-printed JSON string.

#### `manifest_to_jsonl`

```python
def manifest_to_jsonl(manifest: ScanManifest) -> str
```

Serialize a `ScanManifest` to NDJSON/JSONL format. First line is a header containing `schema_version`, `context`, `meta`, `stats`, `quality`, `routing_summary`, `delta`, `manifest_checksum`, and `manifest_signature`. Each subsequent line is one `FileRecord`.

#### `compute_manifest_checksum`

```python
def compute_manifest_checksum(manifest: ScanManifest) -> str
```

Compute the SHA-256 checksum of a manifest's canonical JSON representation. The checksum is computed with the `manifest_checksum` field set to an empty string and the `manifest_signature` field set to `None`, so that the checksum covers every other field exactly. Useful for verifying manifest integrity.

---

### Error Codes

| Constant | Value | Stage | Meaning |
|---|---|---|---|
| `ERR_UNIVERSAL_STAT_FAILED` | `"universal_stat_failed"` | universal | `path.stat()` or `path.relative_to()` raised an exception (permission denied, broken path). |
| `ERR_UNSUPPORTED_EXTENSION` | `"unsupported_extension"` | universal | File extension is not in `SUPPORTED_EXTENSIONS`. |
| `ERR_MIME_TYPE_FALLBACK` | `"mime_type_fallback"` | universal | Content-based MIME detection failed or unavailable; extension-based inference was used. |
| `ERR_BASELINE_DECODE_FAILED` | `"baseline_decode_failed"` | baseline | Text decoding or baseline extraction raised an exception. |
| `ERR_SPECIALIST_PROBE_FAILED` | `"specialist_probe_failed"` | specialist | Specialist tier probe returned null, raised an exception, or was skipped by the MIME guard. |
| `ERR_JSON_PARSE_FAILED` | `"json_parse_failed"` | specialist | JSON file failed `json.loads()` validation. |
| `ERR_XML_PARSE_FAILED` | `"xml_parse_failed"` | structural | XML parser raised on a non-truncated file. |
| `ERR_TOML_PARSE_FAILED` | `"toml_parse_failed"` | structural | TOML parser raised on a non-truncated file. |

---

### Detection Methods

These methods are available on the `Scanner` instance for direct use in advanced workflows. All detection methods that contribute to derived fields return a `(value, ProvenanceEntry)` tuple so the caller can record exactly which rule fired.

#### `Scanner.detect_binary`

```python
def detect_binary(self, sample: bytes, mime_type: str) -> tuple[bool, ProvenanceEntry]
```

Determine if a file is binary based on its content sample and MIME type.

**Detection chain** (first match wins):
1. Unicode BOM at offset 0 (UTF-16 LE/BE, UTF-32 LE/BE) → **text** (v0.7.1 short-circuit; UTF-16 ASCII contains interleaved NULs by construction and would otherwise trigger the NUL-byte heuristic below).
2. NUL byte (`\x00`) in sample → binary.
3. MIME prefix is `image/`, `audio/`, or `video/` → binary.
4. MIME is in the known binary MIME set (PDF, ZIP, Office formats, OLE2, etc.) → binary.
5. MIME starts with `application/` and is not in the text-application set, and the sample fails the text-ratio check → binary.
6. Sample fails the text-ratio check (< 85% printable characters) → binary.
7. Otherwise → text.

#### `Scanner.detect_requires_vision`

```python
def detect_requires_vision(
    self, sample: bytes, mime_type: str, extension: str, is_binary: bool
) -> tuple[bool, ProvenanceEntry]
```

Determine if a file requires image-based interpretation.

Returns `True` for:
- Any `image/*` MIME type.
- `.pdf` files that are binary and lack text stream markers (`/Text`, `BT\n`, `BT\r`, `/Font`).

#### `Scanner.detect_mime`

```python
def detect_mime(self, path: Path, errors: list[ErrorRecord]) -> tuple[str, ProvenanceEntry]
```

Detect MIME type with content-based primary and extension-based fallback. Appends a diagnostic `ErrorRecord` to `errors` when falling back.

#### `Scanner.decode_text`

```python
def decode_text(
    self, sample: bytes, path: Path, max_read: int | None = None
) -> tuple[str, str, ProvenanceEntry]
```

Detect encoding and decode file content up to `max_read` bytes (default `baseline_max_bytes`).

**Cascade:**
1. `chardet` on sample (confidence >= 0.5), if available.
2. `utf-8` → `utf-8-sig` → `cp1252` → `latin-1` strict decoding.
3. `utf-8` with `errors="replace"` (returns encoding `"unknown"`).

#### `Scanner._detect_chatlog_pattern`

```python
def _detect_chatlog_pattern(self, text: str) -> bool
```

Content-based detection returning `True` if the text matches any of the three chatlog activation rules (see spec §2.3). Internal method; exposed for advanced workflows and regression testing.

---

## Usage Examples

### Programmatic scan with a named profile

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig, SCAN_PROFILES, manifest_to_json

config = ScannerConfig(**SCAN_PROFILES["deep_extract"])
scanner = Scanner(source_dir=Path("/data/inbox"), config=config)
manifest = scanner.scan()

print(f"schema: {manifest.schema_version}")
print(f"clean: {manifest.quality.clean_files} / {manifest.quality.total_files}")
print(f"safety flags: {manifest.quality.safety_flags}")
print(f"chatlog files: {manifest.quality.chatlog_files}")
```

### Find the chatlog files in a vault

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig

config = ScannerConfig(enable_specialists=True)
manifest = Scanner(source_dir=Path("./vault"), config=config).scan()

for f in manifest.files:
    if f.is_chatlog and f.specialist_metadata:
        chat = f.specialist_metadata["chatlog"]
        print(f"{f.path}")
        print(f"  speakers: {chat['speaker_labels']}")
        print(f"  turns: {chat['turn_count']}")
        print(f"  top tokens: {chat['top_capitalized_tokens'][:5]}")
```

### Triage a scan via the quality block

```python
from pathlib import Path
from scanner import Scanner

manifest = Scanner(source_dir=Path("./data")).scan()
q = manifest.quality

if q.safety_flags:
    print(f"⚠ {q.safety_flags} files carry safety flags — investigate before ingest")
if q.polyglots_detected:
    print(f"⚠ {q.polyglots_detected} polyglot files — potential format confusion")
if q.mime_mismatches:
    print(f"ℹ {q.mime_mismatches} files have MIME/extension mismatches")
if q.specialist_failures:
    print(f"ℹ {q.specialist_failures} specialist failures — check rescan_candidates")

print(f"overall: {q.clean_files}/{q.total_files} clean, {q.error_files} errored")
```

### Routing files by specialist tool

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig

config = ScannerConfig(enable_specialists=True)
manifest = Scanner(source_dir=Path("./uploads"), config=config).scan()

from collections import Counter
tool_counts = Counter(
    f.specialist_tool for f in manifest.files if f.requires_specialist_tool
)
for tool, count in tool_counts.most_common():
    print(f"  {tool}: {count}")
```

### Find files with safety flags

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig

config = ScannerConfig(enable_specialists=True)
manifest = Scanner(source_dir=Path("./incoming"), config=config).scan()

for f in manifest.files:
    if f.safety_flags:
        print(f"{f.path}: {f.safety_flags}")
```

### Delta scan with chain-of-custody verification

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig, manifest_to_json, compute_manifest_checksum
import json

# First scan
manifest = Scanner(source_dir=Path("./project")).scan()
Path("last_manifest.json").write_text(manifest_to_json(manifest))
expected_checksum = manifest.manifest_checksum

# Later: delta scan referencing the previous manifest
config = ScannerConfig(previous_manifest="last_manifest.json")
manifest = Scanner(source_dir=Path("./project"), config=config).scan()

# Verify the delta links back to the expected previous checksum
assert manifest.delta is not None
assert manifest.delta.previous_manifest_checksum == expected_checksum

print(f"Added: {len(manifest.delta.added)}")
print(f"Modified: {len(manifest.delta.modified)}")
print(f"Removed: {len(manifest.delta.removed)}")
print(f"Rescan candidates: {len(manifest.delta.rescan_candidates)}")
```

### Signed manifest for audit

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig, manifest_to_json

signing_key = Path("./secret.key").read_bytes()
config = ScannerConfig(
    enable_specialists=True,
    signing_key=signing_key,
    signing_key_id="scanner-key-2026",
)
manifest = Scanner(source_dir=Path("./archive"), config=config).scan()

# The signing key is NEVER serialized to the manifest;
# only the signing_key_id and the HMAC-SHA256 signature envelope appear.
assert manifest.manifest_signature is not None
print(f"algorithm: {manifest.manifest_signature['algorithm']}")
print(f"key_id:    {manifest.manifest_signature['key_id']}")
print(f"signature: {manifest.manifest_signature['signature'][:16]}...")

Path("signed_manifest.json").write_text(manifest_to_json(manifest))
```

### Inspect signal provenance

```python
from pathlib import Path
from scanner import Scanner

manifest = Scanner(source_dir=Path(".")).scan()

f = manifest.files[0]
for field_name, prov in f.signal_provenance.items():
    print(f"{field_name}: {prov['method']}/{prov['trigger']}")
```

### JSONL output

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig, manifest_to_jsonl

config = ScannerConfig(format="jsonl")
manifest = Scanner(source_dir=Path("."), config=config).scan()

Path("manifest.jsonl").write_text(manifest_to_jsonl(manifest))
```

---

## Output Schema

The JSON manifest follows this structure (abbreviated for readability):

```json
{
  "schema_version": "0.10",
  "context": {
    "logic_version": "0.10.1",
    "scanner_version": "0.10.1",
    "python_version": "3.12.3",
    "platform": "Linux-6.8.0-x86_64",
    "dependencies": {
      "chardet": {"available": true, "version": "5.2.0"},
      "magic":   {"available": true},
      "yaml":    {"available": true},
      "olefile": {"available": true, "version": "0.47"},
      "defusedxml": {"available": true}
    }
  },
  "meta": {
    "scan_id": "550e8400-e29b-41d4-a716-446655440000",
    "generated_at": "2026-04-10T17:30:00+00:00",
    "source_dir": "/absolute/path/to/scanned/directory",
    "config": {
      "preview_max_chars": 1000,
      "sample_size": 8192,
      "baseline_max_bytes": 65536,
      "specialist_budget": 131072,
      "enable_specialists": true,
      "exclude_hidden": false,
      "format": "json",
      "ignore_file": null,
      "previous_manifest": null,
      "extension_overrides": {},
      "signing_key_id": null
    }
  },
  "stats": {
    "total_files": 142,
    "supported_files": 131,
    "unsupported_files": 11,
    "text_files": 96,
    "binary_files": 46,
    "requires_vision": 8,
    "requires_specialist_tool": 14
  },
  "quality": {
    "total_files": 142,
    "clean_files": 138,
    "degraded_files": 3,
    "error_files": 1,
    "mime_mismatches": 2,
    "polyglots_detected": 0,
    "specialist_failures": 1,
    "unsupported_extensions": 11,
    "safety_flags": 0,
    "chatlog_files": 4
  },
  "routing_summary": {
    "baseline_ready": 96,
    "binary_only": 24,
    "requires_vision": 8,
    "requires_specialist_tool": 14
  },
  "delta": null,
  "manifest_checksum": "a1b2c3...",
  "manifest_signature": null,
  "files": [
    {
      "path": "subdir/document.md",
      "filename": "document.md",
      "extension": ".md",
      "mime_type": "text/markdown",
      "size_bytes": 4096,
      "created_at": null,
      "modified_at": "2026-04-10T12:00:00+00:00",
      "checksum_sha256": "a1b2c3...",
      "stage_folder": "subdir",
      "directory_depth": 1,
      "encoding": "utf-8",
      "is_binary": false,
      "requires_vision": false,
      "requires_specialist_tool": false,
      "specialist_tool": null,
      "sidecar_exists": false,
      "frontmatter": {
        "exists": true,
        "keys": ["date", "tags", "title"],
        "raw": "title: My Document\ndate: 2026-04-10\ntags: draft, review"
      },
      "tags": ["draft", "review"],
      "asset_matches": ["images/diagram.png"],
      "content_preview": "# My Document\n\nFirst 1000 characters of content...",
      "structural": {
        "title": "My Document",
        "heading_structure": ["Introduction", "Methods", "Results"],
        "csv_headers": [],
        "document_keys": [],
        "technology_hints": [],
        "filename_date": null
      },
      "mime_analysis": {
        "detected_mime": "text/markdown",
        "extension_mime": "text/markdown",
        "matches_extension": true
      },
      "specialist_metadata": null,
      "file_signature": {"magic_bytes": "2320...", "magic_length": 16},
      "format_signatures": [],
      "is_polyglot": false,
      "is_chatlog": false,
      "safety_flags": [],
      "signal_provenance": {
        "mime_type": {"layer": "raw", "method": "detect_mime", "trigger": "libmagic"},
        "is_binary": {"layer": "derived", "method": "detect_binary", "trigger": "text_ratio_ok"},
        "encoding":  {"layer": "derived", "method": "decode_text", "trigger": "chardet_confident"},
        "is_chatlog": {"layer": "derived", "method": "_detect_chatlog_pattern", "trigger": "content_pattern_none"}
      },
      "errors": []
    }
  ]
}
```

See [`docs/v0.10.0_RFC_Specification.md`](v0.10.0_RFC_Specification.md) for the current spec and [`docs/HISTORY.md`](HISTORY.md) for the full version history including every patch release.

---

## Contributing

### Local development setup

```bash
git clone <repository-url>
cd scanner

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

### Running tests

```bash
# Full suite (561 tests)
python -m pytest tests/ -v

# Single test file
python -m pytest tests/test_unit.py -v

# Single test
python -m pytest tests/test_unit.py::TestDetectChatlogPattern::test_three_speaker_labels_triggers -v
```

### Test structure

| File | Scope |
|---|---|
| `tests/test_unit.py` | Unit tests for all extraction methods, provenance, ScanContext, specialists (PDF, PNG, JPEG, MSG, EML, XLSX, XLS, DOCX, DOC, RTF), chatlog detection and extraction, quality block, safety flags, ZIP security, signature scanning |
| `tests/test_integration.py` | Full `scan()` against `tests/fixtures/`, manifest shape, provenance, routing flags |
| `tests/test_golden.py` | Determinism verification across repeated scans |
| `tests/test_edge_cases.py` | Edge cases: empty files, binary-in-text, ignore rules, delta/rescan, MIME mismatch, all specialists, XML/TOML, HTML, chatlog fixture files |

### Project conventions

- Single-module implementation: all scanner logic lives in `src/scanner/scanner.py`.
- [`docs/v0.10.0_RFC_Specification.md`](v0.10.0_RFC_Specification.md) is the current authoritative spec. RFC normative language applies (BCP 14).
- [`docs/CONVENTIONS.md`](CONVENTIONS.md) describes internal naming, version-bump rules, document promotion paths, and the tracking inventory of specialists / namespaces / magic signatures / safety flags / error codes.
- [`docs/HISTORY.md`](HISTORY.md) is the running index of every version and patch release, with links to specs and compliance reports.
- External dependencies (`python-magic`, `chardet`, `PyYAML`, `olefile`, `defusedxml`) are imported with graceful fallbacks and fingerprinted in `ScanContext.dependencies`.
- All outputs are deterministic: sorted file iteration, sorted tags, sorted keys, sorted list fields within specialist metadata.
