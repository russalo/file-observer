# Scanner Version History

This is the running index of all scanner versions, their specifications, and their compliance reports. Use this as the entry point to find what was in any historical version.

**Current version:** see `pyproject.toml` and the latest entry below.

**How to read this index:**
- Active versions have specs and compliance reports in `docs/`
- Archived versions have specs and compliance reports in `docs/archive/` (introduced at v1.0)
- Pre-RFC versions (v0.1, v0.2) used different document conventions and are noted below

---

## Pre-1.0 Versions

| Version | Schema | Date | Notable | Spec | Compliance |
|---|---|---|---|---|---|
| 0.1.0 | n/a | 2026-04 | Initial three-tier architecture (Universal/Baseline/Specialist), MIME detection, encoding cascade | [SPEC.md](SPEC.md) | [COMPLIANCE.md](COMPLIANCE.md) |
| 0.2.0 | n/a | 2026-04 | Manifest metadata, stats, routing summary, JSONL output, .scannerignore, delta scanning, manifest checksum, MIME mismatch signaling, PDF specialist metadata, HTML/HTM support | [v0.2Spec.md](v0.2Spec.md) | [COMPLIANCE-v0.2.md](COMPLIANCE-v0.2.md) |
| 0.3.0 | 0.3 | 2026-04-08 | Capability-locked determinism (ScanContext), signal layering (raw/derived/semantic-local), structured signal_provenance, bounded observation mandate, PDF deepened, PNG IHDR, MSG envelope, XML/TOML support | [v0.3.0 RFC_Specification.md](v0.3.0%20RFC_Specification.md) | [COMPLIANCE-v0.3.md](COMPLIANCE-v0.3.md) |
| 0.4.0 | 0.4 | 2026-04-08 | Semantic specialist tool names, JPEG SOF specialist, EML specialist, XLSX specialist with 128KB deviation, MSG enrichment for EML parity, defusedxml hardening, ZIP entry validation | [v0.4.0_RFC_Specification.md](v0.4.0_RFC_Specification.md) | _(no compliance report)_ |
| 0.4.1 | 0.4 | 2026-04-08 | Document envelope floor: DOCX (title, author, word_count, heading_count), DOC (olefile), RTF ({\info} regex). Module docstring with version tracking. | _(part of v0.4)_ | _(part of v0.4)_ |
| 0.5.0 | 0.5 | 2026-04-08 | Schema reshaping: schema_version field, namespaced specialist_metadata (pdf/image/email/spreadsheet/document), baseline_max_bytes config, CRLF cross-platform handling, as_posix() path normalization, ZIP traversal hardening, XML/TOML parse failure recording | [v0.5.0_RFC_Specification.md](v0.5.0_RFC_Specification.md) | [COMPLIANCE-v0.5.md](COMPLIANCE-v0.5.md) |
| 0.6.0 | 0.6 | 2026-04-09 | Configurable extraction depth (specialist_budget, extension_overrides, named profiles), structural file signatures (file_signature, format_signatures, is_polyglot), specialist MIME guard, integrity envelope (previous_manifest_checksum, manifest_signature HMAC-SHA256) | [v0.6.0_RFC_Specification.md](v0.6.0_RFC_Specification.md) | [COMPLIANCE-v0.6.md](COMPLIANCE-v0.6.md) |
| 0.7.0 | 0.7 | 2026-04-10 | XLS specialist (BIFF8 BoundSheet8 parsing), spreadsheet format field (biff/ooxml), safety_flags (has_javascript/has_macros/has_ole_objects/has_external_references), ScanQuality block (clean/degraded/error/mismatch/polyglot/safety counts) | [v0.7.0_RFC_Specification.md](v0.7.0_RFC_Specification.md) | _(no compliance report)_ |
| 0.7.1 | 0.7 | 2026-04-10 | **Patch release.** UTF-16/UTF-32 BOM detection in `detect_binary` (UTF-16 text files were being routed to binary_only because of interleaved NULs in UTF-16 ASCII content). OLE2 specialists (`.msg`, `.doc`, `.xls`) now receive the file path instead of the 8KB sample buffer — olefile cannot follow FAT sector chains from a head-only buffer, so all three were 100% failing on real-world files. Both bugs found from real-world corpus scanning. LOGIC_VERSION bumped (routing changes for UTF-16 text; extraction succeeds where it previously failed). | _(part of v0.7)_ | _(part of v0.7)_ |
| 0.7.2 | 0.7 | 2026-04-10 | **Patch release.** Two MSG specialist bugs found from the v0.7.1 patched rescan. (1) `date` field was 0% populated — the code read property `0x0047` as a string substg, but fixed-length properties like FILETIME live in the MAPI properties stream (`__properties_version1.0`), not in substg streams. New MAPI parser walks the 16-byte property entries and reads `PR_CLIENT_SUBMIT_TIME` (`0x0039`, `PT_SYSTIME`), with fallback to `PR_MESSAGE_DELIVERY_TIME` (`0x0E06`); converts the Windows FILETIME to ISO 8601. The bug had been silently broken since the date field was added in v0.4. (2) `from` field returned the Exchange legacyDN for all Exchange-sourced messages; reorder the lookup chain to prefer `PR_SENDER_NAME` (`0x0C1A`, always a display name string) over `PR_SENDER_EMAIL_ADDRESS` (`0x0C1F`). LOGIC_VERSION bumped (date field changes from null to a real value for every msg). | _(part of v0.7)_ | _(part of v0.7)_ |
| 0.8.0 | 0.8 | 2026-04-10 | Chatlog specialist (first content-detected, not extension-based): `is_chatlog` flag detection runs even when specialists disabled; `_extract_chatlog_metadata` produces all 11 fields (turn_count, speaker_labels, section_marker_count/styles, avg/max/min_turn_chars, reference_tokens, top_capitalized_tokens, capitalized_token_count, vocabulary_size_estimate); per-field signal_provenance with `bounded_text` trigger; `quality.chatlog_files` counter; new `chatlog` namespace in SPECIALIST_MIME_GUARD; CHATLOG_NAMESPACE / CHATLOG_TOOL module constants; 3 fixture files in `tests/fixtures/edge_cases/`. SCHEMA_VERSION 0.7 → 0.8 (additive). | [v0.8.0_RFC_Specification.md](v0.8.0_RFC_Specification.md) | [COMPLIANCE-v0.8.md](COMPLIANCE-v0.8.md) |
| 0.9.2 | 0.9 | 2026-05-27 | **Patch release.** reference_tokens path regex tightened — added negative lookbehind to exclude URL-embedded path fragments. Self-scan path_references dropped from 32K to near-actual counts. 98.6% of previous hits were URL fragments in JSON files (Google API OAuth scopes). `reference_tokens` method_version 1 → 2. LOGIC_VERSION unchanged. | _(part of v0.9)_ | _(part of v0.9)_ |
| 0.9.1 | 0.9 | 2026-05-27 | **Patch release.** Chatlog vector tuning from 6-corpus validation: (1) H3 header detection threshold raised from 3 to 5 — reduces false positives on documentation-heavy repos (FastAPI: 519 → 387, -25%). (2) Speaker label stop-list added — common doc patterns (`Note:`, `Example:`, `Result:`, `Disallow:`, etc.) no longer count as conversation participants. Both changes bump `method_version` 1 → 2; identity digest changes accordingly. LOGIC_VERSION unchanged (no routing changes). | _(part of v0.9)_ | _(part of v0.9)_ |
| 0.9.0 | 0.9 | 2026-05-27 | **Vector abstraction** — the scanner becomes a corpus observer. `Vector` dataclass with identity digest (SHA-256 over vector_id + method_version + rules_hash + static_tuning_hash + reserved fields). New `vectors_collected[]` top-level manifest block. Two exemplar vectors: `chatlog` (refactored from v0.8, content-gated) and `reference_tokens` (new, unconditional, 7 subcategories). `reference_tokens` per-file field on all text files. Email body chatlog cross-cut (`specialist_metadata.email.body_chatlog`). Per-directory aggregation (`quality.per_directory_summary[]`). Dublin Core graduated to Adopted tier in STANDARDS_TRACKING — first standards promotion. All v0.9 additions provisional (§2.4). Validated against 6 corpora / 18K+ files. SCHEMA_VERSION 0.8 → 0.9 (additive). | [v0.9.0_RFC_Specification.md](v0.9.0_RFC_Specification.md) | _(pending)_ |
| 0.10.1 | 0.10 | 2026-05-27 | **Patch release.** JSONL chatlog detection — `.jsonl` files with role-bearing JSON objects (`"type": "user"/"assistant"`) now trigger chatlog detection (rule 4). Message text extracted from JSONL structure and processed through existing chatlog extraction pipeline. `.jsonl` added to SUPPORTED_EXTENSIONS and REFERENCE_TOKENS_EXTENSIONS. Chatlog method_version 2 → 3. LOGIC_VERSION bumped (routing change: `.jsonl` files now get chatlog detection). | _(part of v0.10)_ | _(part of v0.10)_ |
| 0.10.0 | 0.10 | 2026-05-27 | Human-readable scan summary (`summary` field — deterministic Markdown paragraph on every manifest). `author_aggregate` corpus vector (cross-specialist author normalization, template-default candidate detection). `filename_patterns` vector (6 boolean subcategories on every file: date_prefix, version_marker, numbered_revision, template_name, uuid_filename, copy_suffix). Four vectors now in `vectors_collected[]`. Validated against Tika (64 authors found, 84 filename pattern hits). SCHEMA_VERSION 0.9 → 0.10 (additive). | [v0.10.0_RFC_Specification.md](v0.10.0_RFC_Specification.md) | _(pending)_ |

