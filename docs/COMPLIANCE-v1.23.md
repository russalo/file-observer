# Compliance — file-observer v1.23.0

Maps the [v1.23.0 RFC](v1.23.0_RFC_Specification.md) to evidence. Written before merge.
**Verdict: compliant.** Designation-only promotion: `preservation` provisional → stable.

## Capability (RFC §2) → implementation
| Requirement | Implementation | Status |
|---|---|---|
| `preservation` (field + vector) promoted to stable | removed `"preservation"` from `PROVISIONAL_VECTORS` (now empty) and `("FileRecord","preservation")` from `PROVISIONAL_MANIFEST_FIELDS`; `--schema` annotates both `stable` | **Met** |
| Designation-only — manifest data byte-identical | the registries feed ONLY the `--schema` stability annotation; no extraction/routing/value logic touched; no `stability` key in the manifest | **Met** |
| `format_signatures`/`is_polyglot` reclassified held-by-design | §2.4 updated (permanently-informational, NOT promotion candidates); they STAY in `PROVISIONAL_MANIFEST_FIELDS` | **Met** |
| Capture fields + chatlog NOT swept up | image/video stay provisional (season); chatlog family stays held | **Met** |

## Acceptance bar (RFC §4, falsify-first) → `tests/test_v1_23.py` (8, failing-first)
| # | Clause | Result |
|---|---|---|
| 1 | `--schema` annotates preservation vector + FileRecord field `stable` | ✅ `test_preservation_promoted_to_stable` |
| 2 | preservation out of both provisional registries | ✅ `test_preservation_out_of_provisional_registries` (+ `test_v1_14` drift guard updated) |
| 3 | designation-only — no `stability` leak, preservation values unchanged, deterministic | ✅ `TestDesignationOnly` (3) + workers 1-vs-4 byte-identical |
| 4 | format_signatures/is_polyglot STAY provisional | ✅ `test_held_by_design_fields_stay_provisional` |
| 5 | capture fields stay provisional | ✅ `test_capture_fields_stay_provisional` |
| — | version surfaces (1.23.0 / 1.14 / 1.12.1) | ✅ `test_version_surfaces` |

Full suite: **1074 passed.** SCHEMA.md regenerated; all drift-guards (README, contract-doc, version-sync, SCHEMA.md) green.

## Evidence-of-value (the v1.14 hold resolution, corpus-grounded 2026-06-19)
19,488 files, all carry `preservation`: 19,319 `current` / 155 `at_risk` (legacy MS Office .doc/.xls/.ppt, CAD .dwg/.dgn, .eps) / 14 `obsolete` (Flash .swf, WordPerfect .wpd/.wp, Lotus .wks/.wq1, old OpenOffice .sxc/.sxw); `migration_recommended=True` correctly on the 14 obsolete. Accurate, meaningful, not noise. (`scratch/promotion_readiness_audit_2026-06-19.md`.)

## Four-leg review
| Leg | Result |
|---|---|
| 1 · in-house (inline) | Clean — registry-only change feeds only the `--schema` annotation; manifest data untouched |
| 2 · Gemini cross-model (flash) | Clean — confirmed designation-only, no scan-output impact, no other field's stability flipped, no determinism issue |
| 3 · determinism | workers 1-vs-4 byte-identical; no `stability` key in the manifest; preservation values present. (A full corpus sweep is not differentially informative for a designation-only change — the manifest data is byte-identical; the determinism + no-leak properties are the relevant evidence, test-covered.) |
| 4 · PR bots | on PR open |

## Version axes (RFC §5)
SCANNER 1.22.1→1.23.0; **SCHEMA 1.13→1.14** (promotion = contract change, v0.11/v1.10/v1.14 precedent); **LOGIC unchanged 1.12.1** (designation-only).

## Residuals (per RFC §6)
- Capture fields (image EXIF, video) — season first (days old); next promotion pass, weeks out (image-EXIF leads; video-GPS Apple-only-validated).
- chatlog family — held (non-count redesign + Sentinel alpha-lock).
- The `preservation` closed table may still grow additively (more formats), rules-hash-tracked — an additive value change, not a field-shape change (the `provenance` precedent).
