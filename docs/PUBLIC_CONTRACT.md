# File Observer Public Contract

This document defines what **consumers** of the File Observer manifest can rely on. It is the stability commitment from File Observer to downstream systems (ingestors, BI tools, classifiers, audit pipelines).

> **This contract is binding as of v1.0.** The stability commitments below are obligations, not intentions. Fields marked stable will not be removed, renamed, or change type without a MAJOR version bump (v2.0). See the backward compatibility and deprecation policies below.

---

## 1. What Consumers Can Count On

### 1.1 Schema Version

Every manifest includes a top-level `schema_version` field in the format `MAJOR.MINOR`.

**Stability rules (post-v1.0):**

- **MINOR bumps are additive only.** New fields may appear. Existing fields will not be removed, renamed, or change type.
- **MAJOR bumps are reserved for breaking changes** and require an explicit migration path. A MAJOR bump will be preceded by at least one full MINOR version of deprecation warnings on affected fields.
- **Consumers should branch on the MAJOR version.** Code written for schema 1.x will continue to work with schema 1.y where y > x. Code written for schema 1.x is not guaranteed to work with schema 2.0.

**Pre-v1.0 reality:**
- Schema can still change in any minor version
- Each schema bump is documented in the corresponding RFC
- Migration guidance is provided in commit messages and compliance reports

### 1.2 Manifest Top-Level Structure

Every manifest contains these top-level keys (post-v1.0):

| Key | Type | Stability |
|---|---|---|
| `schema_version` | string | **Stable** — always present |
| `context` | object | **Stable** — fields may be added in MINOR bumps |
| `meta` | object | **Stable** — `scan_id` and `generated_at` excluded from `manifest_checksum` |
| `stats` | object | **Stable** |
| `quality` | object | **Stable** (since 0.7) |
| `routing_summary` | object | **Stable** |
| `delta` | object or null | **Stable** — null when no previous manifest |
| `manifest_checksum` | string (sha256 hex) | **Stable** — deterministic over the manifest content |
| `manifest_signature` | object or null | **Stable** — null when signing not configured |
| `files` | array | **Stable** — sorted by path |
| `vectors_collected` | array | **Stable** (since 0.9, promoted 0.11) — one entry per vector that ran; sorted by vector_id |
| `summary` | string | **Stable** (since 0.10) — deterministic Markdown, included in checksum |

### 1.3 FileRecord Structure

Every entry in `files` has these stable fields:

| Field | Type | Stability |
|---|---|---|
| `path` | string (forward slashes) | **Stable** |
| `filename` | string | **Stable** |
| `extension` | string (lowercase) | **Stable** |
| `mime_type` | string | **Stable** |
| `size_bytes` | int | **Stable** |
| `created_at` | string or null | **Stable** — null on platforms without `st_birthtime` |
| `modified_at` | string (ISO-8601 UTC) | **Stable** |
| `checksum_sha256` | string (sha256 hex) | **Stable** |
| `is_binary` | bool | **Stable** |
| `requires_vision` | bool | **Stable** |
| `requires_specialist_tool` | bool | **Stable** |
| `specialist_tool` | string or null | **Stable** — semantic name (see specialist tool registry below) |
| `mime_analysis` | object | **Stable** |
| `specialist_metadata` | object or null | **Stable shape** — fields by namespace; namespace keys stable |
| `signal_provenance` | object | **Stable** — keys are field paths, values are provenance entries |
| `safety_flags` | array of strings | **Stable** (since 0.7) — flag tokens stable, additions in MINOR |
| `is_chatlog` | bool | **Stable** (since 0.8) — always present; true when content detection rules match |
| `reference_tokens` | object or null | **Stable** (since 0.9, promoted 0.11) — seven subcategory counts on text files; null on binary |
| `filename_patterns` | object | **Stable** (since 0.10, promoted 0.11) — six boolean subcategories on every file |
| `stage_folder` | string | **Stable** — first path component (top-level "stage" folder); `""` when the file is at the scan root |
| `directory_depth` | int | **Stable** — directory depth below the scan root |
| `sidecar_exists` | bool | **Stable** — a sidecar/companion file was detected next to this one |
| `encoding` | string or null | **Stable** — detected text encoding; null on binary |
| `content_preview` | string or null | **Stable** — capped text preview (text-eligible files); null on binary |
| `tags` | array of strings | **Stable** — extracted inline tags |
| `asset_matches` | array of strings | **Stable** — matched asset/companion references |
| `frontmatter` | object | **Stable shape** — markdown frontmatter (`exists`/`keys`/`raw`) |
| `structural` | object | **Stable shape** — structural signals (`title`/`heading_structure`/`csv_headers`/`document_keys`/`technology_hints`/`filename_date`) |
| `preservation` | object | **Provisional** (since v1.10) — `format_obsolescence` (`current`/`at_risk`/`obsolete`) + `migration_recommended` (bool), from a closed obsolescence table |
| `errors` | array of objects | **Stable** — error codes stable (see error code registry); `errors[].detail` is **Stable** (since 1.2, promoted 1.10) |

