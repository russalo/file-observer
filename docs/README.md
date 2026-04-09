# Scanner

**File capability scanner for document pipeline systems.**

Recursively discovers files under a source directory, extracts universal and format-aware metadata signals, and emits a deterministic JSON manifest. Scanner is an observation layer only -- it never mutates source files, performs OCR, or makes classification decisions.

| | |
|---|---|
| **Package** | `scanner` |
| **Version** | `0.4.1` |
| **Python** | `>= 3.12` |
| **License** | Private |
| **Spec** | [`docs/v0.4.0_RFC_Specification.md`](v0.4.0_RFC_Specification.md) (current), [`docs/v0.3.0 RFC_Specification.md`](v0.3.0%20RFC_Specification.md) (base contract) |
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

# olefile for .msg / .doc envelope extraction
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

If `libmagic` or `chardet` are unavailable, the scanner degrades gracefully to extension-based MIME detection and a fixed encoding cascade.

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
print(manifest_to_json(manifest))
```

### CLI

```bash
# Scan current directory
scanner

# Scan with ignore rules, JSONL output, and delta comparison
scanner ./project --ignore-file .scannerignore --format jsonl --previous-manifest ./last.json

# Scan with all options
scanner /path/to/files -o ./output --exclude-hidden --specialists --format jsonl
```

---

## Key Features

- **Capability-locked determinism** -- identical inputs + identical `ScanContext` always produce identical manifests. Cross-environment variance is explained by dependency versions and logic version.
- **Signal provenance** -- every derived field includes a structured `signal_provenance` entry tracing exactly how and why it was computed (layer, method, trigger, inputs).
- **Signal layering** -- every field is classified as raw (direct observation), derived (computed from raw), or semantic-local (reserved, opt-in).
- **Bounded observation** -- specialist extractors operate within the sample buffer (8KB default). Null means "not observed within bounds."
- **ScanContext** -- environment fingerprint with logic version, scanner version, Python version, platform, and dependency versions.
- **Three capability tiers** -- Universal (every file), Baseline (text-decodeable files), Structural (format-specific keys/headings), and Specialist (bounded metadata probes, opt-in).
- **Specialist metadata** -- PDF (page count, text streams, doc info, encrypted, pdf_version, sample_text_marker_density), PNG (width, height, bit_depth), JPEG (width, height), MSG/EML (subject, from, to, date, message_id, has_attachments), XLSX (sheet_names, header_rows), DOCX (title, author, word_count, heading_count), DOC (title, author), RTF (title, author).
- **Manifest metadata** -- scan ID, runtime config, stats, routing summary, and SHA-256 manifest checksum for auditing and orchestration.
- **JSONL output** -- streaming-friendly NDJSON format with header line + one record per file.
- **Delta scanning** -- compare against a previous manifest to identify added, modified, unchanged, removed files, plus `rescan_candidates` for files with prior specialist failures.
- **Ignore rules** -- `.scannerignore` file support for excluding vendor directories, build artifacts, and user-defined patterns.
- **MIME mismatch signaling** -- per-file `mime_analysis` exposing content-detected vs extension-expected MIME types and match status.
- **Structural signal extraction** -- titles, heading structure, CSV headers, JSON/YAML/XML/TOML document keys, technology hints, filename dates.
- **Intelligent binary detection** -- NUL byte check, MIME-based classification, and text-ratio heuristic (0.85 threshold).
- **Content-based MIME detection** -- `libmagic` primary, extension-based fallback with diagnostic recording.
- **Encoding detection** -- `chardet` with sample-based detection and a four-step fallback cascade (`utf-8` -> `utf-8-sig` -> `cp1252` -> `latin-1`).
- **Tag extraction** -- inline `#hashtags` and frontmatter `tags:` fields with hex-color filtering, stop-word removal, and code-block stripping.
- **Frontmatter parsing** -- YAML frontmatter with `PyYAML` (optional) or string-splitting fallback; malformed fences detected and preserved.
- **Technology detection** -- 18 patterns covering Tailwind, Bootstrap, React, Vue, Alpine, HTMX, jQuery, Svelte, Angular, Chart.js, D3, Mermaid, Docker Compose, Terraform, Ansible, GitHub Actions, and Google Fonts.
- **Sidecar detection** -- checks for companion `.json` and `.md` metadata files.
- **Routing flags** -- `is_binary`, `requires_vision`, `requires_specialist_tool` for downstream pipeline decisions.
- **Non-fatal error model** -- a single unreadable file never halts the scan; structured `ErrorRecord` objects captured per file per stage.
- **Graceful degradation** -- runs without `python-magic`, `chardet`, `PyYAML`, or `olefile` installed.

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
  |    +-- Universal        Identity, filesystem, checksum, routing flags (every file)
  |    +-- MIME Analysis    Content vs extension MIME comparison (every file)
  |    +-- Baseline         Encoding, preview, tags, frontmatter, assets (text files)
  |    +-- Structural       Title, headings, CSV headers, doc keys, tech hints (text files)
  |    +-- Specialist       Format-specific bounded metadata extraction (opt-in)
  |    +-- Provenance       Per-field derivation map (layer, method, trigger)
  |
  +-- Manifest assembly     Context, meta, stats, routing summary, delta, checksum
