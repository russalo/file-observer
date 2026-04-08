# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

File capability scanner — observation layer only. Recursively discovers files, extracts metadata and signals, emits a deterministic JSON manifest. Not responsible for ingestion, OCR, embeddings, or classification.

## Spec

- `docs/SPEC.md` — v0.1 base contract (field semantics, null rules, capability tiers)
- `docs/v0.2Spec.md` — v0.2 additions (manifest metadata, stats, delta, JSONL, MIME mismatch)
- `docs/v0.3.0 RFC_Specification.md` — **authoritative v0.3 spec**. Defines capability-locked determinism, signal layering (raw/derived/semantic-local), structured provenance, bounded observation mandate, and specialist expansions.

RFC normative language applies (MUST/SHOULD/MAY per BCP 14). Read the v0.3 RFC before making changes to scanner behavior.

## Stack

Python 3.12. No framework. stdlib + python-magic + chardet. Optional: PyYAML (frontmatter), olefile (MSG). Virtual env at `.venv`.

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

### Specialist tools
| Extension | Tool | What it extracts |
|-----------|------|-----------------|
| `.pdf` | `pdf_scanner` | page count, text streams, doc info, encrypted, pdf_version, sample_text_marker_density |
| `.png` | `png_header` | width, height, bit_depth (IHDR chunk via struct) |
| `.msg` | `msg_envelope` | subject, from, to (OLE2 properties via olefile) |
| `.docx` | `docx_parser` | downstream routing only (no scanner-side extraction) |
| `.rtf` | `rtf_parser` | downstream routing only (no scanner-side extraction) |

## Known decisions

- Specialist tier disabled by default (`ScannerConfig.enable_specialists = False`)
- Preview capped at 1000 chars (`ScannerConfig.preview_max_chars`)
- Binary detection: NUL byte in sample OR MIME prefix/set OR text char ratio < 0.85
- MIME detection: content-based (python-magic/libmagic) primary, extension-based fallback with diagnostic error
- Encoding: chardet (confidence >= 0.50) then cascade: utf-8 → utf-8-sig → cp1252 → latin-1 → replace
- Manifest checksum excludes `scan_id` and `generated_at` (volatile fields)
- ScanContext excludes hostname and timestamps (not causally linked to outputs)
- Signal provenance replaces process_log — per-field, not per-tier
- PDF sample_text_marker_density is a quantitative float, not qualitative labels
- PNG extraction uses stdlib struct, not Pillow
- MSG extraction uses optional olefile, graceful degradation when unavailable

## Test fixtures

`tests/fixtures/` contains sample files across formats (.md, .pdf, .txt, .csv, .html, .yaml, .xlsx, .png, .docx, .rtf, .json, .mdx, .jpg). Use these for integration tests.

Test suite: 258 tests across `test_unit.py`, `test_integration.py`, `test_golden.py`, `test_edge_cases.py`.
