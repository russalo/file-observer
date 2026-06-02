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
| `errors` | array of objects | **Stable** — error codes stable (see error code registry) |

### 1.4 Specialist Metadata Namespaces

`specialist_metadata` is keyed by **namespace**, not by extension. Multiple extensions may map to the same namespace.

| Namespace | Stability | Source extensions |
|---|---|---|
| `pdf` | Stable since 0.5 | `.pdf` |
| `image` | Stable since 0.5 | `.png`, `.jpg`, `.jpeg` |
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
| `image_structure` | `.png`, `.jpg`, `.jpeg` |
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
| `unsupported_extension` | universal | Extension not in supported set |
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
- `quality.duplicate_clusters`, `quality.duplicate_cluster_count`, `quality.redundant_file_count` — duplicate detection (provisional since v1.1)
- `quality.specialist_stats` — per-specialist attempted/succeeded/failed counts (provisional since v1.1)
- `specialist_metadata.chatlog.speaker_turn_counts`, `.speaker_turn_chars`, `.alternation` — per-speaker turn structure (provisional since v1.2)
- `errors[].detail` — optional structured error diagnostic (provisional since v1.2)

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