```

### Capability Tiers

| Tier | Runs for | Gated by |
|---|---|---|
| **Universal** | Every discovered file | Always |
| **Baseline** | Non-binary files | `is_binary == False` |
| **Structural** | Non-binary files (best-effort) | `is_binary == False` |
| **Specialist** | Supported structured formats | `ScannerConfig.enable_specialists` |

### Supported File Types

| Extension | Baseline | Structural Signals | Specialist Tool |
|---|---|---|---|
| `.txt` | encoding, preview, tags | technology_hints, filename_date | -- |
| `.md` / `.mdx` | encoding, preview, tags, frontmatter, assets | title, heading_structure, technology_hints, filename_date | -- |
| `.csv` | encoding, preview, tags | csv_headers, filename_date | -- |
| `.json` | encoding, preview, tags | document_keys, filename_date | validation probe (opt-in) |
| `.yaml` / `.yml` | encoding, preview, tags | document_keys, technology_hints, filename_date | -- |
| `.html` / `.htm` | encoding, preview, tags | title, technology_hints, filename_date | -- |
| `.xml` / `.vx` | encoding, preview, tags | document_keys (root + children), filename_date | -- |
| `.toml` | encoding, preview, tags | document_keys (top-level), filename_date | -- |
| `.css` | encoding, preview, tags | technology_hints, filename_date | -- |
| `.pdf` | -- | filename_date | `pdf_extraction` (page count, text streams, doc info, encrypted, pdf_version, density) |
| `.png` | -- | filename_date | `image_structure` (width, height, bit_depth) |
| `.jpg` / `.jpeg` | -- | filename_date | `image_structure` (width, height) |
| `.msg` | -- | filename_date | `email_envelope` (subject, from, to, date, message_id, has_attachments) |
| `.eml` | -- | filename_date | `email_envelope` (subject, from, to, date, message_id, has_attachments) |
| `.xlsx` | -- | filename_date | `spreadsheet_structure` (sheet_names, header_rows) |
| `.docx` | -- | filename_date | `document_extraction` (title, author, word_count, heading_count) |
| `.doc` | -- | filename_date | `document_extraction` (title, author) |
| `.rtf` | -- | filename_date | `document_extraction` (title, author) |

Unsupported extensions still receive universal-tier processing and are marked with an `unsupported_extension` error record.

---

## CLI Reference

```
usage: scanner [-h] [-o OUTPUT] [--specialists] [--exclude-hidden]
               [--preview-max PREVIEW_MAX] [--format {json,jsonl}]
               [--ignore-file IGNORE_FILE]
               [--previous-manifest PREVIOUS_MANIFEST]
               [source]
```

| Argument | Description | Default |
|---|---|---|
| `source` | Source directory to scan | `.` (cwd) |
| `-o`, `--output` | Output directory for the manifest file | `<package>/manifests/` |
| `--specialists` | Enable specialist tier probes and metadata extraction | Disabled |
| `--exclude-hidden` | Skip files and directories starting with `.` | Disabled |
| `--preview-max` | Maximum characters for content preview | `1000` |
| `--format` | Output format: `json` or `jsonl` | `json` |
| `--ignore-file` | Path to ignore file (glob patterns, one per line) | `.scannerignore` in source dir |
| `--previous-manifest` | Path to previous manifest for delta comparison | None |

### Examples

```bash
# Basic scan
scanner ./project

