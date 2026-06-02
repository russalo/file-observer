# File Observer

**Know what's in your files before you open them.**

*A one-shot, read-only observation pass — not a file watcher. Point it at a directory, get one deterministic JSON manifest of what's inside, before you ingest it.*

File Observer makes a single read-only pass over a directory and tells you exactly what's inside — file types, metadata, conversation patterns, author fingerprints, structural signals — all in one deterministic JSON manifest. You run it on demand; it doesn't stay resident or watch for changes. It reads everything. It changes nothing.

```bash
pip install file-observer
fo ./your-project --specialists
```

```
Scanned 4,366 files (3,526 text, 840 binary) in 31 directories.

1,163 supported (336 with specialist metadata). 3,203 unsupported extensions.
Quality: 676 clean, 3,690 degraded. 4 safety flags, 2 polyglots.

Vectors: author_aggregate found 64 distinct authors across 114 files.
chatlog matched 22 files. reference_tokens ran on 806 files (2,164 URLs,
382 paths, 262 @mentions). filename_patterns matched 84 of 4366 files.

Largest directories: tika-parsers (2,037), tika-pipes (459), tika-core (440).
```

That's the human-readable summary. The full manifest is structured JSON — here's a truncated file object so you can see the data contract before you install:

```json
{
  "schema_version": "1.2",
  "context": { "scanner_version": "1.3.0", "logic_version": "1.2.0", "...": "…" },
  "files": [
    {
      "path": "docs/report.pdf",
      "mime_type": "application/pdf",
      "checksum_sha256": "9f86d081884c7d65…",
      "is_binary": true,
      "requires_specialist_tool": true,
      "specialist_tool": "pdf_extraction",
      "safety_flags": ["has_javascript"],
      "signal_provenance": {
        "requires_specialist_tool": { "layer": "derived", "method": "specialist_tools_registry", "trigger": "extension_match" }
      },
      "...": "…"
    }
  ],
  "vectors_collected": [
    { "vector_id": "chatlog", "method_version": 8, "identity_digest": "a3f1c2…", "...": "…" }
  ],
  "manifest_checksum": "7d2bafef…",
  "manifest_signature": { "algorithm": "hmac-sha256", "key_id": "default", "value": "…" }
}
```

Every derived field carries a `signal_provenance` entry; every vector an `identity_digest`; the whole manifest a checksum and optional HMAC signature.

