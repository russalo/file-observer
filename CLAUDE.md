# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

File Observer — observation layer only. Recursively discovers files, extracts metadata and signals, emits a deterministic JSON manifest. Not responsible for ingestion, OCR, embeddings, or classification.

## Spec

- `docs/v1.2.0_RFC_Specification.md` — **current release spec** (patches v1.2.1–v1.2.4 against it — documented in HISTORY.md, no RFC). Chatlog generalized & hardened detection (conversational JSON/JSONL across role/content schemas, `.json` candidate) + per-speaker structure (provisional). Patches tightened chatlog FP rules. Net current: **LOGIC 1.1.4, chatlog method_version 8**, SCHEMA 1.2.
- `docs/v1.1.0_RFC_Specification.md` — prior. Corpus Intelligence: `quality.duplicate_clusters` + `quality.specialist_stats` (both provisional).
- `docs/v1.0.0_RFC_Specification.md` — prior. Schema freeze. Public contract binding. Backward compatibility policy.
- `docs/archive/0.x/v0.11.0_RFC_Specification.md` — prior release. Provisional → stable promotions, SECURITY.md.
- `docs/archive/0.x/v0.10.0_RFC_Specification.md` — prior release. Human-readable scan summary, author_aggregate corpus vector, filename_patterns vector.
- `docs/archive/0.x/v0.9.0_RFC_Specification.md` — prior release. Vector abstraction (identity digest, rules_hash, static_tuning_hash), `vectors_collected[]` manifest block, chatlog vector (refactored from v0.8), reference_tokens vector (7 subcategories), email body chatlog cross-cut, per-directory aggregation, Dublin Core adoption. All v0.9 additions provisional.
- `docs/archive/0.x/v0.8.0_RFC_Specification.md` — prior release. Chatlog specialist (first content-detected, not extension-based): is_chatlog flag, drift-visible signals (turn counts, speaker labels, section markers, reference tokens, top capitalized tokens, vocabulary estimate).
- `docs/archive/0.x/v0.7.0_RFC_Specification.md` — v0.7.x line. XLS specialist, spreadsheet `format` field, safety_flags, ScanQuality block. v0.7.1 and v0.7.2 are patch releases against this spec — see HISTORY.md.
- `docs/archive/0.x/v0.6.0_RFC_Specification.md` — configurable depth (specialist_budget, extension_overrides, profiles), structural signatures, polyglot detection, integrity envelope (HMAC manifest_signature).
- `docs/archive/0.x/v0.5.0_RFC_Specification.md` — schema reshape: namespaced specialist_metadata, schema_version field, baseline_max_bytes, cross-platform hardening.
- `docs/archive/0.x/v0.4.0_RFC_Specification.md` — semantic specialist tool naming, deviation policy, coverage expansion (JPEG, EML, XLSX, MSG enrichment).
- `docs/archive/0.x/v0.3.0 RFC_Specification.md` — base contract: capability-locked determinism, signal layering, provenance, bounded observation.
- `docs/HISTORY.md` — running index of all versions and patch releases. Start here when orienting.
- `docs/CONVENTIONS.md` — internal naming, version-bump rules, document promotion paths, tracking inventory of specialists / namespaces / signatures / safety flags / error codes.
- `docs/PUBLIC_CONTRACT.md` — consumer-facing stability commitments. **Binding as of v1.0.**

RFC normative language applies (MUST/SHOULD/MAY per BCP 14). Read the v1.0 RFC plus HISTORY.md before making changes.

## Package and distribution

| | |
|---|---|
| **Package name** | `file-observer` |
| **CLI commands** | `file-observer` or `fo` (shorthand) |
| **PyPI** | https://pypi.org/project/file-observer/ |
| **GitHub** | https://github.com/russalo/file-observer (public) |
| **License** | AGPL-3.0 + dual commercial (see LICENSE) |
| **Copyright** | Russell Pfister |
| **Publishing** | GitHub Release triggers `.github/workflows/publish.yml` → PyPI via trusted publisher |

