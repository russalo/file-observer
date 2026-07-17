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
| `unsupported_extension` | universal | Could not identify the file — its extension isn't in the supported set AND its content wasn't identified (octet-stream, an extension-only MIME guess, or unreadable). Content-aware: text since v1.21, **any file type since v1.22**; previously "extension not in supported set." |
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
- `summary` — **since v1.45** (see below)

**Properties:**
- Deterministic for identical inputs and identical scanner context
- Changes when ANY observable signal changes
- Stable across re-runs of the same scanner version on the same files

**The `summary` is a non-sealed derived view (v1.45).** The top-level human-readable `summary` is a
*rendering* of already-checksummed data (files / vectors / quality), not an independent observation, so
it is **excluded from `manifest_checksum`** — a prose refresh never moves the checksum (previously it did,
forcing a `LOGIC_VERSION` bump each time). Consequences a consumer must know: the summary is **not part of
the tamper-evident content**; it is a *build-versioned* view (the same sealed observations render a
different summary under a newer `scanner_version`); and it is **reconstructible** from the sealed
observations. **Trust the sealed machine fields; treat the summary prose as convenience, not evidence.**
The v1.45 change moved every manifest's `manifest_checksum` once (the exclusion) — a one-time
`LOGIC_VERSION` bump, versioned so a consumer knows the computation changed.

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
- **Does not cover the `summary` (v1.45)** — the signature is computed *from* the checksum, and the
  checksum excludes `summary` (§1.8), so the summary prose is neither checksummed nor signed. To verify a
  summary, re-derive it from the sealed observations under the manifest's `scanner_version`.

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

### 1.12 The `--schema` Self-Description Document (build-time interface)

`file-observer --schema --format json` emits a deterministic description of the
build's complete output surface and exits without scanning (introduced at schema
1.8 / v1.13; see §3). **Its envelope shape is a committed build-time interface**,
versioned by `schema_doc_version` (currently `3`):

- The document is a JSON object carrying `scanner_version`, `logic_version`,
  `schema_version`, `schema_doc_version`, the structural sections (`manifest`,
  `specialists`, `vectors`), and the enumeration sections (`safety_flags`,
  `error_codes`, `provenance_triggers`, `format_signatures`, `preservation_tiers`,
  `mime_tiers`, `reference_tokens_subcategories`, `filename_patterns_subcategories`).
- `manifest` is `{RecordName: [{"name": str, "type": str, "stability": "stable"|"provisional"}, …]}`; **`FileRecord`** field descriptors additionally carry `"trust": "fo_derived"|"file_derived"|"mixed"` (added at `schema_doc_version` 3 / v1.40 — see §1.13).
- A **backward-incompatible change to this shape** (renaming/removing an envelope
  key, changing the field-object key set, re-nesting `manifest`) **bumps
  `schema_doc_version`** — a consumer's re-snapshot signal.

**Committed: the shape. Not frozen: the field inventory.** Which fields appear
(and their `stability`) evolves additively with the build — tracked by
`schema_version`/`SCHEMA_VERSION`, not `schema_doc_version`. But a field marked
`stable` inherits the §6 backward-compatibility policy (not removed/retyped
without a MAJOR `SCHEMA_VERSION` bump + deprecation), so consuming the **names of
stable fields** off `--schema` is exactly as safe as consuming the manifest.

**Not committed:** the provenance `trigger` strings `--schema` lists remain opaque
per §2.2 — `--schema` describes the current surface, it does not freeze those.

Committed 2026-06-17 (v1.21.2), once `--schema` gained a real consumer.

---

### 1.13 Field trust classification and safe mode (`--trusted-only`)

Introduced v1.40. Every manifest field is classified by whether it can carry
**attacker-controlled free text** into a consumer:

- **`fo_derived` (trusted):** values file-observer computed — numbers, booleans,
  hashes, MIME types, closed-vocabulary enums/labels, `safety_flags`, timestamps,
  sizes. Safe to summarize even when the value was read from the file (a `page_count`
  can't carry a payload).
- **`file_derived` (untrusted):** verbatim bytes from the input — `path`/`filename`,
  `content_preview`, `tags`, frontmatter, `structural`, `reference_tokens`, and the
  string values inside `specialist_metadata` (extracted author / title / producer /
  EXIF make+model / email subject / chatlog speaker label). An attacker who controls
  a filename or a metadata field can place text here that rides into a downstream model.

**Committed:**

- Each `FileRecord` field descriptor in `--schema` carries a **`trust`** attribute
  (`fo_derived` / `file_derived` / `mixed`) — a consumer can read it to build its own
  projection. The classification is **fail-safe: an unclassified/uncertain field is
  reported `file_derived`**, so it can only over-suppress, never under-report.
- **`--trusted-only`** (CLI, `ScannerConfig(trusted_only=True)`, the MCP `trusted_only`
  tool param, or a server-wide `--trusted-only`) emits a **projection** of the manifest
  that (a) scrubs every `file_derived` value across the WHOLE manifest — per-`FileRecord`
  fields AND the manifest-level blocks: **nulling** `meta.source_dir`, the human `summary`,
  and `quality.per_directory_summary[].directory`; **emptying to `[]`** the `delta` path lists
  and `quality.duplicate_clusters[].paths`; and **emptying to `{}`** `vectors_collected[].summary`
  (so a consumer must handle `[]`/`{}`, not only `null`) — **except the `lexicon` vector summary, kept
  since v1.44** (§1.13.1) — in both JSON and JSONL; (b) adds a per-file **`path_id`**
  = `sha256(<relative-posix path>)` (a fo-derived correlation handle carrying no free text)
  and a top-level **`trusted_only: true`** marker; and (c) recomputes `manifest_checksum`
  over the projected content, so the safe-mode output is self-verifiable.
- **The DEFAULT manifest is byte-identical** to a pre-v1.40 scan — safe mode is a separate,
  opt-in output; `LOGIC_VERSION` / `SCHEMA_VERSION` are unchanged (the front-door precedent).

**Not committed / caveats:**

- Safe mode is a **projection, not a sanitizer** — it drops untrusted fields, it never
  rewrites a value to make it "safe."
- `--trusted-only` output is a derived VIEW and does **not** validate against the committed
  `docs/manifest.schema.json` (which models the DEFAULT manifest: the nulled fields are
  non-nullable there, and `path_id` is not present). A projection-aware or separate
  trusted-only schema is a planned follow-up.
- It over-suppresses by design (fail-safe): it also drops fo-derived but free-text-*shaped*
  values it can't prove safe (the human `summary`, corpus vector summaries — **except the
  `lexicon` vector, see §1.13.1** — enum strings inside `specialist_metadata`). Use the default
  manifest when you need those.

Committed 2026-07-12 (v1.40.0).

#### 1.13.1 Lexicon exception (v1.44)