---

## Drafts in Flight

| Version | Status | Notes | File |
|---|---|---|---|
| 1.0.0 | Forward-looking | Schema freeze + backward compatibility policy. Becomes binding when scanner reaches maturity (see scanner version policy in CLAUDE.md). | [v1.0.0_RFC_DRAFT.md](v1.0.0_RFC_DRAFT.md) |

---

## Historical Drafts and Design Documents

These are working documents from earlier in the project. Kept for design history; not specifications themselves.

| File | Era | Purpose |
|---|---|---|
| [v0.3_DESIGN_GOALS.md](v0.3_DESIGN_GOALS.md) | Pre-v0.3 | Initial design goals that became the v0.3 RFC |
| [v0.3SpecDRAFT.md](v0.3SpecDRAFT.md) | Pre-v0.3 | First candidate draft for v0.3 (before final RFC) |
| [Gem_v0.3SpecDRAFT.md](Gem_v0.3SpecDRAFT.md) | Pre-v0.3 | Alternate candidate draft for v0.3 |

---

## Compliance Report Gaps

We have known gaps in compliance reports:

- **v0.4.0** — no compliance report exists. v0.4 shipped before the per-version compliance discipline was fully established.
- **v0.7.0** — no compliance report exists. Slipped during the v0.7 release cycle.