# Scan with JSONL output and ignore rules
scanner ./project --format jsonl --ignore-file .scannerignore

# Delta scan against previous manifest
scanner ./project --previous-manifest ./manifests/last.json

# Scan with all options
scanner ./project -o ./reports --specialists --exclude-hidden --preview-max 2000 --format jsonl

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
    enable_specialists: bool = False
    exclude_hidden: bool = False
    format: str = "json"
    ignore_file: str | None = None
    previous_manifest: str | None = None
```

Configuration dataclass for tuning scanner behavior.

| Field | Type | Default | Description |
|---|---|---|---|
| `preview_max_chars` | `int` | `1000` | Maximum characters retained in `content_preview`. |
| `sample_size` | `int` | `8192` | Bytes read for binary detection and encoding inference. |
| `enable_specialists` | `bool` | `False` | When `True`, runs format-specific probes (JSON validation, PDF metadata extraction). |
| `exclude_hidden` | `bool` | `False` | When `True`, skips files and directories whose names begin with `.`. |
| `format` | `str` | `"json"` | Output format: `"json"` (standard manifest) or `"jsonl"` (NDJSON, one record per line). |
| `ignore_file` | `str \| None` | `None` | Path to an ignore file. When `None`, checks for `.scannerignore` in the source directory. |
| `previous_manifest` | `str \| None` | `None` | Path to a previous manifest JSON file for delta comparison. |

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
| manifest | `ScanManifest` | Complete scan result with `context`, `meta`, `stats`, `routing_summary`, `delta`, `manifest_checksum`, and `files` list. |

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
1. **Universal tier** -- always runs: stat, checksum, MIME, routing flags.
2. **Baseline tier** -- runs for non-binary files: encoding, preview, tags, frontmatter, assets.
3. **Structural tier** -- runs for non-binary files: title, headings, CSV headers, document keys, technology hints.
4. **Specialist tier** -- runs when `config.enable_specialists` is `True`.

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
    meta: ScanMeta                  # Scan ID, timestamp, source dir, config snapshot
    stats: ScanStats                # File count summaries
    routing_summary: RoutingSummary # Aggregate routing category counts
    delta: DeltaRecord | None       # Delta vs previous manifest, or None
    manifest_checksum: str          # SHA-256 of canonical manifest content
    files: list[FileRecord]         # One record per discovered file
```

Top-level output container. Serializable via `manifest_to_json()` or `manifest_to_jsonl()`.

#### `ScanMeta`

```python
@dataclass
class ScanMeta:
    scan_id: str            # UUID4, unique per scan execution
    generated_at: str       # ISO-8601 UTC timestamp
    source_dir: str         # Absolute path to scanned directory
    config: dict[str, Any]  # Runtime ScannerConfig snapshot
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
    previous_scan_id: str   # scan_id from the previous manifest
    added: list[str]        # Paths present now but not before
    modified: list[str]     # Paths present in both with different checksums
    unchanged: list[str]    # Paths present in both with matching checksums
    removed: list[str]      # Paths present before but not now
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
    specialist_metadata: dict | None    # Format-specific metadata (PDF), or None
    errors: list[ErrorRecord]           # Non-fatal errors from any tier
```

**Null semantics:**
- `created_at`: `None` when the platform does not expose `st_birthtime` (most Linux filesystems).
- `encoding`: `None` for binary files; a detected encoding string or `"unknown"` for text files.
- `specialist_tool`: `None` when `requires_specialist_tool` is `False`; a tool name string when `True`.
- `content_preview`: `None` for binary files; a string (possibly empty) for text files.
- `specialist_metadata`: `None` when specialists are disabled or the file type has no metadata extractor. A dict for PDFs when specialists are enabled.

**Invariants:**
- `requires_specialist_tool == True` implies `specialist_tool is not None` (and vice versa).
- `is_binary == True` implies `encoding is None` and `content_preview is None`.
- Arrays (`tags`, `asset_matches`, `errors`) are always present, never `None`.
- `mime_analysis` is always present, never `None`.

