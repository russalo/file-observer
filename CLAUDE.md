# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

File capability scanner — observation layer only. Recursively discovers files, extracts metadata and signals, emits a deterministic JSON manifest. Not responsible for ingestion, OCR, embeddings, or classification.

## Spec

`docs/SPEC.md` is authoritative. RFC normative language applies (MUST/SHOULD/MAY). The spec defines the full JSON output contract, field semantics, null rules, and capability tiers. Read it before making changes to scanner behavior.

## Stack

Python 3.12. No framework. stdlib + python-magic + chardet. Virtual env at `.venv`.

## Commands

```bash
# Activate venv
source .venv/bin/activate

# Install in dev mode (editable)
pip install -e .

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

### Three capability tiers (all in Scanner class)
1. **Universal** — runs for every file: identity, filesystem metadata, checksum, path-derived fields, routing flags (`is_binary`, `requires_vision`, `requires_specialist_tool`)
2. **Baseline** — runs for text-like files: encoding detection, content preview, tag extraction, frontmatter parsing, asset matching
3. **Specialist** — gated behind `ScannerConfig.enable_specialists` (default: False). Placeholder for format-specific parsers (PDF, DOCX, RTF)

### Key data flow
`Scanner.scan()` → `iter_files()` walks directory → `scan_file()` per file → builds `FileRecord` dataclass → assembled into `ScanManifest` → serialized via `manifest_to_json()`

### Core dataclasses
- `FileRecord` — one per discovered file, all fields from the spec contract
- `FrontmatterRecord` — nested in FileRecord for markdown frontmatter
- `ErrorRecord` — non-fatal errors captured per file per stage
- `ScanManifest` — top-level output: `generated_at`, `source_dir`, `files[]`

## Known decisions

- Specialist tier disabled by default (`ScannerConfig.enable_specialists = False`)
- Preview capped at 1000 chars (`ScannerConfig.preview_max_chars`)
- Binary detection: NUL byte in sample OR text char ratio < 0.85
- MIME detection currently extension-based only (`mimetypes.guess_type`); spec prefers content-based (python-magic)
- Encoding cascade: utf-8 → utf-8-sig → cp1252 → latin-1 → replace fallback
- Sidecar convention: `stem.json`, `name.ext.json`, or `name.ext.md`
- Tags: inline `#hashtags` + frontmatter `tags:` field, deduplicated and sorted
- Asset matches: markdown link/image references to local (non-http) paths

## Test fixtures

`tests/fixtures/` contains sample files across formats (.md, .pdf, .txt, .csv, .html, .yaml, .xlsx, .png). Use these for integration tests. No test suite exists yet — tests need to be written.
