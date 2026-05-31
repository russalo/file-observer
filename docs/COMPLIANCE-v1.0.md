# v1.0 Spec Compliance Report

**Report Date:** 2026-05-31
**Spec:** docs/v1.0.0_RFC_Specification.md (Approved 2026-05-28)
**Implementation:** src/file_observer/scanner.py (v1.0.0 as released; line references hold on the schema-identical v1.0.1 tree, where the file was renamed from `src/scanner/scanner.py`)
**Prior Compliance:** docs/archive/0.x/COMPLIANCE-v0.11.md (v0.11 — 38 requirements, all PASS)

---

## 1. Executive Summary

- **Spec Version:** v1.0.0 RFC Specification (Approved 2026-05-28)
- **Implementation Version:** 1.0.0 (current main: 1.0.1 — packaging/docs patch, schema and behavior unchanged)
- **Schema Version:** 1.0 (frozen — no structural change over 0.11)
- **Overall Compliance Assessment:** COMPLETE — all §7 acceptance criteria satisfied. v1.0 is a governance declaration: the schema is frozen, PUBLIC_CONTRACT.md is binding, and the backward-compatibility and deprecation policies are in effect. No new code, no new fields, no removals.
- **Test Count:** 564 passed, 1 skipped at v1.0.0 (unchanged from v0.11 — no new behavior). Current main: 571 passed, 1 skipped (the +7 are v1.0.1 packaging guards, not behavior).
- **Critical Deviations:** None.

This report audits the v1.0.0 release. Because v1.0.1 changed only the import-package name and documentation (no schema or routing change), every contract-level finding below holds unchanged on current `main`.

---

## 2. Stable Manifest Structure (§2.1)

All twelve stable top-level keys are present on `ScanManifest` (scanner.py:459). The manifest shape is identical to v0.11.

| # | Key | Type | Implementation | Status |
|---|---|---|---|---|
| 1 | `schema_version` | string | `ScanManifest.schema_version` = `SCHEMA_VERSION` ("1.0") | **PASS** |
| 2 | `context` | object | `ScanContext` | **PASS** |
| 3 | `meta` | object | `ScanMeta` | **PASS** |
| 4 | `stats` | object | `ScanStats` | **PASS** |
| 5 | `quality` | object | `ScanQuality` (includes `per_directory_summary[]`) | **PASS** |
| 6 | `routing_summary` | object | `RoutingSummary` | **PASS** |
| 7 | `delta` | object or null | `DeltaRecord \| None` | **PASS** |
| 8 | `manifest_checksum` | string | present | **PASS** |
| 9 | `manifest_signature` | object or null | `dict[str, str] \| None` | **PASS** |
| 10 | `files` | array | `list[FileRecord]` | **PASS** |
| 11 | `vectors_collected` | array | `list[dict]` (stable since 0.9, promoted 0.11) | **PASS** |
| 12 | `summary` | string | present (stable since 0.10) | **PASS** |

---

## 3. Stable FileRecord Fields (§2.2)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 13 | All PUBLIC_CONTRACT §1.3 fields present | `FileRecord` carries the full stable field set | **PASS** |
| 14 | `reference_tokens` stable | Present on `FileRecord` (stable since 0.11) | **PASS** |
| 15 | `filename_patterns` stable | Present on `FileRecord` (stable since 0.11) | **PASS** |
| 16 | `is_chatlog` stable | Present on `FileRecord` (stable since 0.8) | **PASS** |
| 17 | `safety_flags` stable | `safety_flags: list[str]` (stable since 0.7) | **PASS** |

---

## 4. Stable Specialist Namespaces (§2.3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 18 | `pdf`, `image`, `email`, `spreadsheet`, `document`, `chatlog` namespaces stable | All present in `SPECIALIST_NAMESPACE` / chatlog dispatch | **PASS** |
| 19 | `email.body_chatlog` stable since 0.11 | Present in the `email` namespace | **PASS** |

---

## 5. Stable Vectors (§2.4)

Four vectors ship at v1.0 with the method versions fixed by the spec.

| # | Vector | Required method_version | Implementation | Status |
|---|---|---|---|---|
| 20 | `chatlog` | 3 | `CHATLOG_METHOD_VERSION = 3` (scanner.py:536) | **PASS** |
| 21 | `reference_tokens` | 2 | `REFERENCE_TOKENS_METHOD_VERSION = 2` (scanner.py:564) | **PASS** |
| 22 | `author_aggregate` | 1 | `AUTHOR_AGGREGATE_METHOD_VERSION = 1` (scanner.py:612) | **PASS** |
| 23 | `filename_patterns` | 1 | `FILENAME_PATTERNS_METHOD_VERSION = 1` (scanner.py:585) | **PASS** |

---

## 6. Remaining Provisional Fields (§2.5)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 24 | Only `format_signatures` and `is_polyglot` remain provisional | PUBLIC_CONTRACT.md §2.4 lists exactly these two | **PASS** |

---

## 7. Backward Compatibility Policy (§3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 25 | Version semantics (MAJOR/MINOR/PATCH) documented | PUBLIC_CONTRACT.md §6 "Backward Compatibility Policy (since v1.0)" | **PASS** |
| 26 | Consumer guarantees (1.x forward-compatible; branch on MAJOR; ignore unknown fields) | PUBLIC_CONTRACT.md §0 (binding note, line 5) and §5 consumer guidance | **PASS** |
| 27 | Deprecation policy: ≥1 full MINOR of deprecation before MAJOR removal | PUBLIC_CONTRACT.md §6 ("Preceded by deprecation in at least one full MINOR release") | **PASS** |