## Workbench (shared working surface)

The project uses Tether for human-AI collaboration. The workbench serves editable JSON docs in a browser over tailnet.

- **Tether repo:** `/srv/projects/pkplab/tether/` (see BOOTSTRAP.md and WORKBENCH.md there)
- **Scanner workbench data:** `scratch/workbench/` (gitignored)
- **Hub port:** 8800 (manages all project instances on this node)
- **Scanner instance port:** 8801
- **Tailnet access:** `http://origin-core:8800` (hub) / `http://origin-core:8801` (scanner workbench)
  - Full DNS: `origin-core.taild63637.ts.net`
  - Short: `origin-core` (works inside tailnet via search-domain)
  - IPv4: `100.89.175.30`

**After a server reboot**, the workbench must be restarted:
```bash
cd /srv/projects/pkplab/tether
nohup python3 hub.py --port 8800 > /tmp/workbench-hub.log 2>&1 &
curl -s -X POST http://localhost:8800/api/start \
  -H 'Content-Type: application/json' \
  -d '{"project": "scanner", "data_dir": "/srv/projects/pkplab/scanner/scratch/workbench", "port": 8801}'
```

**Future:** systemd unit for auto-start on boot (pattern: `/etc/systemd/system/blog.service` on origin-core). Manual restart is acceptable while iterating.

## Stack

Python 3.12. No framework. stdlib + python-magic + chardet. Optional: PyYAML (frontmatter), olefile (MSG/DOC/XLS — required for OLE2 specialists), defusedxml (hardened XML). Virtual env at `.venv`.

## Version roadmap