The one deliberate exception to the blanket vector-summary / `specialist_metadata`-key scrub: the
**lexicon per-category breakdown survives `--trusted-only`** — the per-file
`specialist_metadata.lexicon_match.categories` (category names + `{count, density}`) and `lexicon_id`,
and the corpus `lexicon` vector `summary` (`lexicon_id` / `files_matched` / `category_hits`). These are
counts (`fo_derived`) keyed by category names / a `lexicon_id` that are **`consumer_config`** — a third
trust class: a string that originates from the consumer's own runtime configuration (the supplied
lexicon), **never from a scanned file**. So a safe-mode consumer can route *by category* on a
model-safe manifest. The relaxation is scoped to the `lexicon_match` namespace and the `lexicon` vector
**only** — every other namespace's dynamic keys and every other vector summary are still scrubbed, and
any non-enumerated `lexicon_match` leaf still falls through to the generic nulling projector. Committed
2026-07-14 (v1.44.0, #146).

---

### 1.14 The screening receipt (`--receipt`)

Introduced v1.42. A compact, audit-friendly projection of a built manifest — CLI `--receipt`, MCP `receipt` param — so an orchestrator can persist a small record of *what was screened, under what config*, and staple its own read/skip decision to it. **A projection of existing observation** (no new field in the default manifest); the DEFAULT manifest is byte-identical (LOGIC/SCHEMA unchanged — the front-door precedent).

**Committed shape (versioned by `receipt_doc_version`, currently `1`):**
- **Envelope:** `receipt_doc_version`, `scanner_version`, `logic_version`, `schema_version`, `manifest_checksum`, `manifest_signature` (when signed), `scan_id`, `generated_at`, `dictionary_id` (the `lexicon` vector's, when a lexicon ran), and `receipts` (a list).
- **Per-file receipt:** `receipt_id`, `path_id`, `checksum_sha256`, `size_bytes`, `mime_type`, `safety_flags`, and `lexicon` (`{body_hits, metadata_hits, categories, metadata_categories}`) when a lexicon ran.
- **`receipt_id`** = `sha256(preimage)`, where the preimage is the **length-prefixed** concatenation of `manifest_checksum`, the relative POSIX path, and `checksum_sha256` — i.e. `f"{len(a)}:{a}{len(b)}:{b}{len(c)}:{c}"`. A consumer recomputes it from those three inputs to **verify** the receipt; changing the file content (→ `checksum_sha256`) or the scan (→ `manifest_checksum`) changes the id. Length-prefixing makes the preimage unambiguous — no two distinct triples collide (the v1.38 `dictionary_id` lesson).

**Safe by construction:** every receipt field is fo-derived — the raw `path` is NOT emitted (`path_id` correlates back to a path the consumer hashes itself). A receipt is safe to feed a model *and* to persist as an audit record.

**The boundary fo cannot cross:** a receipt says *what fo observed*, never *what the agent did with it*. fo does not — and will not — record the read/skip decision; it makes its record trivially correlatable so the orchestrator's decision log and fo's observation join on one `receipt_id`. Observe-don't-interpret; counts, not verdicts.

**Persistence:** via **MCP** the receipt is returned to the caller (the server is stateless/read-only and persists nothing itself); via the **CLI** `--receipt` writes to a file or `--stdout`.

Committed 2026-07-12 (v1.42.0).

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

- `format_signatures` — internal magic signature scan results. **Held-by-design — permanently informational, NOT a promotion candidate:** the signature vocabulary intentionally grows with every MIME-detection change, so freezing it would be wrong. Branch on *presence*, not exact tokens (the same stance as the §2.2 provenance triggers).
- `is_polyglot` — derived from `format_signatures`; same held-by-design status.
- `specialist_metadata.chatlog.speaker_turn_counts`, `.speaker_turn_chars`, `.alternation` — per-speaker turn structure (provisional since v1.2)
- `specialist_metadata.chatlog.content_shape` (`.utterance_ratio`, `.density`) — content-shape detection signals; null in JSONL mode (provisional since v1.4)
- `specialist_metadata.presentation.*` — the entire `presentation` namespace (`slide_count`, `title`, `author`, `application`) is **provisional** (new in v1.24, Candidate B phase 1). The namespace *key* is additive-stable (§1.4); its fields are provisional pending a promotion pass. (`.odt` adds nothing new to `document`; `.ods` nothing new to `spreadsheet`; `.jp2`/`.tiff` reuse the existing `image` fields.) Legacy `.ppt` (v1.25, OLE2) populates these same `presentation` fields — no new field.
- `specialist_metadata.audio.*` — the entire `audio` namespace (`format`, `bitrate`, `duration_s`, `title`, `artist`, `album`, `year`) is **provisional** (new in v1.25, Candidate B phase 2; `.mp3`). The namespace *key* is additive-stable (§1.4); its fields are provisional pending a promotion pass.
- `specialist_metadata.lexicon_match.*` — the entire `lexicon_match` namespace (`lexicon_id`, `categories` [`{cat: {count, density}}`], `total_hits`, `total_tokens`) is **provisional** (new in v1.38, bring-your-own-lexicon). Present **only when a consumer supplies a lexicon** (`--lexicon` / `ScannerConfig(lexicon=…)`); absent otherwise (dormant → manifest byte-identical). fo counts the consumer's category-tagged terms (word-boundary, literal) in the file's text and reports per-category counts + density — an **observation, never a verdict** (the consumer thresholds). **Terms are never emitted** — only counts, category names, and a content-hash `dictionary_id` (on the `lexicon` vector). A `lexicon_match` safety_flag fires on any hit. **v1.41** adds a provisional `metadata` sub-block (`{categories, total_hits, total_tokens}`) — the same per-category counts run over the file-derived METADATA strings (`filename` [not the full path] + `tags` + `frontmatter` + `structural` + the string leaves in `specialist_metadata`, minus `content_preview` and the `lexicon_match` namespace itself), catching a term that hides in metadata (a filename, an EXIF make, a PDF producer) where the body scan can't look; the body counts and the `metadata` block are kept separate, and the safety_flag fires on a body OR metadata hit. On a binary file (no body scan) the namespace is created with a zero body block + the `metadata` block. Bounded: the joined metadata text is capped at `LEXICON_METADATA_MAX_CHARS`. The namespace *key* is additive-stable (§1.4); its fields are provisional.
- `specialist_metadata.fact_block.*` — the entire `fact_block` namespace (`pair_count`, `pairs` [a `{key, value}` list], `duplicate_keys`) is **provisional** (new in v1.32, FR #114). Content-detected on any text body that is a `key: value` block (frontmatter stripped; a sentence-value veto keeps it off dialogue); the FALLBACK observer for a text body no dedicated specialist owns. Emits the observed pairs **verbatim + generic** — no key schema, no validation, no normalization (the consumer interprets what the pairs mean). **`pairs` carries only DISTINCT keys, first-occurrence order** — a repeated key increments `duplicate_keys` and is not re-emitted (so a consumer can safely key on `pairs[].key`). **Bounded observation** (a consumer building on `fact_block` should know the caps): keys are truncated to 64 chars, values to 4096 chars, and at most 4096 distinct pairs are emitted — beyond that, further new keys are dropped and are *not* counted in `duplicate_keys`. The namespace *key* is additive-stable (§1.4); its fields are provisional.

**Promoted to stable in v1.31.0** (now under the backward-compat policy — not removable/retypable without a MAJOR bump): the **capture-metadata surface** — the `image`-namespace EXIF fields (`make`/`model`/`orientation`/`datetime_original`/`gps_present`/`xmp_present`; the older `width`/`height`/`bit_depth` dimensions were already stable since 0.5, so the whole `image` namespace is now stable) AND the entire `video` namespace (`codec`/`duration_s`/`width`/`height`/`creation_date`/`creation_date_qt`/`make`/`model`/`gps_present`/`gps_source`). Settled logic since ship (image v1.16; video v1.17–1.20), exiftool-oracle-validated, corpus-proven, and red-teamed. `gps_present` is **presence, not coordinates** (bool) and `gps_source` names the mechanism — that observe-don't-over-capture boundary is part of the stable contract. Bounded observation still holds: a field is `null` when not observed within bounds, and a later release may fill more nulls (additive). **Observed field VALUES byte-identical** (designation-only — stability lives only in `--schema`, never the manifest; no extracted value changed) — but because `schema_version` is in the checksum preimage, `manifest_checksum` moves for every manifest on v1.31.0 (as on any SCHEMA bump), so a consumer pinning the checksum will see it change while every extracted value is unchanged; `LOGIC_VERSION` unchanged (1.15.3). SCHEMA 1.16→1.17 (promotion = contract change, the v0.11/v1.10/v1.14/v1.23 precedent).

**Promoted to stable in v1.23.0** (now under the backward-compat policy — not removable/retypable without a MAJOR bump): the **`preservation`** signal — both the per-`FileRecord` `preservation` field (`.format_obsolescence`: `current`/`at_risk`/`obsolete`; `.migration_recommended`: bool; top-level, same scope as `filename_patterns`) AND the `preservation` vector. Settled since v1.10 (closed obsolescence table, rules-hash-fingerprinted) with demonstrated evidence-of-value on the corpus. The closed table may still grow additively (more formats classified), rules-hash-tracked — table growth is an additive value change, not a field-shape change (the `provenance`-vector precedent).

**Promoted to stable in v1.14** (now under the backward-compat policy — not removable/retypable without a MAJOR bump): `specialist_metadata.pdf.parser` (`pypdf`/`stdlib`/`none` decode tier — the PDF arc completed at v1.12; its value records which tier ran and is independent of any future `/Info` extraction), `specialist_metadata.{document,spreadsheet}.application` (producing application; OOXML + OLE2), and the `vectors_collected[]` `provenance` vector (shape `toolchains`/`production_years`/`digitization` — stable; the closed toolchain table may still grow additively, rules-hash-tracked). As of v1.14, `file-observer --schema` annotates every field/vector with its `stability` (`stable`/`provisional`).

**Promoted to stable in v1.10** (now under the backward-compat policy — not removable/retypable without a MAJOR bump): `quality.duplicate_clusters` / `duplicate_cluster_count` / `redundant_file_count`, `quality.specialist_stats`, `errors[].detail`, `specialist_metadata.pdf.text_detected`, `specialist_metadata.pdf.xref_type`.

**Candidate tier (below provisional, v1.10):** some observations (CAD coverage, word-twisting provenance) are tracked + measured in the review apparatus but are **NOT in the manifest** at all — they carry no contract status until promoted to provisional. (Image EXIF was a candidate here until v1.16 built it into the manifest; it is now a provisional field, listed above.) The ladder is `candidate → provisional → stable`; see `CONVENTIONS.md`.

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
| `1.14` | 1.23.0 | **Promotion pass: `preservation` → stable (designation-only).** The `preservation` signal — the per-`FileRecord` field (`.format_obsolescence`: current/at_risk/obsolete; `.migration_recommended`: bool) AND the `preservation` vector — graduates provisional → stable: settled since v1.10 (closed obsolescence table, rules-hash-fingerprinted) + demonstrated evidence-of-value (accurate `at_risk`/`obsolete` on legacy Office/CAD/Flash/WordPerfect across the corpus; the v1.14 hold resolved). Also reclassified `format_signatures`/`is_polyglot` in §2.4 as **held-by-design** (permanently-informational, never promoted). **Observed field VALUES byte-identical** (designation-only — stability lives only in `--schema`, never the manifest; no extracted value changed) — but because `schema_version` is in the checksum preimage, `manifest_checksum` moves for every manifest on v1.31.0 (as on any SCHEMA bump), so a consumer pinning the checksum will see it change while every extracted value is unchanged; `LOGIC_VERSION` unchanged (1.12.1). SCHEMA 1.13→1.14 (promotion = contract change, v0.11/v1.10/v1.14 precedent). No existing field changed/removed/retyped. |
| `1.14` | 1.23.1 | **PDF-header false-positive fix (patch), schema unchanged.** The `%PDF-` magic signature, matched find-anywhere in the first 8 KB since v1.3, typed any file carrying that literal *anywhere* (e.g. a source file with `%PDF-1.4` in a string) as `application/pdf` in the pure-Python MIME sniff. Now `%PDF-` is bounded to a 256-byte header window for the **MIME-type judgment** (`_sniff_mime`), so a deep stray literal no longer mis-types the file — while `format_signatures`/`is_polyglot` keep find-anywhere, so a genuinely embedded PDF still registers and polyglot observation stays honest (the C1/C2 split). Surfaced by a clean-room replica's signature sweep. `LOGIC_VERSION` 1.12.1→1.12.2 (MIME-sniff routing). No existing field changed/removed/retyped. |
| `1.14` | 1.23.2 | **Corroborated PDF-header MIME sniff (patch, hardening), schema unchanged.** Generalizes the v1.23.1 fix: the `%PDF-` MIME-sniff window widens 256→1024 (matching the scanner's own `sample[:1024]` PDF-header tolerance) AND now requires a corroborating PDF-structure token (` 0 obj`/`endobj`/`/Type`/`xref`/`trailer`/`%%EOF`), so a real PDF with a junk/BOM prefix up to 1024 bytes is correctly typed while a deep literal with no structure is still rejected — offset alone couldn't separate them (the corpus FP sat at 864, inside 1024). `scan_signatures`/`is_polyglot` keep pure find-anywhere (corroboration is sniff-only). **Consumer-visible only on the no-libmagic path:** a `%PDF-` with NO PDF structure in the first 8 KB (a truncated/degenerate "PDF") is no longer typed `application/pdf` by the sniff — a real PDF always carries structure, so this affects only non-PDF inputs. `LOGIC_VERSION` 1.12.2→1.12.3. No existing field changed/removed/retyped. |
| `1.14` | 1.23.3 | **bzip2 dual-magic MIME sniff (patch, no-libmagic path), schema unchanged.** FO's pure-Python bzip2 signature required the compressed-block magic ("1AY&SY") at offset 4, so a data-less bzip2 (`bz2.compress(b"")`) — which carries the end-of-stream magic (0x177245385090) there instead — sniffed as octet-stream. v1.23.3 accepts EITHER magic at offset 4 (via a new `_OneOf` byte-alternation matcher) plus the block-size level digit '1'-'9' at offset 3, so empty bzip2 is recognized while prose ("BZh9 is...") and an invalid level byte are still rejected. **No-libmagic path only** (with libmagic, bzip2 was already typed). Reconciled byte-for-byte with the puresniff clean-room replica. `LOGIC_VERSION` 1.12.3→1.12.4. No existing field changed/removed/retyped. |
| `1.15` | 1.24.0 | **Office & media extraction (Candidate B, phase 1).** New `presentation` namespace (`slide_count`/`title`/`author`/`application`, provisional) + extraction for `.pptx`/`.odp`/`.odt`/`.ods`/`.jp2`/`.tiff`/`.tif`, reusing the docx/xlsx ZIP+XML and the v1.16 image-EXIF / ISOBMFF / TIFF-IFD machinery (stdlib, no new dep). `requires_specialist_tool` flips False→True for these seven types (`LOGIC_VERSION` 1.12.4→1.13.0; routing change, the v1.16 precedent). SCHEMA 1.14→1.15 (a new namespace = contract-shape change); new fields provisional. No existing field changed/removed/retyped. |
| `1.16` | 1.25.0 | **Audio & legacy presentation extraction (Candidate B, phase 2).** New `audio` namespace (`format`/`bitrate`/`duration_s`/`title`/`artist`/`album`/`year`, provisional) for `.mp3` — ID3v2 tags + a bounded MPEG frame-header parse (stdlib, no new dep; the one net-new untrusted-binary parser, carried at the v1.8.1 bounded/never-crash bar). Legacy `.ppt` reuses the existing `presentation` fields via the OLE2 `SummaryInformation`/`DocumentSummaryInformation` streams (the `.doc`/`.xls` olefile path — no new field). `requires_specialist_tool` flips False→True for `.mp3`/`.ppt` (`LOGIC_VERSION` 1.13.0→1.14.0; routing change, the v1.16/v1.24 precedent). SCHEMA 1.15→1.16 (the new `audio` namespace = contract-shape change); new fields provisional. No existing field changed/removed/retyped. |
| `1.16` | 1.28.1 | **`[all]` install extra (patch, packaging-only), schema unchanged.** A new `pip install "file-observer[all]"` pulls every optional specialist dependency in one line (the union of `[yaml,msg,security,pdf,watch]`; self-referencing so it can't drift, drift-guarded). `[dev]` now references `[all]` (DRY). No scanner / manifest / API change (packaging metadata only — the v1.0.1/v1.0.2 precedent). `LOGIC_VERSION`/`SCHEMA_VERSION` unchanged (1.14.1 / 1.16). |
| `1.16` | 1.29.0 | **Chatlog detection recognizes agentic (tool-turn) sessions, schema unchanged.** A conversation turn is now counted when it has a conversational role AND content carrying a **text-bearing block** (any block with a string `text`, backward-compat) OR a **distinctive agentic block** (`thinking`/`tool_use`/`tool_result`), not only when it yields prose text. This recovers tool-heavy Claude Code session logs the prior text-centric gate false-negatived (measured: 3/28 real federation logs, incl. a 139 MB session; falsify-first + leg-1 review validated FP-clean vs telemetry/RBAC/function-call/gallery/doc-store JSON — the generic `image`/`document` types are deliberately NOT triggers). Both detection AND the chatlog turn-counting signals adopt it (prose signals — char/vocabulary — stay text+thinking only). **`is_chatlog` is strictly additive** (False→True; no file flips True→False), but the chatlog **signal values** (`turn_count`, `speaker_turn_counts`, …) and the chatlog vector `identity_digest` **move for already-detected agentic logs**, so `manifest_checksum` moves on any corpus containing agentic chatlogs. `LOGIC_VERSION` 1.14.1→1.15.0; chatlog `method_version` 9→10; `SCHEMA_VERSION` unchanged (1.16). No existing field changed/removed/retyped. |
| `1.16` | 1.30.2 | **ReDoS / bounded-time hardening (patch, red-team hardening), schema unchanged.** file-observer bounds input *size* (`baseline_max_bytes`), but three content regexes backtracked super-linearly on bounded-size-but-pathological input, so a single crafted `.md`/`.txt` could hang a per-file scan: `CHATLOG_WIKI_LINK_RE` (~13 s on 64 KB of `[[`), `ASSET_RE` (~1.7 s on 64 KB of `[`), and `PROVENANCE_VERSION_SUFFIX_RE` (a `\s+`/`\s*` overlap — hung on a 64 KB-whitespace PDF `/Producer`; the third was found by a falsify-first all-regex battery, not manual read). All three are bounded/anchored → linear (≤53 ms); a standing guard (`test_regex_redos_hardening.py`) battery-tests **every** compiled regex under a hard per-regex timeout so the class can't regress. Behavior is byte-identical on real content (verified parity: wiki links, markdown asset paths, real producer strings incl. the leading-whitespace edge); observed **values** change only on bracket-bearing / over-long (label >1024 / target >4096 = PATH_MAX — no valid on-disk path is ever excluded) / >32-whitespace pathological inputs. The `reference_tokens` rules-definition carried the actual wiki pattern, so it is updated and **reference_tokens `method_version` bumps 2→3** — its `rules_hash` and `method_version` move in `vectors_collected`, so `manifest_checksum` moves for **every reference_tokens-bearing manifest** (the fingerprint contract: a rule edit MUST move the digest; consumers see an explicit rule change, not silent drift). The provenance vector's fingerprint is live-derived and moved automatically with the suffix-regex fix. (The v1.8.1 red-team-hardening precedent; corpus sweep NO-DRIFT.) This is the *bounded-size-but-unbounded-time* member of the bounded-observation class the v1.8.1 (size/crash/escape) pass didn't cover. `LOGIC_VERSION` 1.15.2→1.15.3; `SCHEMA_VERSION` unchanged (1.16). No manifest field/shape change. Surfaced by the fo↔bruni seam audit (the same O(n²)-regex class, checked against fo's own extractors). |
| `1.17` | 1.31.0 | **Promotion pass: capture-metadata (image EXIF + video) → stable (designation-only).** The v1.16 `image`-namespace EXIF fields (`make`/`model`/`orientation`/`datetime_original`/`gps_present`/`xmp_present`) and the entire v1.17–1.20 `video` namespace (`codec`/`duration_s`/`width`/`height`/`creation_date`/`creation_date_qt`/`make`/`model`/`gps_present`/`gps_source`) graduate provisional → stable: settled logic since ship, exiftool-oracle-validated, corpus-proven (`wikimedia-exif` + `synth-video-capture`), and red-teamed (`test_capture_metadata_hardening`). The image dimensions were already stable (since 0.5), so both namespaces are now fully stable. **Observed field VALUES byte-identical** (designation-only — stability lives only in `--schema`, never the manifest; no extracted value changed) — but because `schema_version` is in the checksum preimage, `manifest_checksum` moves for every manifest on v1.31.0 (as on any SCHEMA bump), so a consumer pinning the checksum will see it change while every extracted value is unchanged; `LOGIC_VERSION` unchanged (1.15.3). SCHEMA 1.16→1.17 (promotion = contract change, the v0.11/v1.10/v1.14/v1.23 precedent). No existing field changed/removed/retyped. |
| `1.23` | 1.46.6 | **Lexicon-index members confined to the index directory (patch, LOGIC/SCHEMA unchanged — loader hardening).** From bestiary's soak (slice ③): a `--lexicon-index` subscription file's `sources` members could `../`-escape (or use an absolute path, or a symlink) *out* of the index directory before failing loud — the exact "traversal surface" the v1.43 RFC deferred `!#include` to avoid and claimed absent. `_read_lexicon_index` now applies `resolve()`-containment: a member escaping the index dir fails **loud** (the read never happens), closing `../` + absolute + symlink escapes at once. Operator-trust so not a strict vuln, but it matters under the subscription/distribution model (a third-party index shouldn't reach outside its bundle). Faithful to v1.43's self-contained-bundle model; **cross-bundle composition stays available via separate `--lexicon PATH` flags** (the arbitrary-path mechanism), so no functionality is lost. A loader hardening — a valid *in-bundle* index resolves identically → the manifest is byte-identical, so `LOGIC_VERSION`/`SCHEMA_VERSION` are UNCHANGED (1.24.4 / 1.23; the v1.43 loader-frozen precedent). Only an *escaping* index changes, from read-then-fail-loud to block-then-fail-loud. No manifest field changed. |
| `1.23` | 1.46.5 | **Never-crash: a numeric-typed EXIF make/model no longer aborts the scan (patch, SCHEMA unchanged, LOGIC value-change).** From bestiary's decorrelated capture-metadata soak (#165): an EXIF `make`/`model` tag with a *numeric* TIFF type (SHORT/LONG, not the ASCII the spec requires) made fo store an `int`; the aggregate summary then did `.strip()` on it → an unhandled `AttributeError` that aborted the **whole scan** (corpus-level — one bad `.jpg` crashed a whole directory) with no per-file `ErrorRecord`. Fixed in two layers: `_parse_exif_tiff` **type-gates** (`make`/`model`/`datetime` are ASCII by spec → a numeric-typed tag is `None`, never an `int`; `orientation` stays the one numeric SHORT field), and `_build_summary` **defensively** lets only string make/model contribute (the other aggregate string sites already had the `isinstance` guard). An observed value changes only on a **malformed** EXIF file (int→None) → `manifest_checksum` moves for those files only (the v1.8.2/v1.25.1 degraded-path precedent; real corpora → NO-DRIFT). `LOGIC_VERSION` 1.24.3→1.24.4; `SCHEMA_VERSION` unchanged (1.23) — `make`/`model` were always documented as `str`-or-`None`, now enforced. No existing field changed/removed/retyped. |
| `1.23` | 1.46.4 | **Recognize macOS-universal metadata by magic (patch, SCHEMA unchanged, LOGIC recognition-change).** `.DS_Store` (Bud1) and `._*` (AppleDouble) appear in nearly every macOS directory; libmagic types both `application/octet-stream`, so the v1.22 content-recognition gate flagged them `unsupported_extension` on every Mac corpus scan (an error-record spray, surfaced by a MacBook Neo APFS shakedown). fo now recognizes them by magic — a signature match is a positive content ID, so they count as *identified* even when libmagic shrugs (a genuine unknown binary still flags — control-tested). `unsupported_extension` flips off + `format_signatures` gains the label (`application/x-apple-dsstore` / `application/applefile`) for these files → `manifest_checksum` moves for `.DS_Store`/AppleDouble-bearing manifests (a recognition values/routing change — the v1.22/v1.23.3 precedent; no new field; corpora without them → NO-DRIFT). `LOGIC_VERSION` 1.24.2→1.24.3; `SCHEMA_VERSION` unchanged (1.23). No existing field changed/removed/retyped. |
| `1.23` | 1.46.3 | **MCP-surface hardening (patch, LOGIC/SCHEMA unchanged) — the manifest is untouched.** From bestiary's decorrelated consumer-seat (MCP-client) shakedown. #161: `scan_file` scans an isolated single-file copy, so `sidecar_exists` (which checks the file's *neighbourhood*) was a misleading `False`; it is now **re-observed on the original path** (a neighbourhood stat via fo's own `detect_sidecar`, not a sibling scan) → the correct value matching `scan_directory`; `asset_matches` is content-derived and unaffected. #162: the pre-scan work-guard's `max_files` (an LLM-constructed tool arg) is now **clamped to a server ceiling** (`SERVER_MAX_FILES` = 100 000, floor 1) so an over-set value can't defeat the guard (the floor also fixes a negative `max_files` "more than -1 files" message). MCP front-door only — `scan_directory`'s manifest is byte-identical to a CLI scan, so `LOGIC_VERSION`/`SCHEMA_VERSION` are UNCHANGED (1.24.2 / 1.23; the v1.38.1 runtime-patch precedent). No manifest field changed/added/removed. |
| `1.23` | 1.46.2 | **`.vx` pinned to `text/plain` (patch, SCHEMA unchanged, LOGIC values-move).** The v1.46.0 Windows shakedown was expanded (v2) with a systematic MIME-registry sweep; it found `.vx` is the last of the `.csv`-class flips: `mimetypes.guess_type(".vx")` is None on every OS, so on the no-libmagic Windows path it fell back to `application/octet-stream` (a binary type) → `is_binary` flipped True, while Linux libmagic reads it `text/plain`. Pinning `text/plain` aligns every OS (keeps `matches_extension` true vs the libmagic reading; the `.toml`/`.csv` precedent). Changes `.vx` `extension_mime` None→text/plain and `is_binary` on the no-libmagic path → `manifest_checksum` moves for `.vx`-bearing manifests (a values-move — no new field, no routing flag flip; no `.vx` in any corpus → sweep NO-DRIFT). `LOGIC_VERSION` 1.24.1→1.24.2; `SCHEMA_VERSION` unchanged (1.23). No existing field changed/removed/retyped. |
| `1.23` | 1.46.1 | **`csv_headers` gains its `signal_provenance` entry (patch, SCHEMA unchanged, LOGIC values-move).** A pre-existing gap (#156, surfaced in the v1.46 review): `structural.csv_headers` was extracted with no per-field `signal_provenance` entry while its siblings (`structural.title`, `structural.document_keys`) had one. v1.46.1 emits it (a new `csv_header_row` trigger). This adds a provenance key on CSV-with-headers files → `manifest_checksum` **moves for CSV-bearing manifests** (a values-move — no new manifest field, no routing flag flip; the v1.8.2/v1.9.1/v1.25.1 provenance/determinism-patch precedent). `LOGIC_VERSION` 1.24.0→1.24.1; `SCHEMA_VERSION` unchanged (1.23). No existing field changed/removed/retyped. |
| `1.23` | 1.46.0 | **Native-Windows / NTFS hardening (SCHEMA unchanged, cross-platform LOGIC bump).** From a native-NTFS shakedown. (A) **reparse-aware discovery containment** — discovery now enumerates with `os.walk` and **prunes NTFS junctions / reparse-point dirs *before* descending into them** (Windows-only). `rglob` descended into junctions (they aren't symlinks, so the `is_symlink()`-gated check missed them) *and materialized the whole walk first*, so a crafted out-of-tree or cyclic junction could escape the tree, double-count, or hang/OOM the scan before any per-file filter ran. Directory-level pruning closes all three before any file is materialized, and fails closed via `resolve()`-containment on an inconclusive attribute read. POSIX is byte-identical (`os.walk(followlinks=False)` omits symlinked dirs exactly as `rglob` did; the v1.8.1 file-symlink containment is retained). (B) pin **`.csv → text/csv`** so a plain-text CSV isn't typed *binary* by the Windows MIME registry's `application/vnd.ms-excel` on the no-libmagic path (which flipped `is_binary` and dropped `csv_headers`). (C) byte-safe `--watch`/`--schema` stdout (UTF-8 via `stdout.buffer`, mirroring the already-safe main `--stdout`, so a non-ASCII payload doesn't crash a cp1252 console — output routing only). A+B are cross-platform routing-LOGIC changes: **Linux real-corpus output is byte-identical** (A skips only out-of-tree-resolving files, which v1.8.1 already skipped for file symlinks; B is a no-op on Linux) → sweep NO-DRIFT; the new behavior is Windows-only. Per Pillar 1, fo is not byte-identical across OS (platform is a `ScanContext` field) — A+B make the Windows manifest *closer* to the Linux one. `LOGIC_VERSION` 1.23.0→1.24.0 (the v1.15 cross-platform-LOGIC precedent — the observing logic changed even though Linux bytes are unchanged); `SCHEMA_VERSION` unchanged (1.23). No field added/removed/retyped. |
| `1.23` | 1.45.0 | **Human summary decoupled from the checksum + refreshed (SCHEMA unchanged, one-time LOGIC bump).** The per-scan `summary` is a **derived view** of already-checksummed data (files/vectors/quality); it was inside `manifest_checksum`, so every prose refresh cost a `LOGIC_VERSION` bump. v1.45 **excludes the whole `summary` from the checksum** (joining `scan_id`/`generated_at`) — a **one-time ungated bump: every manifest's `manifest_checksum` moves once** (`LOGIC_VERSION` 1.22.0→1.23.0; the v1.15/v1.36 every-checksum-moves precedent) — after which summary refreshes are LOGIC-free forever. The summary stays **one coherent readable field** (a sidecar would fragment it). **Consequence (see §1.8/§1.9):** the `manifest_signature` is computed from the checksum, so the summary is now **outside both the checksum and the signature** — a non-sealed, unsigned, build-versioned derived view; trust the sealed machine fields (the summary is reconstructible from them). The refresh (rides free): the summary now surfaces the `lexicon` vector shape, a `fact_block` file count, and `ai_session` token sums (each gated on presence — a corpus without them renders an unchanged summary; ai_session tokens are counted, **never priced**). SCHEMA 1.23 unchanged (the `summary` field's shape is unchanged — only its role in the checksum). No field added/removed/retyped. |
| `1.23` | 1.44.0 | **Lexicon category breakdown survives `--trusted-only` (SCHEMA/LOGIC unchanged).** Safe mode (v1.40) previously nulled the lexicon per-category breakdown — category names are dynamic dict keys, dropped by the projection's attacker-label defense (a dict key can be attacker-controlled). But the whole lexicon path is counts (`fo_derived`) keyed by category names / a `lexicon_id` that are **consumer configuration — never bytes from a scanned file**. v1.44 names that third trust class **`consumer_config`** (trusted in safe mode) and keeps the lexicon per-category signal — the per-file `lexicon_match.categories` + the corpus `lexicon` vector `category_hits` now survive `--trusted-only` — via a relaxation scoped to the `lexicon_match` namespace only (every other namespace's dynamic keys stay dropped), a completeness guard, and a canary proving no file content rides along. A projection change → the DEFAULT manifest is **byte-identical**, so `LOGIC_VERSION`/`SCHEMA_VERSION` UNCHANGED (1.22.0 / 1.23; the v1.40 front-door precedent); the `--schema` field-level trust annotation is unchanged (`specialist_metadata` stays `mixed`), so `schema_doc_version` does not bump. Unblocks per-category tiered routing (#135). No existing field changed/removed/retyped. |
| `1.23` | 1.43.0 | **Lexicon source loader (distribution format + composition), SCHEMA/LOGIC unchanged.** How a consumer *sources* the bring-your-own lexicon moves from one flat JSON file to the way risk/blocklist term lists are actually distributed (uBlock/EasyList/hosts). Two accepted formats normalize to the same internal `{lexicon_id, categories}`: JSON (canonical, with optional load-time-only header keys `version`/`source`/`license`/`description`) + an EasyList-style **text** list (`! Title:` header, `[category]` sections, one-term-per-line, `!`/`#` comments; literal terms only). Composition: repeatable `--lexicon` flags (union+dedup, order-independent) + a `--lexicon-index` subscription file; `--lexicon-id` overrides the composed id. Source **provenance stays load-time-only** (a stderr summary) and NEVER enters the manifest — only the composed `lexicon_id` + `dictionary_id` cross, exactly as v1.38–v1.42. `dictionary_id` stays content-anchored (a version bump with identical terms → the same id). fo composes **local** files; it never fetches (the offline-deterministic charter). A projection-grade loader upgrade: an equivalent term set resolves byte-identical with the same `dictionary_id`, and the existing single flat JSON loads identically → `LOGIC_VERSION`/`SCHEMA_VERSION` UNCHANGED (1.22.0 / 1.23; the v1.26/v1.39 loader/front-door precedent). No manifest field changed/added/removed (the text/index formats are an *input* contract, not part of the manifest contract; the `lexicon_match` namespace they feed is unchanged). |
| `1.23` | 1.42.0 | **Screening receipt projection (`--receipt`), SCHEMA/LOGIC unchanged.** A new compact, audit-friendly output mode (CLI `--receipt`, MCP `receipt` param) that projects a built manifest into an envelope (`receipt_doc_version`, versions, `manifest_checksum` + `manifest_signature`, `scan_id`, `dictionary_id`) + a per-file record (`receipt_id`, `path_id`, `checksum_sha256`, `size_bytes`, `mime_type`, `safety_flags`, and a `lexicon` hit-summary when a lexicon ran). The **`receipt_id`** is a tamper-evident sha256 over a length-prefixed preimage of (`manifest_checksum` + relative path + `checksum_sha256`) — independently recomputable, the explicit join key a downstream read/skip log references (#133 + blah_mad). Safe by construction (no raw path — `path_id` correlates). fo never records the read/skip decision (the charter boundary). A projection of existing observation → the DEFAULT manifest is byte-identical, so `LOGIC_VERSION`/`SCHEMA_VERSION` are UNCHANGED (1.22.0 / 1.23; the v1.26/v1.28/v1.37/v1.40 front-door precedent); a new `receipt_doc_version` (starts at 1) versions the receipt envelope shape. No existing field changed/removed/retyped. See §1.14. |
| `1.23` | 1.41.0 | **Lexicon self-sweep over file-derived metadata.** The v1.38 lexicon scans a file's BODY; a risk term can hide in metadata the body scan never sees (a filename, an EXIF make/model, a PDF producer/title/author, an office application string). v1.41 reuses the `_lexicon_scan` matcher over the collected file-derived metadata strings (filename [not the full path] + tags + frontmatter + structural + the string leaves in `specialist_metadata`, minus `content_preview` and the `lexicon_match` namespace) and reports the result in a new provisional `lexicon_match.metadata` sub-block (`{categories, total_hits, total_tokens}`), kept SEPARATE from the body so a consumer sees WHERE. Binary files (images/PDFs/office) get no body scan but do carry metadata hits, so the sweep creates the namespace with a zero body block. The existing `lexicon_match` safety_flag now fires on a body OR metadata hit. Metadata text capped at `LEXICON_METADATA_MAX_CHARS` (64 KiB). Dormant without a lexicon → existing manifests byte-identical. `LOGIC_VERSION` 1.21.0→1.22.0 (values move on lexicon scans only; lexicon method_version 1→2). SCHEMA 1.22→1.23 (a new field in an existing namespace = additive contract change); provisional. No existing field changed/removed/retyped. |
| `1.22` | 1.40.0 | **Field trust classification + `--trusted-only` safe mode (SCHEMA/LOGIC unchanged).** Every FileRecord field is classified `fo_derived` (trusted — numbers/booleans/hashes/timestamps/enums/flags, cannot carry a free-text payload) vs `file_derived` (untrusted / attacker-controllable — filenames, paths, `content_preview`, tags, frontmatter, extracted metadata *strings*), via a first-class `FIELD_TRUST` registry (completeness-guarded). Two surfaces consume it: (a) `--schema` field descriptors gain a `trust` attribute (`schema_doc_version` 2→3 — a build-time interface, not the manifest contract); (b) a new `--trusted-only` output mode (CLI flag, `ScannerConfig(trusted_only=True)`, MCP tool param + server flag) emits a PROJECTION that keeps only the trusted fields, nulls the file-derived strings, and adds a fo-derived `path_id` (sha256 of the path) as a correlation handle + a top-level `trusted_only: true` marker — safe by construction to feed a downstream model. A projection of existing observation (no new observation, no sanitization): the DEFAULT manifest is **byte-identical**, so `LOGIC_VERSION`/`SCHEMA_VERSION` are UNCHANGED (1.21.0 / 1.22) — the v1.26/v1.28/v1.37 front-door precedent. No existing field changed/removed/retyped. |
| `1.22` | 1.39.0 | **MCP front-door gains lexicon + delta (SCHEMA/LOGIC unchanged).** The v1.37 MCP server predated v1.38 lexicon; v1.39 threads the lexicon (server-startup `--lexicon` flag — the private terms never cross the MCP wire, only term-free counts) + delta (`previous_manifest_path` tool param) through the existing tools. A front-door: the manifest is byte-identical to a CLI scan with the same `--lexicon`/`--previous-manifest` settings, so nothing observable changes. `LOGIC_VERSION`/`SCHEMA_VERSION` UNCHANGED (1.21.0 / 1.22) — the v1.26/v1.28/v1.37 front-door precedent. `mcp` stays an optional dep. No existing field changed/removed/retyped. |
| `1.22` | 1.38.1 | **`--version`/`-V` CLI flag (patch), SCHEMA/LOGIC unchanged.** Prints `file-observer X.Y.Z` to stdout and exits 0 — un-breaks downstream version probing (recall's `doctor` read the usage banner and false-positived fo as below-floor; #126). Runtime-only output, no manifest change (the `--workers`/`--watch`/`--stdout` precedent). `LOGIC_VERSION`/`SCHEMA_VERSION` unchanged (1.21.0 / 1.22). No existing field changed/removed/retyped. |
| `1.22` | 1.38.0 | **Bring-your-own-lexicon term observer.** A new provisional `lexicon_match` specialist namespace (`lexicon_id`, `categories` [`{cat: {count, density}}`], `total_hits`, `total_tokens`) + a `lexicon_match` safety_flag + a `lexicon` vector + a `lexicon_full_file` provenance trigger. When a consumer supplies a category-tagged lexicon (`--lexicon` / `ScannerConfig(lexicon=…)`), fo counts each category's terms (word-boundary, case-folded, literal token(-sequence) match — measure-first: substring over-counts 9.4×) in every text file, over a **full-file bounded read** (64 MiB; a risk term can sit anywhere in a long log), and reports per-category counts + density — an **observation, never a verdict** (the consumer thresholds). Motivated by knowing a file is a guardrail-trip risk *before* handing it to an AI (fo is not an AI → safe to read what an LLM couldn't). **Values-neutral engine**: the mechanism ships empty; the terms are **consumer-private runtime config** — excluded from `meta.config`, **never echoed into the manifest** (only counts, category names, and a content-hash `dictionary_id` that moves on any term change → catches silent lexicon drift). **Dormant when no lexicon is supplied** → existing manifests byte-identical; `manifest_checksum` moves only for lexicon-supplied scans (the v1.30 gated-feature precedent). `LOGIC_VERSION` 1.20.0→1.21.0 (a new baseline derivation; no routing flag flips). SCHEMA 1.21→1.22 (new namespace + vector + safety_flag + trigger = additive contract-shape change); all provisional. No existing field changed/removed/retyped. |
| `1.21` | 1.37.0 | **MCP server (agent-native front-door, SCHEMA/LOGIC unchanged).** A new `file-observer-mcp` stdio entry point + `[mcp]` extra exposes fo's EXISTING manifest / summary / schema through the Model Context Protocol (read-only, deterministic; 4 tools with progressive disclosure). A NEW SURFACE — the manifest returned is **checksum-identical to `scan()`** (byte-identical modulo the volatile `scan_id`/`generated_at`), so nothing observable changes. `LOGIC_VERSION` / `SCHEMA_VERSION` UNCHANGED (1.20.0 / 1.21) — the v1.26 `scan()` / v1.28 `--stdout` / GitHub-Action front-door precedent. `mcp` is an optional dep; the runtime stays zero-required-dep. No existing field changed/removed/retyped. |
| `1.21` | 1.36.0 | **defusedxml → purexml XML-dependency changeover (SCHEMA unchanged).** fo's XML hardening (OOXML/ODF specialists + the structural XML-keys tier) moves from `defusedxml` to **purexml** — a pure-stdlib, zero-dependency, oracle-gated-to-defusedxml drop-in (MIT), capability-proven **2,695/0** on fo's own corpus. fo OPTS INTO purexml's structural caps (`max_depth`=1000 / `max_attributes`=256 / `max_bytes`=100 MiB) — so it now REFUSES a pathologically-deep/attribute-flooded/oversized XML that defusedxml dutifully parsed (a catchable `LimitExceeded` ⊂ `ValueError` → the field degrades to null/error, never a crash). **Parse output byte-identical on real files** (2,695/0); output changes ONLY on pathological XML inputs → `LOGIC_VERSION` 1.19.0→1.20.0 (the v1.30.2 bounded-observation precedent; no routing flag flips). **⚠ `manifest_checksum` moves on EVERY manifest:** `ScanContext.dependencies` records `purexml` (name+version+applied limits) in place of `defusedxml`, and the dependency record is part of every manifest's context — so the checksum moves universally (as any dependency version bump would; Pillar 1: ScanContext exists to explain environment variance), while every extracted value is unchanged. The no-purexml stdlib fallback stays unhardened + un-capped (LIMITATIONS). SCHEMA unchanged (1.21) — no field/shape change. No existing field changed/removed/retyped. |
| `1.21` | 1.35.0 | **AI-session per-model usage attribution.** A new provisional `ai_session.usage_by_model` — a deterministic list (real models sorted, `null` bucket last) of per-model token-usage **sums** (same canonical fields as the session `usage`), keyed on the model **co-located** with each usage dict (Claude Code `message.model` / OpenAI `response.model` / Gemini `modelVersion`, all measured 100% co-located). **Invariant:** `usage` == elementwise sum of `usage_by_model` — the tested v1.33 session path is untouched, so the session `usage` block stays byte-identical. Model **verbatim** including non-model markers (e.g. `<synthetic>`); a usage-turn naming no model, and a hostile-cardinality overflow beyond `AI_SESSION_MAX_MODELS`, fold into the `model: null` bucket (sums stay complete). **Observe-only: sums are never priced.** `LOGIC_VERSION` 1.18.0→1.19.0 (values move `manifest_checksum` on ai_session corpora — the v1.29/v1.33 values-move precedent; no routing flag flips); ai_session `method_version` 1→2. SCHEMA 1.20→1.21 (a new field in an existing namespace = additive contract change); provisional. No existing field changed/removed/retyped. |
| `1.20` | 1.34.0 | **Chatlog session axes.** Three new provisional flat scalars in the `chatlog` namespace: `first_timestamp`/`last_timestamp` (min/max turn timestamp over the recognized-key set `timestamp`/`created_date`/`create_time`/`created_at`, parsed from ISO-string-or-epoch → **canonical ISO-8601 UTC** `…Z`/ms; null when untimestamped) + `cwd` (the session's first-seen working directory, verbatim/bounded; null when absent). Deterministic pure function of the file — observe, don't derive; a consumer gets a time axis + a project attr on the session node. `LOGIC_VERSION` 1.17.0→1.18.0 (new observed values move `manifest_checksum` on timestamped/cwd-bearing chatlog corpora — the v1.29/v1.33 values-move precedent; no routing flag flips, `is_chatlog` unchanged). SCHEMA 1.19→1.20 (new fields, provisional); chatlog method_version 10→11. No existing field changed/removed/retyped. |
| `1.19` | 1.33.0 | **AI-session observation, increment 1.** New provisional `ai_session` namespace on `is_chatlog`-detected AI session logs (Claude Code / OpenAI / Gemini): token-usage **sums** (`usage` sub-block — `turns_with_usage` + canonical `input_tokens`/`output_tokens`/`cache_read_tokens`/`cache_creation_tokens`/`reasoning_tokens`/`total_tokens`, null-per-absent, vendor `raw_keys` preserved) + a **producer-schema fingerprint** (`vendor`/`surface`/`models`/`id_prefix`/`object_types`/`schema_mismatch`) anchored on id-prefix + object-type (the usage-key vocab is NOT a reliable tell — OpenAI Responses collides with Anthropic on `input_tokens`). **Observe-only: sums are never priced.** `LOGIC_VERSION` 1.16.0→1.17.0 (values move `manifest_checksum` on AI-session corpora — the v1.29 values-move precedent; no routing flag flips). SCHEMA 1.18→1.19 (a new namespace = contract-shape change); new fields provisional. No existing field changed/removed/retyped. |
| `1.18` | 1.32.0 | **Generic kv-fact-block specialist (FR #114).** New provisional `fact_block` namespace (`pair_count`/`pairs`/`duplicate_keys`): when a text file's BODY (frontmatter stripped) is dominated by `key: value` lines, fo emits the observed pairs **verbatim + generic** (never a per-consumer schema; no validation/normalization — the consumer interprets). Content-detected like `is_chatlog` — the FALLBACK observer for a text body no dedicated specialist owns; a sentence-value veto keeps it off dialogue (measure-first: fact-blocks 497/497, prose 0/397, dialogue 0/60). New `is_fact_block` derived flag; `requires_specialist_tool` flips False→True on a matching no-specialist text body (`LOGIC_VERSION` 1.15.3→1.16.0 — the v1.2/v1.29 detection-LOGIC precedent; additive, False→True only). SCHEMA 1.17→1.18 (a new namespace = contract-shape change); new fields provisional. No existing field changed/removed/retyped. |
| `1.16` | 1.30.1 | **Self-inclusion skip anchored to the actual output dir (patch, red-team hardening), schema unchanged.** The v1.30.0 self-inclusion skip matched a bare directory name (`file-observer-manifests`) at any depth, so an UNRELATED user directory of that name was silently dropped from the manifest (leg-2/OpenAI red-team: silent data loss; also missed on case-insensitive filesystems). v1.30.1 anchors the skip to fo's **actual resolved output directory** (a prefix-match on its path relative to the source, `normcase`), driven by a runtime `skip_output_dir` (the CLI's own output dir; excluded from `meta.config`) — so ONLY fo's own output is skipped; an unrelated same-named dir is scanned normally. Also: the CLI output write is now wrapped → a non-writable output path fails loud (`rc=1`) instead of a traceback (`#110` moved output to the user-controlled cwd). `manifest_checksum` moves ONLY for a tree that contains an unrelated `file-observer-manifests` dir (now included); the API never skips (it writes nothing). `LOGIC_VERSION` 1.15.1→1.15.2; `SCHEMA_VERSION` unchanged (1.16). No manifest field/shape change. |
| `1.16` | 1.30.0 | **CLI robustness — fail-loud on invalid input + default output relocated, schema unchanged.** fo now errors (`rc=2`) before scanning on a **nonexistent or non-directory source**, `--workers < 1`, and `--preview-max < 0` (a missing `--previous-manifest` **warns**, not errors) instead of silently returning a successful empty manifest — the worst outcome for the stack fo sits under (a typo'd source silently empties the index + search downstream). And the **bare default output** moves out of the installed package directory to `./file-observer-manifests/` in the cwd (runtime data must not be written into the code tree). `-o`/`--stdout` are unchanged → callers that pass `-o` (trellis/recall) are unaffected. To prevent self-inclusion (a re-scan of the cwd observing its own output), **discovery now skips a `file-observer-manifests/` directory** — so a **valid scan is byte-identical EXCEPT for a tree that contains fo's own output dir** (which is now skipped; the empty-real-dir case is preserved: 0 files is a valid observation). `LOGIC_VERSION` 1.15.0→1.15.1 (the discovery skip — `manifest_checksum` moves only for a tree containing that dir; the v1.8.1 symlink-skip precedent); `SCHEMA_VERSION` unchanged (1.16). No manifest field/shape change. Surfaced by bestiary (#109/#110) via the GitHub-issues feedback model. |
| `1.16` | 1.28.0 | **`--stdout` (manifest to stdout), schema unchanged.** A new CLI flag writes the manifest to stdout (no file, no report) so a one-shot scan composes in a pipe (`file-observer . --stdout \| jq`) and a container can emit it cleanly. Output routing only — the emitted manifest is **byte-identical** to the file the same invocation would write; respects `--format json\|jsonl`; mutually exclusive with `--output` and `--watch`. `LOGIC_VERSION` unchanged (1.14.1); `SCHEMA_VERSION` unchanged (1.16). No manifest field/shape change. |
| `1.16` | 1.27.0 | **JSON Schema artifact for the manifest, schema unchanged.** A committed, generated `docs/manifest.schema.json` (JSON Schema draft 2020-12) describing the manifest — for any-language validation/codegen — emitted by `file-observer --schema --schema-format json-schema`. Generated from the manifest dataclasses (single source of truth); the stable core is typed strictly, the namespace-keyed/provisional dicts are open objects. The schema artifact is a **build-time interface** versioned by `$id` (carries `schema_version`); pin the MAJOR of `schema_version` (the same MAJOR-pin a consumer already uses). The JSON Schema *describes* the existing manifest — it changes nothing the scanner emits. `LOGIC_VERSION` unchanged (1.14.1); `SCHEMA_VERSION` unchanged (1.16). No manifest field/shape change. |
| `1.16` | 1.26.0 | **One-call public API (`scan` / `scan_to_json`), schema unchanged.** New top-level convenience functions: `from file_observer import scan; m = scan("./folder")` (and `scan_to_json(...)`), thin wrappers over the existing `Scanner`/`ScannerConfig` path. The **import/Python API is not under this contract** (the *manifest* is — the v1.0.1 precedent), so this is purely additive ergonomics: the produced manifest is **byte-identical** to the explicit path. `LOGIC_VERSION` unchanged (1.14.1); `SCHEMA_VERSION` unchanged (1.16). No manifest field/shape change. |
| `1.16` | 1.25.1 | **OLE2 full-file deviation provenance (patch), schema unchanged.** The OLE2 path-reading specialists (`.doc`/`.xls`/`.msg`/`.ppt`) hand `olefile` the filesystem path and read property streams from anywhere in the compound file — NOT the 8 KB sample — yet their `signal_provenance` reported `trigger="bounded_sample"` + `detail.sample_size` (false). Now they declare a deviation: `trigger="bounded_deviation"`, `detail.reason="ole2_full_file_required"` (no fixed byte budget — bounded by file size on disk). **Provenance-accuracy only — no extracted VALUE changes** — but `signal_provenance` is part of the manifest, so `manifest_checksum` moves for any manifest containing OLE2 files. Surfaced as a leg-4/Codex P2 on PR #98 (v1.25.0); fixed for the whole OLE2 family at once (pre-existing, family-wide) rather than diverging `.ppt`. `LOGIC_VERSION` 1.14.0→1.14.1 (manifest-surface change, the v1.8.2/v1.9.1 precedent). No existing field changed/removed/retyped. |
| `1.13` | 1.22.1 | **`.eml` MIME-guard relaxation (patch), schema unchanged.** Real `.eml` whose body dominates (HTML mail, quirky leading headers) is typed by libmagic as `text/plain`/`text/html`, not `message/rfc822`; the OLE2-shaped `email` guard rejected those, so the email specialist was skipped on ~38% of real `.eml` (envelope lost). Now `text/plain`/`text/html` are accepted for **`.eml` specifically** — `.msg` stays OLE2-only, so a lying text-typed `.msg` remains distrusted (extension-gated, the v1.15.2 discipline). Recovers full envelope (subject/from/to/date) on the affected `.eml`; `.msg` and `message/rfc822` `.eml` unchanged. `LOGIC_VERSION` 1.12.0→1.12.1 (extraction-dispatch). No existing field changed/removed/retyped. |
| `1.13` | 1.22.0 | **Content-aware recognition for binary, schema unchanged.** Completes the v1.21 arc: `unsupported_extension` no longer fires when a file's CONTENT is positively identified — text (v1.21) OR binary (v1.22; e.g. `video/x-msvideo`, `application/zip`, `audio/mpeg`). It fires only when content detection genuinely failed: octet-stream, an extension-fallback MIME (both content tiers failed → `mimetypes`), or unreadable. Recognition gates on observed content (a content-derived MIME, never the extension fallback); **recognition ≠ extraction** — a recognized binary still has no specialist and no new metadata (byte-identical specialist output). `supported`/`degraded` counters shift for binary-with-unlisted-extension; `supported` is now single-source (not-flagged AND not-stat-failure). `LOGIC_VERSION` 1.11.0→1.12.0. No existing field changed/removed/retyped. |
| `1.13` | 1.21.2 | **`--schema` document shape formally committed (patch), schema unchanged.** The `--schema --format json` envelope becomes a binding build-time interface versioned by `schema_doc_version` (= `2`): top-level `scanner_version`/`logic_version`/`schema_version`/`schema_doc_version` + the structural sections + enumerations, with `manifest` = `{RecordName: [{name, type, stability}]}`; a backward-incompatible *shape* change bumps `schema_doc_version`. The field *inventory* is not frozen by this (it grows additively, tracked by `SCHEMA_VERSION`); a `stable`-marked field keeps its §6 promise, so reading stable field names off `--schema` is as safe as reading the manifest. See §1.12. Prompted by the first real `--schema` consumer (gazetteer). Byte-identical scan output; `LOGIC_VERSION`/`SCHEMA_VERSION` unchanged (1.11.0 / 1.13); `schema_doc_version` unchanged (the shape is committed, not changed). No existing field changed/removed/retyped. |
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