#### `StructuralRecord`

```python
@dataclass
class StructuralRecord:
    title: str | None                  # H1 (markdown) or <title> (HTML)
    heading_structure: list[str]       # Ordered H2 headings (markdown only)
    csv_headers: list[str]             # First-row headers (CSV only)
    document_keys: list[str]           # Top-level keys (JSON/YAML only)
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
    stage: str      # "universal" | "baseline" | "specialist"
```

---

### Functions

#### `manifest_to_json`

```python
def manifest_to_json(manifest: ScanManifest) -> str
```

Serialize a `ScanManifest` to a pretty-printed JSON string.

| Parameter | Type | Description |
|---|---|---|
| `manifest` | `ScanManifest` | The manifest to serialize. |

| Returns | Type | Description |
|---|---|---|
| json_str | `str` | JSON string with 2-space indentation and non-ASCII characters preserved. |

#### `manifest_to_jsonl`

```python
def manifest_to_jsonl(manifest: ScanManifest) -> str
```

Serialize a `ScanManifest` to NDJSON/JSONL format. First line is a header containing `meta`, `stats`, `routing_summary`, `delta`, and `manifest_checksum`. Each subsequent line is one `FileRecord`.

| Parameter | Type | Description |
|---|---|---|
| `manifest` | `ScanManifest` | The manifest to serialize. |

| Returns | Type | Description |
|---|---|---|
| jsonl_str | `str` | Newline-delimited JSON string, one JSON object per line. |

#### `compute_manifest_checksum`

```python
def compute_manifest_checksum(manifest: ScanManifest) -> str
```

Compute the SHA-256 checksum of a manifest's canonical JSON representation (with checksum field set to `""`). Useful for verifying manifest integrity.

---

### Error Codes

| Constant | Value | Stage | Meaning |
|---|---|---|---|
| `ERR_UNIVERSAL_STAT_FAILED` | `"universal_stat_failed"` | universal | `path.stat()` or `path.relative_to()` raised an exception (permission denied, broken path). |
| `ERR_UNSUPPORTED_EXTENSION` | `"unsupported_extension"` | universal | File extension is not in `SUPPORTED_EXTENSIONS`. |
| `ERR_MIME_TYPE_FALLBACK` | `"mime_type_fallback"` | universal | Content-based MIME detection failed or unavailable; extension-based inference was used. |
| `ERR_BASELINE_DECODE_FAILED` | `"baseline_decode_failed"` | baseline | Text decoding or baseline extraction raised an exception. |
| `ERR_SPECIALIST_PROBE_FAILED` | `"specialist_probe_failed"` | specialist | Specialist tier probe raised an exception. |
| `ERR_JSON_PARSE_FAILED` | `"json_parse_failed"` | specialist | JSON file failed `json.loads()` validation. |

---

### Detection Methods

These methods are available on the `Scanner` instance for direct use in advanced workflows.

#### `Scanner.detect_binary`

```python
def detect_binary(self, sample: bytes, mime_type: str) -> bool
```

Determine if a file is binary based on its content sample and MIME type.

| Parameter | Type | Description |
|---|---|---|
| `sample` | `bytes` | First `sample_size` bytes of the file. |
| `mime_type` | `str` | Detected MIME type. |

**Detection chain** (first match wins):
1. NUL byte (`\x00`) in sample.
2. MIME prefix is `image/`, `audio/`, or `video/`.
3. MIME is in the known binary MIME set (PDF, ZIP, Office formats, etc.).
4. MIME starts with `application/` and is not in the text-application set, and the sample fails the text-ratio check.
5. Sample fails the text-ratio check (< 85% printable characters).

#### `Scanner.detect_requires_vision`

```python
def detect_requires_vision(
    self, sample: bytes, mime_type: str, extension: str, is_binary: bool
) -> bool
```

Determine if a file requires image-based interpretation.

Returns `True` for:
- Any `image/*` MIME type.
- `.pdf` files that are binary and lack text stream markers (`/Text`, `BT\n`, `BT\r`, `/Font`).

#### `Scanner.detect_mime`