These gaps are acknowledged but **not** scheduled for backfill. They are evidence of when the per-version discipline was still forming, and retrofitting them would obscure how the project actually matured. The CONVENTIONS.md release checklist now includes a compliance report as a per-minor-version requirement to prevent future gaps.

## On the Muddle

Pre-1.0 history is messy, inconsistent, and reflects a project figuring itself out. The naming conventions changed (v0.1 used `SPEC.md`, v0.2 used `v0.2Spec.md`, v0.3+ used `v{X}.0_RFC_Specification.md`). The compliance discipline was uneven. The schema was reshaped twice before stabilizing at v0.5. v1.0 was prematurely declared and walked back. Personal files lived in fixtures for five versions before being sanitized.

This is not retroactively cleaned up. It's left as it actually happened. The muddle *is* the history.

---

## Archival Policy

**Pre-v1.0:** Nothing is archived. All specs and compliance reports remain in `docs/`. This is intentional — pre-v1.0 history is small and often referenced as we iterate.

**At v1.0:** All v0.x specs and compliance reports move to `docs/archive/0.x/`. This index updates to point to the archive locations. Current working files in `docs/` shrink to: current version's spec + compliance, the three companion documents (CONVENTIONS, PUBLIC_CONTRACT, STANDARDS_TRACKING), README, this HISTORY file, and the historical pre-RFC documents (SPEC.md, v0.2Spec.md, COMPLIANCE.md).

**Post-v1.0:** When v2.0 ships (if ever), v1.x moves to `docs/archive/1.x/`. Same pattern.

**Drafts that never get promoted:** Stay in their location (or move to `scratch/` if they should never have been in `docs/`). They are not deleted — they document considered alternatives.

---

## Version Constants Reference

For each version, the corresponding code constants:

| Version | SCANNER_VERSION | LOGIC_VERSION | SCHEMA_VERSION |
|---|---|---|---|
| 0.3.0 | 0.3.0 | 0.3.0 | 0.3 |
| 0.4.0 | 0.4.0 | 0.4.0 | 0.4 |
| 0.4.1 | 0.4.1 | 0.4.0 | 0.4 |
| 0.5.0 | 0.5.0 | 0.5.0 | 0.5 |
| 0.6.0 | 0.6.0 | 0.6.0 | 0.6 |
| 0.7.0 | 0.7.0 | 0.7.0 | 0.7 |
| 0.7.1 | 0.7.1 | 0.7.1 | 0.7 |
| 0.7.2 | 0.7.2 | 0.7.2 | 0.7 |
| 0.8.0 | 0.8.0 | 0.8.0 | 0.8 |

---

## When This Document Updates

- New version released → add a row to "Pre-1.0 Versions" or post-1.0 section
- Draft promoted to spec → move from "Drafts in Flight" to a version row
- Compliance gap filled → update the gap section
- v1.0 ships → move v0.x specs to `docs/archive/0.x/` and update the link paths in this file