- **v1.2.x (current; shipped & live on PyPI):** v1.2.0 — Chatlog generalized & hardened detection — recognizes conversational JSON/JSONL across role/content schemas (ConvoKit/ShareGPT/oasst/hh-rlhf), `.json` candidate; markdown FPs cut ~96%; `ErrorRecord.detail`; per-speaker structure (`speaker_turn_counts`/`speaker_turn_chars`/`alternation`, provisional). SCHEMA 1.1 → 1.2; LOGIC 1.0.0 → 1.1.0; method_version 3 → 4. **v1.2.1** (patch) — chatlog FP fixes from adversarial self-review: markdown structure rules require a **speaker** co-signal (date co-signal dropped); JSON detection requires ≥2 distinct speakers. LOGIC → 1.1.1; method_version → 5. **v1.2.2** (patch) — prose FP fixes found by the empirical corpus sweep: prose Rule 1 requires ≥2 distinct speakers AND ≥1 recurring speaker; stop-list expanded with header/man-page/form labels. LOGIC → 1.1.2; method_version → 6. **v1.2.3** (patch) — FAQ FP stopgap: `Question`/`Answer` added to the stop-list (cross-model reviewed by Gemini flash + pro; the deeper root — prose `Key:value` ambiguous with dialogue — deferred to a future non-count signal). LOGIC → 1.1.3; method_version → 7. **v1.2.4** (patch) — two clean wins from the in-house multi-agent code-review (issues the cross-model reviews missed): case-INSENSITIVE stop-list (closes the ALL-CAPS `FROM:`/`SUBJECT:` header hole + drops dual-listing) and `_string_has_speaker_dialogue` brought to parity with prose Rule 1 (no more JSON-string-vs-prose asymmetry). LOGIC → 1.1.4; method_version → 8. Net current: **LOGIC 1.1.4, chatlog method_version 8**, SCHEMA 1.2.
- **v1.1.0:** Corpus Intelligence (first additive minor after the freeze): `quality.duplicate_clusters` (+ counts) and `quality.specialist_stats`, both provisional, pure observation. SCHEMA 1.0 → 1.1; LOGIC unchanged.
- **v1.0.x:** v1.0.1 — import package renamed `scanner` → `file_observer` (deprecated `scanner` shim), LIMITATIONS.md, license clarity. v1.0.2 — README/PyPI positioning + honesty hardening (no scan-behavior change). Both patches; SCHEMA/LOGIC unchanged.
- **v1.0.0:** Schema freeze. Public contract binding. Backward compatibility policy. No new features — governance declaration on a proven-stable codebase. SCHEMA_VERSION 0.11 → 1.0.
- **v0.11.0:** Field stability promotions — vectors_collected, reference_tokens, per_directory_summary, email.body_chatlog, filename_patterns all promoted from provisional to stable. SECURITY.md added. No new features. SCHEMA_VERSION 0.10 → 0.11.
- **v0.10.x:** v0.10.1 adds JSONL chatlog detection (`.jsonl` files with `"type": "user"/"assistant"` role objects). v0.10.0: Human-readable scan summary, `author_aggregate` corpus vector (cross-specialist author normalization + template-default detection), `filename_patterns` vector (6 boolean subcategories on every file). Four vectors in `vectors_collected[]`. SCHEMA_VERSION 0.9 → 0.10 (additive).
- **v0.9.x:** Vector abstraction — the scanner becomes a corpus observer. `Vector` dataclass with identity digest (SHA-256). New `vectors_collected[]` manifest block. Two exemplar vectors: `chatlog` (refactored from v0.8) and `reference_tokens` (7 subcategories: at_mentions, wiki_links, code_fence_blocks, url_count, email_mentions, path_references, numeric_id_patterns). Per-file `reference_tokens` field on text files. Email body chatlog cross-cut. Per-directory aggregation in `quality.per_directory_summary[]`. Dublin Core adopted in standards tracking. All v0.9 additions provisional. SCHEMA_VERSION 0.8 → 0.9 (additive).
- **v0.8.0:** chatlog content-based specialist. First content-detected (not extension-driven) dispatch in the scanner: `is_chatlog` flag runs even with specialists disabled; `_extract_chatlog_metadata` produces 11 drift-visible fields when enabled; new `chatlog` namespace + MIME guard; `quality.chatlog_files` counter. SCHEMA_VERSION 0.7 → 0.8 (additive).
- **v0.7.x:** XLS specialist + safety_flags + ScanQuality block (v0.7.0); UTF-16/UTF-32 BOM detection + OLE2 specialists pass file path instead of 8KB sample (v0.7.1, fixes silent breakage of msg/doc/xls extraction); MSG date extraction via MAPI properties stream + MSG `from` prefers display name over Exchange legacyDN (v0.7.2). Both patches found from real-world corpus scanning.
- **v1.3+ (future):** Word-twisting/authority study consuming v1.2 per-speaker structure (data-gated on the tagged RPG corpus); `--watch` mode; pure-Python MIME fallback; customer dictionaries; promotion of v1.1/v1.2 provisional fields to stable. Additive only — v1.0 contract holds.

## Commands

```bash
# Activate venv
source .venv/bin/activate

# Install in dev mode (editable)
pip install -e ".[dev]"

# Run file-observer (after install)
file-observer

# Run directly
python src/file_observer/scanner.py

# Run all tests
python -m pytest tests/

# Run a single test
python -m pytest tests/test_foo.py::test_name -v
```

## Architecture

Single-module implementation in `src/file_observer/scanner.py`, imported as `file_observer` (v1.0.1 rename). A deprecated `scanner` package re-exports the public API with a `DeprecationWarning` for backward compatibility. No deeper package structure yet — the conceptual modules (specialists, vectors) live in the one file until a change makes splitting them worthwhile.