```python
def detect_mime(self, path: Path, errors: list[ErrorRecord]) -> str
```

Detect MIME type with content-based primary and extension-based fallback.

| Parameter | Type | Description |
|---|---|---|
| `path` | `pathlib.Path` | File to detect. |
| `errors` | `list[ErrorRecord]` | Mutable list; a fallback diagnostic is appended when content-based detection fails. |

| Returns | Type | Description |
|---|---|---|
| mime_type | `str` | Detected MIME type, or `"application/octet-stream"` as final fallback. |

#### `Scanner.decode_text`

```python
def decode_text(self, sample: bytes, path: Path) -> tuple[str, str]
```

Detect encoding and decode file content.

| Parameter | Type | Description |
|---|---|---|
| `sample` | `bytes` | File sample used for `chardet` inference. |
| `path` | `pathlib.Path` | File path (full content is read for decoding). |

| Returns | Type | Description |
|---|---|---|
| `(encoding, text)` | `tuple[str, str]` | Detected encoding name and decoded text. Encoding is `"unknown"` if all strict decodings fail. |

**Cascade:**
1. `chardet` on sample (confidence >= 0.5), if available.
2. `utf-8` -> `utf-8-sig` -> `cp1252` -> `latin-1` strict decoding.
3. `utf-8` with `errors="replace"` (returns encoding `"unknown"`).

---

## Usage Examples

### Programmatic scan with custom config

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig, manifest_to_json

config = ScannerConfig(
    preview_max_chars=500,
    enable_specialists=True,
    exclude_hidden=True,
)

scanner = Scanner(source_dir=Path("/data/inbox"), config=config)
manifest = scanner.scan()

# Filter to only markdown files
md_files = [f for f in manifest.files if f.extension in {".md", ".mdx"}]

for f in md_files:
    print(f"{f.path}: {f.structural.title or '(no title)'}")
    if f.frontmatter.exists:
        print(f"  keys: {f.frontmatter.keys}")
    if f.tags:
        print(f"  tags: {f.tags}")
```

### Find files that need vision processing

```python
from pathlib import Path
from scanner import Scanner

manifest = Scanner(source_dir=Path("./docs")).scan()

vision_files = [f for f in manifest.files if f.requires_vision]
for f in vision_files:
    print(f"  {f.path} ({f.mime_type})")
```

### Export manifest to file

```python
from pathlib import Path
from scanner import Scanner, manifest_to_json

manifest = Scanner(source_dir=Path(".")).scan()

Path("manifest.json").write_text(
    manifest_to_json(manifest),
    encoding="utf-8",
)
```

### Routing files by specialist tool

```python
from pathlib import Path
from scanner import Scanner

manifest = Scanner(source_dir=Path("./uploads")).scan()

for f in manifest.files:
    if f.requires_specialist_tool:
        print(f"{f.path} -> {f.specialist_tool}")
    elif f.is_binary:
        print(f"{f.path} -> binary_skip")
    else:
        print(f"{f.path} -> baseline_ingest")
```

### Inspect errors

```python
from pathlib import Path
from scanner import Scanner

manifest = Scanner(source_dir=Path(".")).scan()

for f in manifest.files:
    for err in f.errors:
        print(f"[{err.stage}] {f.path}: {err.code} - {err.message}")
```

### Delta scanning

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig, manifest_to_json

# First scan
scanner = Scanner(source_dir=Path("./project"))
manifest = scanner.scan()
Path("last_manifest.json").write_text(manifest_to_json(manifest))

# Later: delta scan
config = ScannerConfig(previous_manifest="last_manifest.json")
scanner = Scanner(source_dir=Path("./project"), config=config)
manifest = scanner.scan()

if manifest.delta:
    print(f"Added: {manifest.delta.added}")
    print(f"Modified: {manifest.delta.modified}")
    print(f"Removed: {manifest.delta.removed}")
    print(f"Unchanged: {len(manifest.delta.unchanged)} files")
```

### MIME mismatch detection