### 7.1 Vector Identity Contract (§3.4)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 28 | Preimage shape `vector_id\|method_version\|rules_hash\|static_tuning_hash\|dynamic_tuning_hash\|dictionary_id` | `compute_vector_identity_digest` joins exactly these six with `"\|"` (scanner.py:403–410) | **PASS** |
| 29 | Hash function SHA-256, hex-encoded | `sha256(preimage.encode("utf-8")).hexdigest()` (scanner.py:411) | **PASS** |
| 30 | Null represented as literal `"null"` | `dynamic_tuning_hash or "null"`, `dictionary_id or "null"` (scanner.py:408–409) | **PASS** |
| 31 | Shape MUST NOT change without MAJOR bump | PUBLIC_CONTRACT.md §6: "preimage shape and hash function (SHA-256) MUST NOT change without a MAJOR version bump" | **PASS** |

---

## 8. Schema & Version Constants (§4)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 32 | `SCHEMA_VERSION` 0.11 → 1.0 | `SCHEMA_VERSION = "1.0"` (scanner.py:76) | **PASS** |
| 33 | `SCANNER_VERSION` 0.11.0 → 1.0.0 | `SCANNER_VERSION = "1.0.0"` at the v1.0.0 tag (scanner.py:74; now "1.0.1") | **PASS** |
| 34 | `LOGIC_VERSION` 0.10.1 → 1.0.0 | `LOGIC_VERSION = "1.0.0"` (scanner.py:75) | **PASS** |

---

## 9. Implementation & Documentation (§5)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 35 | Code changes limited to version constants | Only the three constants + docstring/pyproject changed at v1.0.0; no behavioral change | **PASS** |
| 36 | Module docstring updated (Version 1.0.0, Schema 1.0, Spec v1.0.0) | Verified in module docstring | **PASS** |
| 37 | PUBLIC_CONTRACT.md pre-1.0 disclaimer removed | Replaced by the binding note (line 5) | **PASS** |
| 38 | PUBLIC_CONTRACT.md marked binding | "This contract is binding as of v1.0 … obligations, not intentions" (line 5) | **PASS** |
| 39 | Backward-compatibility + deprecation policies documented | PUBLIC_CONTRACT.md §6 | **PASS** |
| 40 | CLAUDE.md / CONVENTIONS.md / README.md / HISTORY.md updated | Version roadmap, pointers, version table, and v1.0 row all present | **PASS** |
| 41 | pyproject.toml version 1.0.0; PyPI metadata (classifiers, description, URLs, license) | Present; published to PyPI as `file-observer` | **PASS** |

---

## 10. Acceptance Criteria (§7)

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 42 | `schema_version` is `"1.0"` | `SCHEMA_VERSION = "1.0"` | **PASS** |
| 43 | `SCANNER_VERSION` is `"1.0.0"` | scanner.py:74 at v1.0.0 tag | **PASS** |
| 44 | `LOGIC_VERSION` is `"1.0.0"` | scanner.py:75 | **PASS** |
| 45 | PUBLIC_CONTRACT.md pre-1.0 disclaimer removed | Confirmed | **PASS** |
| 46 | PUBLIC_CONTRACT.md marked binding | Confirmed (line 5) | **PASS** |
| 47 | Backward-compatibility and deprecation policies documented | PUBLIC_CONTRACT.md §6 | **PASS** |
| 48 | All v0.11 tests pass unchanged (no behavioral changes) | 564 passed, 1 skipped — identical to v0.11 | **PASS** |
| 49 | Compliance report written | This document | **PASS** |
| 50 | Published to PyPI as `file-observer` | Live on PyPI (v1.0.0 2026-05-28) | **PASS** |
| 51 | README updated with v1.0 badge/version | README version table at 1.0.0 | **PASS** |

---

## 11. Migration Notes (v0.11 → v1.0)

No migration *guide* is required in the §3.3 sense: v1.0 removes, renames, and retypes nothing. The manifest **structure** — every top-level key, FileRecord field, specialist namespace, and field type — is identical to v0.11.

One value-level change is consumer-visible and intentional: the top-level `schema_version` advances from `"0.11"` to `"1.0"` (and `context.scanner_version` / `context.logic_version` advance accordingly). This is the signal that the stability contract is now binding — not a structural change. Implications:

- Consumers that follow PUBLIC_CONTRACT.md guidance — **branch on the MAJOR component** and **ignore unknown fields** — accept the entire `1.x` line and need no changes.
- Consumers that pin or allowlist an exact `schema_version` value (e.g. accept only `"0.11"`) MUST add `"1.0"` (or switch to MAJOR-component branching). This is the documented, expected handling of a schema-version bump.

Manifests are therefore **structurally compatible** with v0.11 but **not byte-identical** — the `schema_version` and other version strings differ by design.

---

## 12. Compliance Verdict

**PASS — 51 requirements verified, 0 failures, 0 deviations.**

v1.0 is a governance release. The schema is frozen, PUBLIC_CONTRACT.md is binding, and the backward-compatibility, deprecation, and vector-identity contracts are documented and implemented as specified. No new features, no new fields, no new code beyond version constants. Validated across 12 corpora / 28,756 files with zero fatal errors (RFC §6).