### 1.4 Specialist Metadata Namespaces

`specialist_metadata` is keyed by **namespace**, not by extension. Multiple extensions may map to the same namespace.

| Namespace | Stability | Source extensions |
|---|---|---|
| `pdf` | Stable since 0.5 | `.pdf` |
| `image` | Stable since 0.5 | `.png`, `.jpg`, `.jpeg`, `.heic`, `.heif`, `.avif` (HEIC routed + EXIF added v1.16) |
| `video` | Since 1.17 (namespace additive) | `.mp4`, `.mov`, `.m4v` |
| `email` | Stable since 0.5 | `.msg`, `.eml` |
| `spreadsheet` | Stable since 0.5 | `.xlsx`, `.xls` |
| `document` | Stable since 0.5 | `.docx`, `.doc`, `.rtf`. Dublin Core alignment (since 0.9): `document.title` corresponds to `dc:title`, `document.author` corresponds to `dc:creator`. |
| `chatlog` | Stable since 0.8 | Content-detected in `.txt`, `.md`, `.mdx`, `.jsonl`, `.json` — not extension-driven |

**Rules:**
- Namespace keys will not be removed or renamed in MINOR releases
- New namespaces may be added in MINOR releases (additive)
- Fields *within* a namespace will not be removed or renamed in MINOR releases
- New fields *within* a namespace may be added in MINOR releases
- A field value of `null` means "not observed within bounded extraction limits" — NOT "not present in the file"

### 1.5 Specialist Tool Names (Routing Hints)

The `specialist_tool` field uses semantic names that describe **what kind of downstream processing the file needs**, not which scanner internal extracted from it.

| Tool name | Files routed to it |
|---|---|
| `pdf_extraction` | `.pdf` |
| `image_structure` | `.png`, `.jpg`, `.jpeg`, `.heic`, `.heif`, `.avif` |
| `video_structure` | `.mp4`, `.mov`, `.m4v` (since 1.17) |
| `email_envelope` | `.msg`, `.eml` |
| `spreadsheet_structure` | `.xlsx`, `.xls` |
| `document_extraction` | `.docx`, `.doc`, `.rtf` |
| `chatlog_signals` | Content-detected in `.txt`, `.md`, `.mdx`, `.jsonl`, `.json` (not extension-driven) |

**Stability:** Tool names will not change without a MAJOR schema bump. New tool names may be added for new file types in MINOR releases.

### 1.6 Error Codes

The `errors` array on each FileRecord contains entries with stable `code` values:

| Code | Stage | Meaning |
|---|---|---|
| `universal_stat_failed` | universal | File could not be stat'd |
| `unsupported_extension` | universal | Could not identify the file — its extension isn't in the supported set AND its content isn't recognized as text (content-aware since v1.21; previously "extension not in supported set"). |
| `mime_type_fallback` | universal | Content-based MIME unavailable, used extension fallback |
| `baseline_decode_failed` | baseline | Text decoding raised an exception |
| `specialist_probe_failed` | specialist | Specialist returned null or raised an exception |
| `json_parse_failed` | specialist | JSON validation failed (when specialists enabled) |
| `xml_parse_failed` | structural | XML parser raised on full file content |
| `toml_parse_failed` | structural | TOML parser raised on full file content |

**Stability:** Error codes are stable. New codes may be added in MINOR releases. Codes will not be removed or renamed without a MAJOR bump.

### 1.7 Safety Flags

The `safety_flags` array contains stable string tokens. Each token represents an observable structural indicator — not a threat assessment.