```python
from pathlib import Path
from scanner import Scanner

manifest = Scanner(source_dir=Path("./uploads")).scan()

for f in manifest.files:
    if not f.mime_analysis.matches_extension:
        print(f"MISMATCH: {f.path}")
        print(f"  detected: {f.mime_analysis.detected_mime}")
        print(f"  expected: {f.mime_analysis.extension_mime}")
```

### PDF specialist metadata

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig

config = ScannerConfig(enable_specialists=True)
manifest = Scanner(source_dir=Path("./docs"), config=config).scan()

for f in manifest.files:
    if f.specialist_metadata:
        print(f"{f.path}:")
        print(f"  pages: {f.specialist_metadata.get('page_count')}")
        print(f"  text streams: {f.specialist_metadata.get('has_text_streams')}")
        print(f"  title: {f.specialist_metadata.get('title')}")
```

### JSONL output

```python
from pathlib import Path
from scanner import Scanner, ScannerConfig, manifest_to_jsonl

config = ScannerConfig(format="jsonl")
manifest = Scanner(source_dir=Path("."), config=config).scan()

Path("manifest.jsonl").write_text(manifest_to_jsonl(manifest))
```

### Technology detection across a project

```python
from pathlib import Path
from collections import Counter
from scanner import Scanner

manifest = Scanner(source_dir=Path("./project")).scan()

tech_counter = Counter()
for f in manifest.files:
    for hint in f.structural.technology_hints:
        tech_counter[hint] += 1

for tech, count in tech_counter.most_common():
    print(f"  {tech}: {count} files")
```

---

## Output Schema

The JSON manifest follows this structure:

```json
{
  "meta": {
    "scan_id": "550e8400-e29b-41d4-a716-446655440000",
    "generated_at": "2026-04-07T17:30:00+00:00",
    "source_dir": "/absolute/path/to/scanned/directory",
    "config": {
      "preview_max_chars": 1000,
      "sample_size": 8192,
      "enable_specialists": false,
      "exclude_hidden": false,
      "format": "json",
      "ignore_file": null,
      "previous_manifest": null
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
  "routing_summary": {
    "baseline_ready": 96,
    "binary_only": 24,
    "requires_vision": 8,
    "requires_specialist_tool": 14
  },
  "delta": null,
  "manifest_checksum": "sha256hex...",
  "files": [
    {
      "path": "subdir/document.md",
      "filename": "document.md",
      "extension": ".md",
      "mime_type": "text/markdown",
      "size_bytes": 4096,
      "created_at": null,
      "modified_at": "2026-04-07T12:00:00+00:00",
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
        "raw": "title: My Document\ndate: 2026-04-06\ntags: draft, review"
      },
      "tags": ["draft", "review", "inline-tag"],
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
      "errors": []
    }
  ]
}
```

See [`docs/v0.4.0_RFC_Specification.md`](v0.4.0_RFC_Specification.md) for the current spec — semantic naming, deviation policy, specialist contracts, and security requirements.

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
# Full suite (320 tests)
python -m pytest tests/ -v

# Single test file
python -m pytest tests/test_unit.py -v

# Single test
python -m pytest tests/test_unit.py::TestExtractTags::test_basic_hashtags -v
```

### Test structure

| File | Scope |
|---|---|
| `tests/test_unit.py` | Unit tests for all extraction methods, provenance, ScanContext, specialists (PDF, PNG, JPEG, EML, XLSX, DOCX, DOC, RTF), ZIP security |
| `tests/test_integration.py` | Full `scan()` against `tests/fixtures/`, manifest shape, provenance, routing flags |
| `tests/test_golden.py` | Determinism verification across repeated scans |
| `tests/test_edge_cases.py` | Edge cases: empty files, binary-in-text, ignore rules, delta/rescan, MIME mismatch, all specialists, XML/TOML, HTML |

### Project conventions

- Single-module implementation: all scanner logic lives in `src/scanner/scanner.py`.
- `docs/v0.4.0_RFC_Specification.md` is the current authoritative spec. RFC normative language applies (BCP 14). Prior specs: `docs/v0.3.0 RFC_Specification.md`, `docs/SPEC.md` (v0.1).
- External dependencies (`python-magic`, `chardet`, `PyYAML`) are imported with graceful fallbacks.
- All outputs are deterministic: sorted file iteration, sorted tags, sorted keys.