| | |
|---|---|
| **Package** | `file-observer` |
| **CLI** | `file-observer` or `fo` (shorthand) |
| **Version** | `1.3.0` |
| **Schema** | `1.2` |
| **Python** | `>= 3.12` |
| **License** | [AGPL-3.0](https://github.com/russalo/file-observer/blob/main/LICENSE) (commercial license available) |
| **Tests** | 661 passed; ran clean (zero fatal errors) — see "Validated at scale" below |

---

## Why File Observer?

**Your pipeline needs to know what it's processing before it processes it.** File Observer is the observation layer that sits at the front of any document pipeline — ingestion, classification, OCR, embedding, audit. It tells the pipeline what's coming without touching the files. *(Need to react to filesystem changes as they happen? That's a watcher like watchdog or watchfiles — a different tool.)*

- **Deterministic.** Same files + same config = identical manifest, every time. Cross-environment variance is explained, never hidden.
- **Auditable.** Every derived field has a provenance trace — which method, which trigger, which inputs. Nothing is a black box.
- **Honest.** `null` means "not observed within bounds," not "not present." Safety flags are observations, not assessments. The scanner records; the consumer interprets.
- **Verified.** Cryptographic identity digests on every vector. HMAC-signed manifests. Chain-of-custody across incremental scans.

---

## What it observes

### 25 file types, 4 capability tiers

| Tier | Runs for | What it extracts |
|---|---|---|
| **Universal** | Every file | Identity, checksum, MIME, file signatures, polyglot detection, routing flags |
| **Baseline** | Text files | Encoding, preview, tags, frontmatter, chatlog detection, reference tokens, filename patterns |
| **Structural** | Text files | Title, headings, CSV headers, JSON/YAML/XML/TOML keys, technology hints |
| **Specialist** | Supported formats (opt-in) | PDF pages, image dimensions, email envelopes, spreadsheet structure, document metadata |

Supported specialist formats: `.pdf`, `.png`, `.jpg`, `.msg`, `.eml`, `.xlsx`, `.xls`, `.docx`, `.doc`, `.rtf`, `.jsonl`

### 4 observation vectors with cryptographic identity

| Vector | What it finds |
|---|---|
| **chatlog** | Conversation patterns — turns, speakers (per-speaker counts/alternation), section markers. Detects prose transcripts and conversational JSON/JSONL across common schemas (role/from/speaker + text/value/content). Works on `.txt`, `.md`, `.jsonl`, `.json`. |
| **reference_tokens** | @mentions, wiki links, code blocks, URLs, emails, file paths, ticket numbers |
| **author_aggregate** | Cross-format author normalization. Spots template defaults vs real humans. |
| **filename_patterns** | Date prefixes, version markers, numbered revisions, template names, UUIDs, copy suffixes |

Each vector carries an identity digest (SHA-256). Same digest = same rules + same tuning = same output. Always. *(These are observation vectors — named, fingerprinted observations — not embedding vectors for a vector database.)*

### Safety and integrity

- **Safety flags** — detects JavaScript in PDFs, macros in DOCX, OLE objects in RTF, external entities in XML
- **Manifest checksum** — SHA-256 over the canonical manifest
- **HMAC signatures** — optional signed manifests for audit chains
- **Delta scanning** — diff two manifests from separate runs to see added/modified/removed files. Snapshot-to-snapshot, not live change events.
- **Per-directory summary** — corpus shape visible at a glance
- **Duplicate detection** — files grouped by identical content checksum (`quality.duplicate_clusters`); surfaces redundant copies for migration/dedup
- **Per-specialist stats** — attempted/succeeded/failed per specialist tool, so extraction quality is visible, not implied

---

## Quick start

### Install

```bash
pip install file-observer

# Optional: specialist format support
pip install "file-observer[msg]"       # .msg/.doc/.xls (OLE2 formats)
pip install "file-observer[security]"  # Hardened XML parsing
pip install "file-observer[dev]"       # Full dev environment
```

**Optional:** `libmagic` sharpens content-based MIME detection. As of v1.3 it's no longer required — without it (Windows, minimal containers) File Observer falls back to a built-in **pure-Python content sniff** for common binary formats (archives, images, data, media), then extension-based inference. Install it for the widest coverage:
```bash
sudo apt install libmagic1    # Debian/Ubuntu
brew install libmagic         # macOS
pip install python-magic-bin  # Windows (or rely on the pure-Python fallback)
```

### Scan

```bash
# Quick scan
fo ./project

# Deep scan with specialist metadata
fo ./project --specialists

# Named profile with JSONL output
fo ./project --profile deep_extract --format jsonl

# Delta scan against a previous manifest, signed
fo ./project --previous-manifest ./last.json --signing-key-file ./key
```

### Use in code

```python
from pathlib import Path
from file_observer import Scanner, ScannerConfig, manifest_to_json

config = ScannerConfig(enable_specialists=True)
manifest = Scanner(source_dir=Path("./documents"), config=config).scan()

# Human-readable summary
print(manifest.summary)

# Find conversation logs
for f in manifest.files:
    if f.is_chatlog and f.specialist_metadata:
        chat = f.specialist_metadata["chatlog"]
        print(f"{f.path}: {chat['turn_count']} turns, {chat['speaker_labels']}")

# Triage via quality block
q = manifest.quality
print(f"{q.clean_files}/{q.total_files} clean, {q.safety_flags} safety flags")

# Write manifest
Path("manifest.json").write_text(manifest_to_json(manifest))
```

Every scan also produces a standalone Markdown report (`report_v{version}_{timestamp}.md`) — readable in any browser, shareable, no JSON parsing required.

---

## Use cases

### Document pipeline preprocessing
Point File Observer at an incoming document folder before your ingestor touches it. Know which files need OCR, which have specialist metadata, which are mislabeled, and which carry safety flags — before processing begins.

### AI training data curation
Scanning AI conversation logs, knowledge bases, and document corpora? File Observer detects chatlog patterns in `.txt`, `.md`, and `.jsonl` files, counts turns and speakers, and surfaces reference tokens (URLs, @mentions, code blocks) across thousands of files. Built for the datasets that train and evaluate language models.

### Audit and compliance
Every field has a provenance trace. Every vector has a cryptographic identity digest. Manifests can be HMAC-signed with chain-of-custody across incremental scans. When the auditor asks "how do you know this file contains X?" — the manifest answers.

### Knowledge management and vault analysis
Run File Observer against an Obsidian vault, a Confluence export, or a shared drive. The per-directory summary shows corpus shape instantly. Reference tokens reveal link density, cross-references, and structural patterns. Author aggregation spots template defaults vs real contributors.

### Migration and deduplication
Moving files between systems? File Observer gives you checksums, MIME analysis, format signatures, and polyglot detection for every file. Delta scanning tracks what changed between runs. Filename patterns catch copy suffixes, numbered revisions, and UUID-named files.

### Security triage
Safety flags surface JavaScript in PDFs, macros in DOCX files, OLE objects in RTF, and external entities in XML — without opening or executing anything. Surface them to your security pipeline, where *your own policy* decides quarantine or triage. The flags are structural observations, not verdicts — expect false positives and negatives, and tune your own thresholds.

---

## How it works

```
fo ./corpus --specialists
  |
  +-- Universal tier     Every file: checksum, MIME, signatures, routing
  +-- Baseline tier      Text files: encoding, preview, tags, chatlog detection
  +-- Structural tier    Text files: title, headings, keys, technology hints
  +-- Specialist tier    Format-specific: PDF, images, email, spreadsheets, documents
  +-- Vector pass        chatlog, reference_tokens, filename_patterns (per-file)
  +-- Corpus vectors     author_aggregate (after all files processed)
  +-- Summary            Human-readable paragraph + per-directory breakdown
  |
  +-- Output: manifest.json + report.md
```

One file failure never halts the scan. Errors are captured per-file, per-stage. The manifest is always complete.

---

## Configurable depth

| Profile | Baseline | Specialists | Use case |
|---|---|---|---|
| `fast_sort` | 8KB | Off | Quick triage, file routing |
| `general` | 64KB | Off | Standard observation |
| `deep_extract` | 1MB | On | Full metadata extraction |

Per-extension overrides let you give specific formats more budget:
```bash
fo ./docs --specialists --extension-override .pdf:specialist_budget=524288
```

---

## Validated at scale

File Observer has run cleanly — **zero fatal errors** — across 12 real-world corpora totaling 28,756 files. (This measures robustness, not extraction accuracy; precision/recall benchmarks are planned.)

| Corpus | Files | What it tested |
|---|---|---|
| Apache Tika | 4,366 | 152 document specialists, 69 PDFs, 57 spreadsheets, 13 emails |
| OBS Studio | 5,201 | Large C/C++ project, 91 filename patterns |
| AutoGPT | 3,945 | AI platform, 1,612 @mentions; chatlog FP-hardening validation (raw detections cut sharply by v1.2.x) |
| FastAPI | 3,002 | Documentation-heavy Python, chatlog tuning validation |
| OpenPreserve | 753 | Adversarial format samples, 285 PDFs |
| Claude Code logs | 125 | Real AI conversation transcripts, JSONL chatlog detection |
| Flask, tmux, self-scan | 11K+ | Diverse code repos |

---

## Documentation

| Document | What it covers |
|---|---|
| [HISTORY.md](HISTORY.md) | Every version from v0.1 to the current release, with specs and compliance reports |
| [PUBLIC_CONTRACT.md](PUBLIC_CONTRACT.md) | Consumer stability commitments — what you can rely on |
| [CONVENTIONS.md](CONVENTIONS.md) | Internal naming, versioning, and tracking |
| [v1.3.0 RFC Specification](v1.3.0_RFC_Specification.md) | Current release spec — pure-Python MIME fallback. v1.0.0 RFC remains the binding schema-freeze contract. |

---

## API Reference

### Core classes

```python
Scanner(source_dir: Path, config: ScannerConfig | None = None)
Scanner.scan() -> ScanManifest
```

### Configuration

```python
ScannerConfig(
    enable_specialists=False,    # Enable format-specific extraction
    preview_max_chars=1000,      # Content preview length
    sample_size=8192,            # Binary detection sample
    baseline_max_bytes=65536,    # Text decode limit
    specialist_budget=131072,    # OOXML read budget
    format="json",               # "json" or "jsonl"
    exclude_hidden=False,        # Skip dot-files
    ignore_file=None,            # Path to .scannerignore
    previous_manifest=None,      # Delta scan reference
    signing_key=None,            # HMAC signing key
)
```

### Output

```python
manifest_to_json(manifest)      # Pretty-printed JSON
manifest_to_jsonl(manifest)     # NDJSON streaming format
manifest_to_markdown(manifest)  # Human-readable report
```

### Key data classes

- **`ScanManifest`** — top-level: context, stats, quality, vectors_collected, summary, files[]
- **`FileRecord`** — per-file: path, mime, checksum, encoding, specialist_metadata, reference_tokens, filename_patterns, safety_flags, signal_provenance, errors
- **`ScanContext`** — environment fingerprint: versions, platform, dependencies
- **`VectorRecord`** — vector identity, digest, scope, applied count, summary

---

## Contributing

We welcome contributions. See [CONTRIBUTING.md](https://github.com/russalo/file-observer/blob/main/CONTRIBUTING.md) for the full guide.

**Quick version:**
1. Fork and clone
2. `pip install -e ".[dev]"` and run tests
3. Sign the [CLA](https://github.com/russalo/file-observer/blob/main/CLA.md) on your first PR
4. One concern per PR, tests required, determinism preserved

---

## License

File Observer is dual-licensed:

- **Open source** under [AGPL-3.0](https://github.com/russalo/file-observer/blob/main/LICENSE) — use freely, contribute back
- **Commercial license** available for cases where AGPL terms don't fit

### Which one applies to you

**The AGPL is fine — no commercial license needed — for:**

- Internal use: running File Observer inside your own organization, including on private servers, with no obligation to publish anything.
- Personal projects, research, and evaluation.
- Open-source projects that are themselves AGPL-compatible.

**You likely want a commercial license if you:**

- **Embed** File Observer in a proprietary product you distribute without releasing that product's source under the AGPL.
- **Offer it over a network as a service** (SaaS). The AGPL's network clause (§13) means that if users interact with a modified version over a network, you must offer them its complete corresponding source. A commercial license removes that obligation.
- **Distribute** File Observer (or a derivative) to third parties without the AGPL's source-disclosure requirements.

In short: AGPL obligations are triggered by **distribution** and by **network use of modified versions**, not by private internal use. If you're unsure whether your use triggers them, that's exactly what a commercial license resolves.

Contact **russalo@russalo.com** for commercial terms.

> This is a plain-language summary, not legal advice or a substitute for the [license text](https://github.com/russalo/file-observer/blob/main/LICENSE). Where this summary and the license differ, the license governs.

---

*Built by [Russalo](https://russalo.com). The scanner records. The consumer interprets. The identity digest makes the recording auditable.*