| Flag | Source | Meaning |
|---|---|---|
| `has_javascript` | PDF sample | PDF contains `/JS` or `/JavaScript` markers |
| `has_macros` | DOCX ZIP entries | DOCX contains `vbaProject.bin` (requires `enable_specialists`) |
| `has_ole_objects` | RTF sample | RTF contains `\objemb` or `\objlink` |
| `has_external_references` | XML sample | XML contains `<!ENTITY` with `SYSTEM` or `PUBLIC` |
| `geotagged` | image EXIF / video container (v1.16 image, v1.18 video) | The file carries location metadata — image EXIF GPS-IFD pointer, or a video ISO-6709 location box. **Presence only — coordinates are NOT extracted.** |
| `extraction_permission_bypassed` | PDF pypdf cascade (v1.12) | Owner-permission-locked encrypted PDF: the primary `EXTRACT` bit (ISO 32000 Table 22, `UserAccessPermissions.EXTRACT`) was NOT set in `user_access_permissions` but file-observer extracted metadata anyway (observe-with-disclosure — file-observer reads metadata regardless of permission flags; this token records when the owner's extract-restriction was bypassed). Requires the `[pdf]` extra (now includes `cryptography`). |

**Important:**
- Flags report **structural indicators**, not interpretations. The scanner does not decide whether a file is dangerous — it reports what's in the bytes.
- A flag's presence does not mean the content is malicious. Consumers must apply their own threat model.
- New flags may be added in MINOR releases. Existing flag tokens are stable.

### 1.8 Manifest Checksum

The `manifest_checksum` field is a SHA-256 hex digest computed over a canonical serialization of the manifest with the following fields zeroed out:

- `manifest_checksum` itself (treated as empty string)
- `manifest_signature` (treated as null)
- `meta.scan_id`
- `meta.generated_at`

**Properties:**
- Deterministic for identical inputs and identical scanner context
- Changes when ANY observable signal changes
- Stable across re-runs of the same scanner version on the same files

### 1.9 Manifest Signature (Optional)

When the operator configures a signing key, the manifest includes a `manifest_signature` object:

```json
{
  "algorithm": "hmac-sha256",
  "key_id": "scanner-prod-2026",
  "value": "hex..."
}
```

**Properties:**
- Computed over `manifest_checksum`
- Excluded from the checksum preimage (otherwise circular)
- `null` when no signing key is configured
- Deterministic for the same checksum and key

### 1.10 Chain of Custody

When delta scanning is enabled, `delta.previous_manifest_checksum` contains the checksum of the previous manifest. This allows consumers to verify a chain of scans:

```
Scan N's delta.previous_manifest_checksum == Scan N-1's manifest_checksum
```

A break in the chain indicates a missed scan or tampering.

### 1.11 Re-ingest worklist (`delta.rescan_candidates`)

When delta scanning is enabled, `delta.rescan_candidates` is a **sorted list of
paths** that (a) still exist in the current scan and (b) had a specialist
extraction failure (`specialist_probe_failed`) in the **previous** manifest. It is
the **re-ingest worklist**: the files a downstream consumer should re-process —
for example after a File Observer upgrade that may now extract a format the prior
version couldn't, or after fixing a corrupt source. It carries no opinion on *why*
the prior attempt failed (the per-file `errors` hold that); it only points at what
is worth another look. Empty when there is no previous manifest or nothing
previously failed. Stable as part of the `delta` object.

---

## 2. What Consumers Should NOT Rely On

### 2.1 Field Order in JSON

The scanner produces JSON with deterministic key ordering for checksum purposes, but consumers should parse by key name, not position. Field order is not part of the public contract.

### 2.2 Specific Provenance Trigger Strings

`signal_provenance` entries contain `trigger` values like `"libmagic"`, `"chardet_confident"`, `"nul_byte"`. These are stable within a `LOGIC_VERSION` but may be added or refined as the scanner's logic evolves.

**Consumers should:**
- Treat trigger strings as opaque tokens
- Branch on `layer` (`raw`, `derived`) for the stable categorization
- Use trigger strings for human-readable diagnostics and logs

### 2.3 LOGIC_VERSION Specific Values

The `context.logic_version` field tells consumers *that* the routing logic has a particular version, not what behavior to expect. Two scanner releases may have the same LOGIC_VERSION if no routing logic changed between them.

**Consumers should:**
- Use LOGIC_VERSION to detect "did the routing logic change between scans?"
- Not assume specific behavior based on a specific value

### 2.4 Internal Field Sets

These fields exist in the manifest but are subject to change in MINOR releases without notice:

- `format_signatures` — internal magic signature scan results
- `is_polyglot` — derived from format_signatures
- `specialist_metadata.chatlog.speaker_turn_counts`, `.speaker_turn_chars`, `.alternation` — per-speaker turn structure (provisional since v1.2)
- `specialist_metadata.chatlog.content_shape` (`.utterance_ratio`, `.density`) — content-shape detection signals; null in JSONL mode (provisional since v1.4)
- `preservation` (top-level on every `FileRecord`; `.format_obsolescence`: `current`/`at_risk`/`obsolete`; `.migration_recommended`: bool) — per-file format-preservation signal from a **closed obsolescence table** (provisional since v1.10). Same scope as `filename_patterns` — not under `specialist_metadata`.
- `specialist_metadata.image` EXIF fields — `make`, `model`, `orientation`, `datetime_original`, `gps_present`, `xmp_present` (provisional since v1.21.1; added v1.16). The older image dimensions (`width`, `height`, `bit_depth`) remain **stable** (since 0.5).
- `specialist_metadata.video.*` — the entire `video` namespace (`codec`, `duration_s`, `width`, `height`, `creation_date`, `creation_date_qt`, `make`, `model`, `gps_present`, `gps_source`) is **provisional** (since v1.21.1; the namespace is recent — v1.17–1.20). The `video` namespace *key* is additive-stable (§1.4); its fields are provisional pending a promotion pass.

**Promoted to stable in v1.14** (now under the backward-compat policy — not removable/retypable without a MAJOR bump): `specialist_metadata.pdf.parser` (`pypdf`/`stdlib`/`none` decode tier — the PDF arc completed at v1.12; its value records which tier ran and is independent of any future `/Info` extraction), `specialist_metadata.{document,spreadsheet}.application` (producing application; OOXML + OLE2), and the `vectors_collected[]` `provenance` vector (shape `toolchains`/`production_years`/`digitization` — stable; the closed toolchain table may still grow additively, rules-hash-tracked). As of v1.14, `file-observer --schema` annotates every field/vector with its `stability` (`stable`/`provisional`).

**Promoted to stable in v1.10** (now under the backward-compat policy — not removable/retypable without a MAJOR bump): `quality.duplicate_clusters` / `duplicate_cluster_count` / `redundant_file_count`, `quality.specialist_stats`, `errors[].detail`, `specialist_metadata.pdf.text_detected`, `specialist_metadata.pdf.xref_type`.

**Candidate tier (below provisional, v1.10):** some observations (CAD coverage, image EXIF, word-twisting provenance) are tracked + measured in the review apparatus but are **NOT in the manifest** at all — they carry no contract status until promoted to provisional. The ladder is `candidate → provisional → stable`; see `CONVENTIONS.md`.

The following were promoted to stable in v0.11: `vectors_collected[]`, `reference_tokens`, `quality.per_directory_summary[]`, `specialist_metadata.email.body_chatlog`, `filename_patterns`.

These fields are useful but not yet stabilized. Treat them as informational until they're explicitly listed as stable here.

### 2.5 Scratch Notes and Draft Specs

Files in `scratch/` and any document with `_DRAFT` in the filename are not commitments. They represent work in progress and may be revised, deleted, or restructured.

---

## 3. Schema Version History

| Schema Version | Scanner Version | Major changes |
|---|---|---|
| `0.5` | 0.5.0 | Namespaced specialist_metadata, schema_version field, baseline_max_bytes |
| `0.6` | 0.6.0 | Configurable depth, file_signature, format_signatures, is_polyglot, manifest_signature, previous_manifest_checksum |
| `0.7` | 0.7.0 | XLS specialist, safety_flags, quality block |
| `0.8` | 0.8.0 | Chatlog specialist (first content-detected dispatch), `is_chatlog` FileRecord flag, `chatlog` namespace, `chatlog_signals` tool, `quality.chatlog_files` counter |
| `0.9` | 0.9.0 | Vector abstraction (`vectors_collected[]`), `reference_tokens` per-file field, `quality.per_directory_summary[]`, `specialist_metadata.email.body_chatlog` cross-cut, Dublin Core adopted. All v0.9 additions provisional. |
| `0.10` | 0.10.0 | Human-readable `summary` field (stable). `author_aggregate` corpus vector. `filename_patterns` per-file field (6 booleans). |
| `0.11` | 0.11.0 | Provisional → stable promotions: `vectors_collected[]`, `reference_tokens`, `quality.per_directory_summary[]`, `specialist_metadata.email.body_chatlog`, `filename_patterns`. SECURITY.md added. No new fields. |
| `1.0` | 1.0.0 | Schema freeze. Public contract binding. Backward compatibility policy in effect. No new fields — governance only. |
| `1.1` | 1.1.0 | Corpus Intelligence (additive): `quality.duplicate_clusters` (+ `duplicate_cluster_count`, `redundant_file_count`) and `quality.specialist_stats`. Both provisional (§2.4). First additive release after the freeze — no existing field changed; `LOGIC_VERSION` unchanged. |
| `1.2` | 1.2.0 | Chatlog generalized & hardened: detection recognizes conversational JSON/JSONL beyond `type:user/assistant` (ConvoKit/ShareGPT/oasst/hh-rlhf schemas; `.json` candidate); markdown false positives cut ~96% (structure now needs a speaker/date co-signal); per-speaker structure added (`speaker_turn_counts`/`speaker_turn_chars`/`alternation`, provisional); `errors[].detail` added. Detection behavior changed → `LOGIC_VERSION` 1.0.0→1.1.0, chatlog `method_version` 3→4. Additive schema. |
| `1.3` | 1.4.0 | Content-shape chatlog detection gate (additive): `specialist_metadata.chatlog.content_shape` (`utterance_ratio`/`density`, provisional; null in JSONL mode). Detection refined — a content-shape gate over the retained stop-list rejects cyclic data tables / FAQs / changelogs while admitting terse dialogue via a function-word arm. `LOGIC_VERSION` 1.2.0→1.3.0; chatlog `method_version` 8→9. No existing field changed/removed/retyped. |
| `1.4` | 1.5.0 | PDF specialist head+tail read (additive): `specialist_metadata.pdf.text_detected` (bool, provisional). `page_count`/`producer` now reliably populated (read from the trailer, not just the 8 KB head). `requires_vision` for PDFs is refined — born-digital PDFs with compressed content streams are no longer mis-flagged as needing vision (`LOGIC_VERSION` 1.3.0→1.4.0). Object-stream PDFs (PDF 1.5+) return `page_count=None` (honest null). No existing field changed/removed/retyped. |
| `1.5` | 1.6.0 | Production-provenance dimension (additive): a corpus-scoped `provenance` vector in `vectors_collected[]` (normalized `toolchains`, `production_years`, `digitization`; provisional), plus an additive `application` field on docx/xlsx specialist metadata. Pure aggregation — `LOGIC_VERSION` unchanged (1.4.0). No existing field changed/removed/retyped. |
| `1.6` | 1.7.0 | Structural-anchor PDF reader (additive): `specialist_metadata.pdf.xref_type` (`classic`/`stream`/`none`, provisional) — the structural observable. `page_count`/`/Info` are now read by following the PDF's index (`startxref` → trailer → root → page tree, parsing the xref table + `/Prev`) — precise on incremental updates and > 64 MB files; on the corpus, identical values to v1.5 (zero regression). Specialist extraction only — `LOGIC_VERSION` unchanged (1.4.0). No existing field changed/removed/retyped. |
| `1.13` | 1.21.1 | **Provisional-designation correction, schema unchanged (patch).** The v1.16 image-EXIF fields (`make`/`model`/`orientation`/`datetime_original`/`gps_present`/`xmp_present`) and the entire v1.17–1.20 `video` namespace are corrected from STABLE to **provisional** in `--schema` — they had emitted stable only because of an intake-registry oversight (recent fields should be provisional, the data-gathering tier, pending a promotion pass). Manifest **byte-identical** (stability lives only in `--schema`, not the manifest); `LOGIC_VERSION`/`SCHEMA_VERSION` unchanged (1.11.0 / 1.13). The old image dimensions (`width`/`height`/`bit_depth`) stay stable. No existing field changed/removed/retyped — only a stability *promise level* corrected (a weakening that's safe here: these were never enumerated stable in the binding contract, and no consumer depended on the annotation yet). |
| `1.13` | 1.21.0 | **Content-aware text recognition, schema unchanged.** `unsupported_extension` no longer fires when a file's CONTENT is recognized as text (`text/*` or a known structured-text application type, or `inode/x-empty`), even if the extension isn't listed — the diagnostic now means "couldn't identify it," not "extension not in our list." Recognition gates on content (a content-derived MIME + printable-ratio/BOM), never the extension-fallback MIME. Recognition only — no new field, no new extraction; `supported`/`degraded` counters shift for text-with-unlisted-extension. `LOGIC_VERSION` 1.10.0→1.11.0. No existing field changed/removed/retyped. |
| `1.13` | 1.20.0 | **Video QuickTime creation date (additive):** `specialist_metadata.video.creation_date_qt` — the Apple `com.apple.quicktime.creationdate` key (capture moment WITH timezone), kept SEPARATE from `video.creation_date` (mvhd/UTC); never reconciled (observe-don't-interpret). `LOGIC_VERSION` 1.9.0→1.10.0. `SCHEMA_VERSION` 1.12→1.13 (a new field). No existing field changed/removed/retyped. |
| `1.12` | 1.19.0 | **Human-readable surfaces refresh, schema unchanged.** The per-scan human `summary` string is freshened (names the `provenance` vector, adds a Capture line, named safety flags, preservation, content-vs-extension/polyglot ambiguity comments) + a new `--schema --format summary` prose surface. The `summary` string feeds `manifest_checksum`, so its text changes → `LOGIC_VERSION` 1.8.0→1.9.0. No machine field changed/removed/retyped (the summary remains a human-readable string). |
| `1.12` | 1.18.0 | **Video capture device + GPS-presence (additive):** `specialist_metadata.video` gains `make`/`model` (Apple QuickTime keys) + `gps_present`/`gps_source` (ISO-6709 location box — presence + mechanism, NOT coordinates) → the `geotagged` safety flag now fires for video too. `LOGIC_VERSION` 1.7.0→1.8.0. `SCHEMA_VERSION` 1.11→1.12 (new fields). No existing field changed/removed/retyped. |
| `1.11` | 1.17.0 | **Video container metadata (additive):** new `video` specialist namespace (`.mp4`/`.mov`/`.m4v` → `video_structure`) with `codec`/`duration_s`/`width`/`height`/`creation_date` (ISOBMFF container, stdlib). `LOGIC_VERSION` 1.6.0→1.7.0. `SCHEMA_VERSION` 1.10→1.11 (new namespace). No existing field changed/removed/retyped. |
| `1.10` | 1.16.0 | **Image capture-metadata (additive):** the `image` specialist gains EXIF — `make`/`model`/`orientation`/`datetime_original`/`gps_present` (GPS-PRESENCE, NOT coordinates)/`xmp_present` for JPEG & HEIC (`.heic`/`.heif`/`.avif` now route to the image specialist with extraction). New `geotagged` safety flag when GPS is present. `LOGIC_VERSION` 1.5.2→1.6.0. `SCHEMA_VERSION` 1.9→1.10 (new fields + safety flag). No existing field changed/removed/retyped. |
| `1.9` | 1.15.2 | **MIME-guard hardening, schema unchanged (patch).** A generic OLE2 office MIME (`application/vnd.ms-office`) is accepted by the `document`/`spreadsheet` guards; the `.eml` email specialist runs on the no-libmagic path (a curated extension-trusted MIME, gated by the specific MIME + a non-empty read). `LOGIC_VERSION` 1.5.1→1.5.2 (extraction-dispatch change). No existing field changed/removed/retyped. |
| `1.9` | 1.15.1 | **HEIC/HEIF/AVIF recognition, schema unchanged (patch).** `.heic`/`.heif`/`.avif` added to the recognized extension set (no longer flagged `unsupported_extension`) with registered `extension_mime`; brand→MIME precision (generic HEIF brands → `image/heif`). No specialist → `requires_specialist_tool` stays `false` for them. A `.heic` whose content major-brand is generic `mif1` reports `image/heif` → `matches_extension=false` (an honest content-vs-extension signal). `LOGIC_VERSION` 1.5.0→1.5.1. No existing field changed/removed/retyped. |
| `1.9` | 1.15.0 | **Cross-platform hardening, schema unchanged.** HEIC/HEIF/AVIF detection corrects the no-libmagic-path `video/mp4` mislabel; `.toml`/`.yaml`/Office `extension_mime` registered deterministically; `iter_files` file order is now OS-stable (sorts by posix string — `WindowsPath` sorted case-insensitively). **`python-magic` excluded on Windows** (a `platform_system` dependency marker — its import-time libmagic search can hang; the pure-Python fallback runs). **NOT byte-identical across OS** — platform is a `ScanContext` field; the contract is identical bytes + identical ScanContext → identical records. `LOGIC_VERSION` 1.4.3→1.5.0 (MIME tier). No existing field changed/removed/retyped. |
| `1.9` | 1.14.0 | **Promotion pass (provisional → stable), additive contract change.** Promoted to stable: `specialist_metadata.pdf.parser`, `specialist_metadata.{document,spreadsheet}.application`, the `vectors_collected[]` `provenance` vector (see §2.4 — these left the provisional list). `--schema` now annotates `stability` (`stable`/`provisional`) on every field/vector/manifest element (the scan manifest itself carries no `stability` key). Designation-only — manifest byte-identical except the version stamps; `LOGIC_VERSION` unchanged (1.4.3). `SCHEMA_VERSION` 1.8→1.9 (promotion = contract change, v0.11/v1.10 precedent). No existing field removed/retyped. |
| `1.8` | 1.13.0 | **`--schema` self-description, schema unchanged.** `file-observer --schema [--schema-format json\|md]` prints the build's COMPLETE output surface (manifest fields, specialists + their metadata fields, vectors, safety_flags, error codes, signal_provenance triggers, format signatures, preservation tiers, subcategories, MIME tiers) and exits without scanning. **A SEPARATE surface** — no manifest-shape change, no per-scan output change; the manifest is byte-identical to v1.12.x. Committed `docs/SCHEMA.md` is the generated `--schema --format md` output (drift-guarded by a test; regenerate on any surface change). New internal registries make the surface enumerable from one place: `ERROR_CODES`, `SAFETY_FLAGS`, `PROVENANCE_TRIGGERS`, `SPECIALIST_FIELDS`. **NOTE (re §2.2):** `--schema` *lists* the provenance trigger strings for tooling/discovery, but per §2.2 the specific trigger strings remain NOT a stability commitment — `--schema` describes the current surface, it does not freeze it. `LOGIC_VERSION` unchanged (1.4.3); `SCHEMA_VERSION` unchanged (1.8). No existing field changed/removed/retyped; no new dependency. |
| `1.8` | 1.12.2 | **Patch (error-code centralization), schema unchanged.** Two error codes (`xml_parse_failed`, `toml_parse_failed`) moved from inline literals to `ERR_*` module constants. Byte-identical manifest output (same on-the-wire strings). De-risk step ahead of v1.13 `--schema`. `LOGIC_VERSION` unchanged (1.4.3). No existing field changed/removed/retyped. |
| `1.8` | 1.12.1 | **Patch (red-team hardening), schema unchanged.** Determinism fix: `ScanContext.dependencies[*].version` coerces a non-string `__version__` to `"unknown"` (was raw → could crash `json.dumps`, and an address-bearing repr could vary across processes). `LOGIC_VERSION` unchanged (1.4.3). No existing field changed/removed/retyped. |
| `1.8` | 1.12.0 | **PDF residual closure, schema unchanged.** Owner-permission-locked encrypted PDF decode (new `safety_flags` value `extraction_permission_bypassed`) + uncompressed xref-stream support. New error code `pdf_encryption_unsupported`. Specialist extraction only — `LOGIC_VERSION` unchanged (1.4.3). New optional dep `cryptography` (in the `[pdf]` extra). No existing field changed/removed/retyped. |
| `1.8` | 1.11.0 | **Opt-in `--watch` continuous trigger loop, schema unchanged.** No manifest-shape change and no per-scan output change: each scan emitted by `--watch` is **byte-identical** to a one-shot `file-observer` invocation against the same filesystem state (the design contract; verified `tests/test_v1_11.py`). `--watch`, `--watch-debounce-ms`, and `--watch-include-files` are **runtime-only** controls — they are *not* recorded in `meta.config`, `context`, or any checksummed field (no causal link to output). Stream emit format is the manifest JSON minus `files[]` (excluded by default to keep emits small; the `delta` block carries what changed) with `--watch-include-files` to opt back in. `LOGIC_VERSION` unchanged (1.4.3). New optional dependency: `watchfiles` (`file-observer[watch]`). No existing field changed/removed/retyped. |
| `1.8` | 1.10.0 | **Provisional-lifecycle release.** **Promotions → stable:** `quality.duplicate_clusters` family, `quality.specialist_stats`, `errors[].detail`, `pdf.text_detected`, `pdf.xref_type` (now under the backward-compat policy). **New provisional fields:** top-level `preservation` (closed-table format-obsolescence); `specialist_metadata.{document,spreadsheet}.application` extended to OLE2 `.doc`/`.xls` (feeds `provenance`, `method_version` 1→2); plus a top-authors line in the human `summary`. **New governance:** a `candidate` tier *below* provisional — tracked/measured in the apparatus, never in the manifest. `SCHEMA_VERSION` 1.7→1.8 (promotions are a contract-level change, v0.11 precedent; + additive provisional fields). `LOGIC_VERSION` unchanged (1.4.3). No existing field changed/removed/retyped. |
| `1.7` | 1.9.1 | **Patch (stat-failure path fix), schema unchanged.** No manifest-shape change. Behavior: a file in a **subdirectory** that fails `stat()` (TOCTOU race / mid-scan deletion / permission flip) now reports its **full source-relative `path`** (e.g. `sub/file.txt`) in the degraded record, instead of the flattened bare filename it previously emitted — making the degraded record consistent with every normal record. `path` is still a relative-posix string (no field retyped). `LOGIC_VERSION` 1.4.2→1.4.3 (the degraded `path` value changes). No existing field changed/removed/retyped. |
| `1.7` | 1.9.0 | **Parallel scan (`--workers N`) + progress, schema unchanged.** No manifest-shape change and **no output change**: the manifest is **byte-identical regardless of worker count** (the design contract — `LOGIC_VERSION` stays 1.4.2 precisely because output does not change; verified workers=1-vs-N on real corpora). `--workers N` and `--progress` are **runtime-only** controls — they are *not* recorded in `meta.config`, `context`, or any checksummed field (no causal link to output). The progress indicator is stderr-only. No existing field changed/removed/retyped. |
| `1.7` | 1.8.2 | **Patch (determinism fix), schema unchanged.** No manifest-shape change. Behavior: a file that fails `stat()` (e.g. deleted mid-scan, or a TOCTOU race between discovery and read) now reports `modified_at: ""` (empty string — matching the `checksum_sha256: ""` already on that degraded record) instead of the wall-clock scan time — so its degraded `FileRecord` (and therefore `manifest_checksum`) is reproducible run-to-run. `modified_at` stays a non-null string, so the Stable contract is unchanged. `LOGIC_VERSION` 1.4.1→1.4.2. No existing field changed/removed/retyped. |
| `1.7` | 1.8.1 | **Patch (red-team hardening), schema unchanged.** No manifest-shape change. Behavior: a new `signal_provenance`/error value `universal_read_failed` (unreadable file → degraded record, not a crash); a max-length filename no longer aborts the scan; out-of-tree symlinks are no longer followed (the walk stays within the source tree, like `_is_safe_zip_entry` for ZIP paths); malformed/adversarial object-stream PDFs are bounded (no unbounded alloc/loop) → null. `LOGIC_VERSION` 1.4.0→1.4.1 (discovery + error-handling behavior change). New optional dep unchanged. No existing field changed/removed/retyped. |
| `1.7` | 1.8.0 | Object-stream PDF decode (additive): `specialist_metadata.pdf.parser` (`pypdf`/`stdlib`/`none`, provisional). `page_count`/`/Info` are now recovered for object-stream PDFs (page tree compressed in an `/ObjStm`) via a cascade — optional `pypdf` → stdlib in-house decoder → null. Strictly additive (fills nulls, never changes a value); validated against pypdf as an oracle (0 disagreements). Specialist extraction only — `LOGIC_VERSION` unchanged (1.4.0). New optional dependency `pypdf` (`file-observer[pdf]`); core install unchanged. No existing field changed/removed/retyped. |

**Scanner versions under schema `1.2` (no schema change):** 1.2.1–1.2.4 — chatlog false-positive hardening (`LOGIC` → 1.1.4, chatlog `method_version` → 8). **1.3.0** — pure-Python content-based MIME fallback when libmagic is unavailable: new `signal_provenance.trigger` value `magic_signature_fallback` (a new *value* of an existing free-string field, not a new field/type), `MAGIC_SIGNATURES` expanded to ~24 formats incl. RIFF→WebP/WAV/AVI, enriching `file_signature`/`format_signatures`/`is_polyglot`. `LOGIC` → 1.2.0. Schema unchanged; all additive.

---

## 4. Migration Notes

### 4.1 From schema 0.4 to 0.5

`specialist_metadata` was a flat dict in 0.4 and earlier. In 0.5+, it is namespaced by format category. To migrate consumer code:

```python
# Pre-0.5
page_count = file_record["specialist_metadata"]["page_count"]

# 0.5+
page_count = file_record["specialist_metadata"]["pdf"]["page_count"]
```

### 4.2 From schema 0.6 to 0.7

`safety_flags` and `quality` fields added. Existing fields unchanged. No code changes required for consumers that ignore unknown fields.

### 4.3 From schema 0.7 to 0.8

Three additive changes. Existing fields unchanged. No code changes required for consumers that ignore unknown fields.

1. **New FileRecord field `is_chatlog`** (bool, always present, default `false`). Set to `true` when content-detection rules match on `.txt` / `.md` / `.mdx` files. Runs even when the specialist tier is disabled.

2. **New specialist namespace `chatlog`** under `specialist_metadata`. Populated only when `enable_specialists=True`, the file is content-detected as a chatlog, and the content MIME type passes the `chatlog` MIME guard (`text/plain`, `text/markdown`, `text/x-markdown`). Fields within the namespace: `turn_count`, `speaker_labels`, `section_marker_count`, `section_marker_styles`, `avg_turn_chars`, `max_turn_chars`, `min_turn_chars`, `reference_tokens` (an object with `at_mentions`, `wiki_links`, `code_fence_blocks`, `url_count`), `top_capitalized_tokens`, `capitalized_token_count`, `vocabulary_size_estimate`.

3. **New ScanQuality field `quality.chatlog_files`** (int). Count of FileRecords with `is_chatlog == true` in the scan.

**Sample migration:**

```python
# Pre-0.8 consumer (continues to work unchanged — all additions are additive)
for f in manifest["files"]:
    if f["requires_specialist_tool"]:
        route_to_specialist(f["specialist_tool"])

# 0.8+ consumer opting in to chatlog signals
for f in manifest["files"]:
    if f["is_chatlog"]:
        chat = f.get("specialist_metadata", {}).get("chatlog")
        if chat:
            route_to_chatlog_pipeline(chat)
```

Consumers that key on `specialist_tool` values should be aware that `"chatlog_signals"` is a new valid value in 0.8 and MAY appear on `.txt` / `.md` / `.mdx` files. A consumer that switches on the full set of tool names should add a `chatlog_signals` case (or a default) to avoid routing these files nowhere.

### 4.4 From schema 0.8 to 0.9

Five additive changes. All v0.8 fields unchanged. No code changes required for consumers that ignore unknown fields. All v0.9 additions are **provisional** (§2.4) and may change in future minor versions.

1. **New top-level manifest array `vectors_collected[]`**. One entry per vector that ran, sorted by `vector_id`. Each entry includes `vector_id`, `method_version`, `scope`, `rules_hash`, `static_tuning_hash`, `identity_digest`, `applied_to_count`, and `summary`. The identity digest is deterministic — same vector config + same input = same digest.

2. **New FileRecord field `reference_tokens`** (object or null). Seven subcategory counts (`at_mentions`, `wiki_links`, `code_fence_blocks`, `url_count`, `email_mentions`, `path_references`, `numeric_id_patterns`). Present on text-decoded files; null on binary files.

3. **New ScanQuality field `quality.per_directory_summary[]`**. One entry per top-level subdirectory with aggregated counts (total_files, chatlog_files, safety_flags_files, mime_mismatches, polyglots_detected, specialist_failures, unsupported_extensions).

4. **New email namespace field `specialist_metadata.email.body_chatlog`** (object, optional). Present when the chatlog vector's detection rules match on an email's extracted body text. Same shape as `specialist_metadata.chatlog`. Note: `is_chatlog` stays `false` on the email FileRecord — the file itself is binary; only the body was tested.

5. **Dublin Core alignment** documented for the `document` namespace. `document.title` corresponds to `dc:title`, `document.author` corresponds to `dc:creator`. No field changes — documentation only.

---

## 5. Forward Compatibility Tips

If you are building a consumer for a long-lived integration:

1. **Always check `schema_version`** before parsing
2. **Branch on the MAJOR component** (e.g., handle schema `1.x` as a single class of manifests)
3. **Ignore unknown fields** rather than failing on them
4. **Use stable signal layers** (raw vs derived) instead of specific trigger strings for routing logic
5. **Verify `manifest_checksum` and `manifest_signature`** when integrity matters
6. **Use `previous_manifest_checksum`** to verify scan chains

---

## 6. Backward Compatibility Policy (since v1.0)

- **MAJOR** (1.x → 2.0): Breaking change. Field removed, renamed, or type changed. Preceded by deprecation in at least one full MINOR release.
- **MINOR** (1.0 → 1.1): Additive only. New fields, vectors, namespaces. Existing fields untouched.
- **PATCH** (1.0.0 → 1.0.1): No schema change. Bug fixes, vector tuning (method_version bumps).
- Code written for schema `1.x` WILL work with schema `1.y` where `y > x`.
- Consumers SHOULD ignore unknown fields for forward compatibility.
- The vector identity digest preimage shape and hash function (SHA-256) MUST NOT change without a MAJOR version bump.

---

## 7. How This Document Updates

This document is updated when:

- A new field becomes stable enough to commit to
- A new error code is introduced
- A new specialist namespace is introduced
- A new safety flag is introduced
- A schema version changes
- A migration is required

Updates are made in the same PR that introduces the change. Consumers should check this document on every minor release.
