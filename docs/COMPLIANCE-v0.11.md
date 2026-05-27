# v0.11 Spec Compliance Report

**Report Date:** 2026-05-27
**Spec:** docs/v0.11.0_RFC_Specification.md
**Implementation:** src/scanner/scanner.py (v0.11.0, main branch)
**Prior Compliance:** docs/COMPLIANCE-v0.10.md (v0.10 — 82 requirements, all PASS)

---

## 1. Executive Summary

- **Spec Version:** v0.11.0 RFC Specification (Approved 2026-05-27)
- **Implementation Version:** 0.11.0
- **Schema Version:** 0.11 (stability promotion — no structural changes over 0.10)
- **Overall Compliance Assessment:** COMPLETE — all acceptance criteria in §6 satisfied. Five fields promoted from provisional to stable. SECURITY.md added. No behavioral changes.
- **Test Count:** 564 passed, 1 skipped (unchanged from v0.10.2 — no new behavior to test).
- **Critical Deviations:** None.

---

## 2. Provisional → Stable Promotions (§2)

### 2.1 Promotion Decisions

| # | Field | Location | Introduced | Patches survived | Spec decision | Implementation | Status |
|---|---|---|---|---|---|---|---|
| 1 | `vectors_collected[]` | `ScanManifest` | v0.9 | v0.9.1, v0.9.2, v0.10.0, v0.10.1, v0.10.2 | STABLE | PUBLIC_CONTRACT.md §1.2: "Stable (since 0.9, promoted 0.11)" | **PASS** |
| 2 | `reference_tokens` | `FileRecord` | v0.9 | v0.9.2, v0.10.0, v0.10.1, v0.10.2 | STABLE | PUBLIC_CONTRACT.md §1.3: "Stable (since 0.9, promoted 0.11)" | **PASS** |
| 3 | `quality.per_directory_summary[]` | `ScanQuality` | v0.9 | v0.10.0, v0.10.1, v0.10.2 | STABLE | Promoted via §2.4 update | **PASS** |
| 4 | `specialist_metadata.email.body_chatlog` | `email` namespace | v0.9 | v0.10.0, v0.10.1, v0.10.2 | STABLE | Promoted via §2.4 update | **PASS** |
| 5 | `filename_patterns` | `FileRecord` | v0.10 | v0.10.1, v0.10.2 | STABLE | PUBLIC_CONTRACT.md §1.3: "Stable (since 0.10, promoted 0.11)" | **PASS** |

### 2.2 Promotion Semantics

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 6 | Promoted fields present in every manifest | All five fields already present since their introduction; no change needed | **PASS** |
| 7 | Promoted fields cannot be removed without MAJOR bump | Documented in PUBLIC_CONTRACT.md stability annotations | **PASS** |
| 8 | Promoted fields cannot change type without MAJOR bump | Documented in PUBLIC_CONTRACT.md | **PASS** |
| 9 | New sub-fields may be added in MINOR releases | Consistent with existing additive-only policy | **PASS** |

### 2.3 Remaining Provisional Fields

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 10 | Only `format_signatures` and `is_polyglot` remain provisional | PUBLIC_CONTRACT.md §2.4 updated: lists only these two plus a note about v0.11 promotions | **PASS** |

---

## 3. SECURITY.md (§3)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 11 | File exists at project root | `SECURITY.md` present | **PASS** |
| 12 | Documents observation-only scope | §Scope: "reads files and emits metadata", lists 4 things scanner never does | **PASS** |
| 13 | Documents parsing risk accurately | Describes residual risk from native dependencies, recommends updates and sandboxing | **PASS** |
| 14 | Vulnerability reporting process | Email to security@russalo.com, 48h acknowledgment, 7-day assessment | **PASS** |
| 15 | Dependency security table | 5 dependencies listed with role and risk mitigation | **PASS** |
| 16 | defusedxml description accurate | "Used when available ... Falls back to stdlib" (not "replaces") | **PASS** |
| 17 | Bounded observation documented | Default 8KB, OOXML 128KB, OLE2 full file, ZIP traversal validation | **PASS** |
| 18 | Safety flags documented as observations | "observations, not assessments" — 4 flags listed | **PASS** |
| 19 | Supported versions table | 0.11.x (yes), 0.10.x (until 0.11 ships), <0.10 (no) | **PASS** |

---

## 4. Schema Impact (§4)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 20 | Schema version 0.10 → 0.11 | `SCHEMA_VERSION = "0.11"` | **PASS** |
| 21 | No new fields added | No new fields in scanner.py, FileRecord, or ScanManifest | **PASS** |
| 22 | No fields removed | All v0.10 fields present | **PASS** |
| 23 | No type changes | No type changes | **PASS** |
| 24 | LOGIC_VERSION unchanged | `LOGIC_VERSION = "0.10.1"` (no routing changes) | **PASS** |

---

## 5. Documentation Updates (§5)

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 25 | SCANNER_VERSION = "0.11.0" | Verified in scanner.py line 74 | **PASS** |
| 26 | SCHEMA_VERSION = "0.11" | Verified in scanner.py line 76 | **PASS** |
| 27 | Module docstring updated | Version 0.11.0, Schema 0.11, Spec v0.11.0 | **PASS** |
| 28 | PUBLIC_CONTRACT.md updated | Five fields promoted, §2.4 reduced, schema row added | **PASS** |
| 29 | CONVENTIONS.md version pointers | SCANNER_VERSION 0.11.0, SCHEMA_VERSION 0.11 | **PASS** |
| 30 | CLAUDE.md updated | Spec reference, version roadmap, architecture, known decisions all current | **PASS** |
| 31 | README.md updated | Version 0.11.0, schema 0.11, spec link | **PASS** |
| 32 | HISTORY.md row added | v0.11.0 row with promotions and SECURITY.md | **PASS** |
| 33 | pyproject.toml | version = "0.11.0" | **PASS** |

---

## 6. Acceptance Criteria (§6)

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 34 | All five fields promoted in PUBLIC_CONTRACT.md | §1.2, §1.3 updated with "Stable (since X, promoted 0.11)" | **PASS** |
| 35 | §2.4 reduced to format_signatures + is_polyglot | §2.4 lists only these two, plus promotion note | **PASS** |
| 36 | SECURITY.md exists at project root | File present, reviewed in PR #16 | **PASS** |
| 37 | Schema version is "0.11" | `SCHEMA_VERSION = "0.11"` | **PASS** |
| 38 | All v0.10 tests pass unchanged | 564 passed, 1 skipped — identical to v0.10.2 | **PASS** |

---

## 7. Compliance Verdict

**PASS — 38 requirements verified, 0 failures, 0 deviations.**

v0.11 is a governance release. Five fields promoted from provisional to stable based on survival through 2-5 patch releases without shape changes. SECURITY.md establishes the project's security posture. No behavioral changes, no new features, no new code — only stability commitments and documentation.