### v0.3 Design Pillars
1. **Capability-locked determinism** — identical inputs + identical `ScanContext` → identical outputs. Variance across environments must be explained by context (dependency versions, logic version).
2. **Signal layering** — every field is raw (direct observation), derived (computed from raw via deterministic logic), or semantic-local (reserved, opt-in). Layer membership is a contract.
3. **Structured provenance** — every derived field has a `signal_provenance` entry with `layer`, `method`, `trigger`, optional `inputs` and `detail`. Replaces process_log entirely.
4. **Bounded observation** — specialists operate within `sample_size` (8KB default). Null means "not observed within bounds," not "not present in the file."

### Capability tiers (all in Scanner class)
1. **Universal** — runs for every file: identity, filesystem metadata, checksum, path-derived fields, routing flags (`is_binary`, `requires_vision`, `requires_specialist_tool`), MIME analysis, structural file signatures (`file_signature`, `format_signatures`, `is_polyglot`).
2. **Baseline** — runs for text-like files: encoding detection (with v0.7.1 UTF-16/UTF-32 BOM short-circuit), content preview, tag extraction, frontmatter parsing, asset matching. Runs `is_chatlog` content-based detection on `.txt`/`.md`/`.mdx`/`.jsonl`/`.json` files (v1.2: generalized conversational JSON/JSONL across role/content schemas; v1.2.1: markdown structure rules require a **speaker** co-signal; v1.2.2: prose speaker-label Rule 1 requires ≥2 distinct speakers AND ≥1 recurring speaker — kills header/label-block false positives). Runs `reference_tokens` extraction (7 subcategories) on all text-eligible files. Runs `filename_patterns` detection (6 subcategories) on every file. Detection runs even when `enable_specialists=False`.
3. **Structural** — runs for text-like files: title, headings, CSV headers, document keys (JSON/YAML/XML/TOML), technology hints, filename_date.
4. **Specialist** — gated behind `ScannerConfig.enable_specialists` (default: False). Format-specific extraction with namespaced metadata. v0.6 added MIME guard (skips extraction when content MIME doesn't match expected formats) and configurable depth (`specialist_budget`, `extension_overrides`, named profiles via `SCAN_PROFILES`). v0.7 added `safety_flags` (has_javascript, has_macros, has_ole_objects, has_external_references) and the `ScanQuality` block (clean/degraded/error/mismatch/polyglot/safety counts).

### Key data flow
`Scanner.scan()` → `_build_context()` → `iter_files()` walks directory → `scan_file()` per file (builds `FileRecord` + `signal_provenance` + `reference_tokens` + `filename_patterns`) → register file-scoped vectors (chatlog, reference_tokens, filename_patterns) → run corpus-scoped vectors (author_aggregate) → `_build_summary()` → assembled into `ScanManifest` with `context`, `meta`, `stats`, `quality`, `routing_summary`, `delta`, `vectors_collected`, `summary`, `manifest_checksum` → serialized via `manifest_to_json()`, `manifest_to_jsonl()`, and `manifest_to_markdown()`

### Core dataclasses
- `ScanContext` — environment fingerprint: logic version, scanner version, python version, platform, dependency versions
- `ProvenanceEntry` — per-field derivation record: layer, method, trigger, inputs, detail
- `VectorRecord` — one entry in `vectors_collected[]`: vector_id, method_version, scope, rules_hash, static_tuning_hash, identity_digest, applied_to_count, summary
- `VectorRegistry` — collects vectors during a scan, produces sorted `vectors_collected[]`
- `FileRecord` — one per discovered file, all fields from spec contract + `signal_provenance` + `reference_tokens` + `filename_patterns`
- `ScanManifest` — top-level output: `context`, `meta`, `stats`, `quality`, `routing_summary`, `delta`, `vectors_collected`, `summary`, `manifest_checksum`, `files[]`
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
| `.msg` | `email_envelope` | subject, from, to, date, message_id, has_attachments. v0.7.1: takes file path (not 8KB sample) so olefile can follow OLE2 FAT chains. v0.7.2: date read from MAPI properties stream (PR_CLIENT_SUBMIT_TIME 0x0039 → ISO 8601), `from` prefers PR_SENDER_NAME (0x0C1A) display name over PR_SENDER_EMAIL_ADDRESS (0x0C1F) Exchange legacyDN. |
| `.eml` | `email_envelope` | subject, from, to, date, message_id, has_attachments (stdlib email.parser) |
| `.xlsx` | `spreadsheet_structure` | sheet_names, header_rows, format=ooxml (stdlib zipfile + XML, 128KB deviation) |
| `.xls` | `spreadsheet_structure` | sheet_names, format=biff (BIFF8 BoundSheet8 records via olefile, v0.7.0). v0.7.1: takes file path. |
| `.docx` | `document_extraction` | title, author, word_count, heading_count (OOXML ZIP, 128KB deviation) |
| `.doc` | `document_extraction` | title, author (OLE2 SummaryInformation via olefile). v0.7.1: takes file path. |
| `.rtf` | `document_extraction` | title, author ({\info} group regex on sample) |
| `.jsonl` _(v0.10.1)_ | `chatlog_signals` | JSONL conversation detection via role-bearing JSON objects (`"type": "user"/"assistant"`). Message text extracted and processed through chatlog pipeline. |
| _(content-detected)_ | `chatlog_signals` | turn_count, speaker_labels, speaker_turn_counts/speaker_turn_chars/alternation (v1.2, provisional), section_marker_count/styles, turn char stats, reference_tokens, top_capitalized_tokens, vocabulary_size_estimate. Activates by content pattern on `.txt`/`.md`/`.mdx`/`.jsonl`/`.json` (v1.2: generalized conversational schemas). |

## Known decisions

- Specialist tier disabled by default (`ScannerConfig.enable_specialists = False`)
- Preview capped at 1000 chars (`ScannerConfig.preview_max_chars`)
- Binary detection: **v0.7.1 short-circuits on UTF-16/UTF-32 BOM** at offset 0 (treats as text), then NUL byte in sample OR MIME prefix/set OR text char ratio < 0.85
- MIME detection: content-based (python-magic/libmagic) primary, extension-based fallback with diagnostic error
- Encoding: chardet (confidence >= 0.50) then cascade: utf-8 → utf-8-sig → cp1252 → latin-1 → replace
- Manifest checksum excludes `scan_id` and `generated_at` (volatile fields)
- Manifest filename includes version: `manifest_v{VERSION}_{timestamp}.json`
- ScanContext excludes hostname and timestamps (not causally linked to outputs)
- Signal provenance replaces process_log — per-field, not per-tier
- Specialist tool names are semantic (describe downstream need, not scanner implementation)
- PDF sample_text_marker_density is a quantitative float, not qualitative labels
- PNG/JPEG extraction uses stdlib struct, not Pillow
- **OLE2 specialists (msg/doc/xls) take a file path, not a sample buffer** (v0.7.1) — olefile cannot follow FAT sector chains from a head-only buffer. Declared deviation from `sample_size`, bounded by file size on disk.
- **MSG date extraction parses the MAPI `__properties_version1.0` stream directly** (v0.7.2) — fixed-length properties (FILETIME) live there, not in substg streams. Reads PR_CLIENT_SUBMIT_TIME (0x0039) → ISO 8601, falls back to PR_MESSAGE_DELIVERY_TIME (0x0E06).
- **MSG `from` prefers display name (PR_SENDER_NAME 0x0C1A) over Exchange legacyDN (PR_SENDER_EMAIL_ADDRESS 0x0C1F)** (v0.7.2) — both kept in the lookup chain, but the human-readable form wins when present.
- EML extraction uses stdlib email.parser, no external dependencies
- XLSX/DOCX use 128KB deviation budget (declared exception to 8KB bounded observation)
- ZIP entries validated against path traversal (_is_safe_zip_entry), decompressed size capped at 1MB (_safe_zip_read)
- XML parsing uses defusedxml when available, stdlib fallback with documented risk
- v0.6 added `SCAN_PROFILES` (e.g. `fast_sort`) — named bundles of `extension_overrides` for common extraction depth tradeoffs
- v0.6 added `previous_manifest_checksum` and `manifest_signature` (HMAC-SHA256 with optional `signing_key`) for chain-of-custody integrity
- v0.7 added `safety_flags` (has_javascript / has_macros / has_ole_objects / has_external_references) and the `ScanQuality` block
- **`is_chatlog` is content-detected, not extension-driven** — activates for `.txt`/`.md`/`.mdx`/`.jsonl`/`.json`. Prose: speaker labels (stop-list filtered); H3 (5+) / dividers (3+) **require a co-signal** — 2+ speaker labels or 2+ date-stamped headers (v1.2, kills prose-doc false positives). JSON/JSONL (v1.2 generalized): 3+ "message-like" objects (a role key `type`/`role`/`from`/`speaker`/`author` + a content key `text`/`value`/`content`/`message`/`body`) — line-delimited, arrays, nested trees, or dialogue embedded in a JSON string; regex fallback for truncated large single-JSON. Detection runs even when `enable_specialists=False`.
- **v0.9 Vector abstraction** — vectors are named, uniquely-identified observation units with SHA-256 identity digests. Four vectors: chatlog, reference_tokens, author_aggregate, filename_patterns.
- **v0.10 Scan summary** — deterministic Markdown paragraph on every manifest + standalone `.md` report file.
- **v0.11 Field promotions** — vectors_collected, reference_tokens, per_directory_summary, email.body_chatlog, filename_patterns promoted from provisional to stable.
- **v1.0.1 package rename** — canonical import is `file_observer`; legacy `scanner` is a deprecated re-export shim (`DeprecationWarning`). The import path is NOT under the public contract (the manifest is), so the rename + packaging/positioning changes shipped as patches.
- **v1.1 Corpus Intelligence** — `quality.duplicate_clusters` (group by identical `checksum_sha256`, count ≥ 2) + `quality.specialist_stats` (per-tool attempted/succeeded/failed). Provisional; pure observation; no routing change.
- **v1.2 Chatlog generalized + hardened** — detection recognizes conversational JSON/JSONL across role/content schemas (`.json` candidate); per-speaker structure (provisional); `ErrorRecord.detail` added. Detection change → LOGIC 1.1.0, chatlog method_version 4. **v1.2.1/v1.2.2/v1.2.3 patches** tightened the FP rules (found by adversarial self-review + the empirical corpus sweep, cross-model reviewed): markdown structure needs a speaker co-signal; JSON needs ≥2 distinct speakers; prose Rule 1 needs ≥2 distinct + ≥1 recurring speaker; stop-list expanded (incl. FAQ `Question`/`Answer` in v1.2.3). Net: **LOGIC 1.1.4, method_version 8**. Open residual: prose `Key:value` (FAQ, tech-doc labels, i18n form fields) is ambiguous with dialogue, and the recurrence rule misses all-distinct multi-party openings — both need a future non-count signal, not more stop-list words. Word-twisting/authority study deferred (data-gated on tagged RPG corpus).

## Test fixtures

`tests/fixtures/` contains sample files across formats (.md, .pdf, .txt, .csv, .html, .yaml, .xlsx, .png, .docx, .rtf, .json, .mdx, .jpg). Chatlog fixtures in `tests/fixtures/edge_cases/`.

Test suite: 627 tests across `test_unit.py`, `test_integration.py`, `test_golden.py`, `test_edge_cases.py`, `test_packaging.py`, `test_v1_1.py`, `test_v1_2.py`, `test_v1_2_1.py`, `test_v1_2_2.py`, `test_v1_2_3.py`, `test_v1_2_4.py` (as of v1.2.4).
