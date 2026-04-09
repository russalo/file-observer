# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

File capability scanner — observation layer only. Recursively discovers files, extracts metadata and signals, emits a deterministic JSON manifest. Not responsible for ingestion, OCR, embeddings, or classification.

## Spec

- `docs/v0.5.0_RFC_Specification.md` — **current release spec**. Namespaced specialist_metadata, schema_version, baseline_max_bytes, cross-platform hardening, silent failure fixes.
- `docs/v0.6.0_RFC_DRAFT.md` — next target: dip switches, structural signatures, integrity envelope.
- `docs/v1.0.0_RFC_DRAFT.md` — schema freeze draft. v1.0 = scanner maturity + backward compatibility policy.
- `docs/v0.4.0_RFC_Specification.md` — semantic naming, deviation policy, coverage expansion.
- `docs/v0.3.0 RFC_Specification.md` — base contract: capability-locked determinism, signal layering, provenance, bounded observation.

RFC normative language applies (MUST/SHOULD/MAY per BCP 14). Read the v0.5 RFC before making changes to scanner behavior.

## Stack

Python 3.12. No framework. stdlib + python-magic + chardet. Optional: PyYAML (frontmatter), olefile (MSG/DOC), defusedxml (hardened XML). Virtual env at `.venv`.

## Version roadmap

- v0.5.0 (current): schema reshaping — namespaced specialist_metadata, schema_version field, baseline_max_bytes cap, CRLF hardening, silent failure fixes.
- v0.6.0 (next): dip switches (configurable depth per extension), structural file signatures, polyglot detection, data integrity envelope.
- v1.0.0 (target): schema freeze + backward compatibility policy. Scanner is a configurable observation engine that's honest, verifiable, and stable.

## Commands

```bash
# Activate venv
source .venv/bin/activate

# Install in dev mode (editable)
pip install -e ".[dev]"

# Run scanner (after install)
scanner

# Run scanner directly
python src/scanner/scanner.py

# Run all tests
python -m pytest tests/

# Run a single test
python -m pytest tests/test_foo.py::test_name -v
```

## Architecture

Single-module implementation in `src/scanner/scanner.py`. No package structure beyond that.

### v0.3 Design Pillars
1. **Capability-locked determinism** — identical inputs + identical `ScanContext` → identical outputs. Variance across environments must be explained by context (dependency versions, logic version).
2. **Signal layering** — every field is raw (direct observation), derived (computed from raw via deterministic logic), or semantic-local (reserved, opt-in). Layer membership is a contract.
3. **Structured provenance** — every derived field has a `signal_provenance` entry with `layer`, `method`, `trigger`, optional `inputs` and `detail`. Replaces process_log entirely.
4. **Bounded observation** — specialists operate within `sample_size` (8KB default). Null means "not observed within bounds," not "not present in the file."

### Capability tiers (all in Scanner class)
1. **Universal** — runs for every file: identity, filesystem metadata, checksum, path-derived fields, routing flags (`is_binary`, `requires_vision`, `requires_specialist_tool`), MIME analysis
2. **Baseline** — runs for text-like files: encoding detection, content preview, tag extraction, frontmatter parsing, asset matching
3. **Structural** — runs for text-like files: title, headings, CSV headers, document keys (JSON/YAML/XML/TOML), technology hints
4. **Specialist** — gated behind `ScannerConfig.enable_specialists` (default: False). Format-specific bounded metadata extraction (PDF, PNG, MSG)

### Key data flow
`Scanner.scan()` → `_build_context()` → `iter_files()` walks directory → `scan_file()` per file (builds `FileRecord` + `signal_provenance`) → assembled into `ScanManifest` with `context`, `meta`, `stats`, `routing_summary`, `delta`, `manifest_checksum` → serialized via `manifest_to_json()` or `manifest_to_jsonl()`

### Core dataclasses
- `ScanContext` — environment fingerprint: logic version, scanner version, python version, platform, dependency versions
- `ProvenanceEntry` — per-field derivation record: layer, method, trigger, inputs, detail
- `FileRecord` — one per discovered file, all fields from spec contract + `signal_provenance` dict
- `ScanManifest` — top-level output: `context`, `meta`, `stats`, `routing_summary`, `delta`, `manifest_checksum`, `files[]`
- `MimeAnalysisRecord` — content vs extension MIME comparison
- `FrontmatterRecord` — markdown frontmatter extraction
- `StructuralRecord` — structural signals (title, headings, keys, etc.)
- `ErrorRecord` — non-fatal errors captured per file per stage

### Specialist tools (semantic names — describe downstream need, not scanner implementation)
| Extension | Tool | What it extracts |
|-----------|------|-----------------|
| `.pdf` | `pdf_extraction` | page count, text streams, doc info, encrypted, pdf_version, sample_text_marker_density |
| `.png` | `image_structure` | width, height, bit_depth (IHDR chunk via struct) |
| `.jpg`/`.jpeg` | `image_structure` | width, height (SOF0/SOF2 markers via struct) |
| `.msg` | `email_envelope` | subject, from, to, date, message_id, has_attachments (OLE2 via olefile) |
| `.eml` | `email_envelope` | subject, from, to, date, message_id, has_attachments (stdlib email.parser) |
| `.xlsx` | `spreadsheet_structure` | sheet_names, header_rows (stdlib zipfile + XML, 128KB deviation) |
| `.docx` | `document_extraction` | title, author, word_count, heading_count (OOXML ZIP, 128KB deviation) |
| `.doc` | `document_extraction` | title, author (OLE2 SummaryInformation via olefile) |
| `.rtf` | `document_extraction` | title, author ({\info} group regex on sample) |

## Known decisions

- Specialist tier disabled by default (`ScannerConfig.enable_specialists = False`)
- Preview capped at 1000 chars (`ScannerConfig.preview_max_chars`)
- Binary detection: NUL byte in sample OR MIME prefix/set OR text char ratio < 0.85
- MIME detection: content-based (python-magic/libmagic) primary, extension-based fallback with diagnostic error
- Encoding: chardet (confidence >= 0.50) then cascade: utf-8 → utf-8-sig → cp1252 → latin-1 → replace
- Manifest checksum excludes `scan_id` and `generated_at` (volatile fields)
- Manifest filename includes version: `manifest_v{VERSION}_{timestamp}.json`
- ScanContext excludes hostname and timestamps (not causally linked to outputs)
- Signal provenance replaces process_log — per-field, not per-tier
- Specialist tool names are semantic (describe downstream need, not scanner implementation)
- PDF sample_text_marker_density is a quantitative float, not qualitative labels
- PNG/JPEG extraction uses stdlib struct, not Pillow
- MSG/DOC extraction uses optional olefile, graceful degradation when unavailable
- EML extraction uses stdlib email.parser, no external dependencies
- XLSX/DOCX use 128KB deviation budget (declared exception to 8KB bounded observation)
- ZIP entries validated against path traversal (_is_safe_zip_entry), decompressed size capped at 1MB (_safe_zip_read)
- XML parsing uses defusedxml when available, stdlib fallback with documented risk

## Test fixtures

`tests/fixtures/` contains sample files across formats (.md, .pdf, .txt, .csv, .html, .yaml, .xlsx, .png, .docx, .rtf, .json, .mdx, .jpg). Use these for integration tests.

Test suite: 320 tests across `test_unit.py`, `test_integration.py`, `test_golden.py`, `test_edge_cases.py`.
