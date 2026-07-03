# Compliance — file-observer v1.31.0

Maps the [v1.31.0 RFC](v1.31.0_RFC_Specification.md) to evidence. Written before merge.
**Verdict: compliant.** Designation-only promotion: the capture-metadata surface (`image` EXIF + the
entire `video` namespace) provisional → stable.

## Capability (RFC §2) → implementation
| Requirement | Implementation | Status |
|---|---|---|
| Promote the 6 image-EXIF + 10 video fields → stable | removed all 16 `(namespace, field)` tuples from `PROVISIONAL_SPECIALIST_FIELDS`; `--schema` now annotates them `stable`. Both the `image` and `video` namespaces are fully stable | **Met** |
| Designation-only — manifest data byte-identical | the registry feeds ONLY the `--schema` stability annotation; no extraction/routing/value logic touched; no `stability` key in the manifest; the EXIF/ISOBMFF parsers are untouched | **Met** |
| Image dimensions (width/height/bit_depth) already stable | never in the provisional set (stable since 0.5); unchanged | **Met** |
| Held sets NOT swept up | `presentation` (v1.24) + `audio` (v1.25) stay provisional (too young); chatlog family stays held (alpha-locked); `format_signatures`/`is_polyglot` stay held-by-design | **Met** |

## Acceptance bar (RFC §5, falsify-first) → `tests/test_v1_31.py`
| # | Clause | Result |
|---|---|---|
| 1 | all image-EXIF + all video fields annotated `stable`; both namespaces fully stable | ✅ `TestPromotedToStable::test_image_namespace_fully_stable` / `test_video_namespace_fully_stable` |
| 2 | none of the 16 tuples remain in `PROVISIONAL_SPECIALIST_FIELDS` | ✅ `test_promoted_tuples_out_of_provisional_registry` (+ `test_v1_14` drift guard updated) |
| 3 | designation-only — no `stability` leak, promoted values keep their shape, deterministic | ✅ `TestDesignationOnly` (3) |
| 4 | held sets stay provisional (chatlog / presentation / audio / format_signatures / is_polyglot) | ✅ `TestHeldSetsStayProvisional` (3) |
| — | version surfaces (SCANNER ≥1.31.0 / SCHEMA ≥1.17 / LOGIC ≥1.15.3) | ✅ `test_version_surfaces` |

Full suite: **1248 passed.** `docs/SCHEMA.md` + `docs/manifest.schema.json` regenerated; all drift-guards (README, contract-doc, version-sync, SCHEMA.md, JSON-Schema) green.

## Evidence-of-value (the v1.23 §6 hold resolution)
The v1.23.0 pass explicitly deferred the capture fields ("season first — days old; next pass, weeks out"). Now:
- **Settled logic:** the EXIF/TIFF-IFD reader (v1.16) and the ISOBMFF reader (v1.17–1.20) are unchanged since ship (~2–2.5 weeks).
- **Oracle-validated:** matched `exiftool` exactly — 61/61 real `.mov` (v1.17 container), real iPhone 16 clips (v1.18), and the `synth-video-capture` fixtures gated against exiftool (v1.18/v1.20).
- **Corpus-proven:** coverage was deliberately built for this pass (2026-06-28) — `wikimedia-exif` (70 real CC/PD photos: 70/70 make/model, 40 geotagged) + `synth-video-capture` (3 spec-valid `.mov` carrying Apple QuickTime keys).
- **Adversarially hardened:** the in-house capture-metadata red-team (2026-06-22) hit these exact parsers with 21 vectors → 0 bounds/crash/determinism violations, codified as `tests/test_capture_metadata_hardening.py`. (A decorrelated bestiary fuzz pass — bestiary#23 — is additionally in flight; belt-and-suspenders, not a gate.)

## Four-leg review
| Leg | Result |
|---|---|
| 1 · in-house (inline) | Clean — registry-only change; the 16 tuples feed ONLY the `--schema` annotation; the EXIF/ISOBMFF parsers, routing, and manifest values are untouched. `test_v1_31` + the updated `test_v1_14`/`test_v1_23` drift guards enforce the exact promote/hold split. |
| 2 · cross-model | _(pending — pre-PR)_ |
| 3 · determinism / sweep | `test_manifest_deterministic` (byte-identical repeat scan); no `stability` key in the manifest. A full corpus sweep is not differentially informative for a designation-only change — the manifest data is byte-identical (stability is a `--schema`-only surface), so the determinism + no-leak properties are the relevant evidence, and they're test-covered. |
| 4 · PR bots | on PR open |

## Version axes (RFC §6)
SCANNER 1.30.2→1.31.0; **SCHEMA 1.16→1.17** (promotion = contract change, the v0.11/v1.10/v1.14/v1.23 precedent); **LOGIC unchanged 1.15.3** (designation-only — no routing/value change).

**Checksum note (grounded via the cross-model leg):** `schema_version` is in the `manifest_checksum` preimage (verified empirically), so a SCHEMA bump moves the checksum for *every* manifest — the observed field VALUES are byte-identical, but a consumer pinning `manifest_checksum` will see it change on v1.31.0 (true of any SCHEMA bump; the sweep's "no-drift" compares the *stripped* data fingerprint with version stamps removed). "Designation-only" = no value changed, not "checksum stable."

## Residuals (per RFC §7)
- `presentation` (v1.24) + `audio` (v1.25) — held: too young; season first. Next promotion pass, weeks out.
- chatlog family — held (non-count redesign + Sentinel alpha-lock).
- Promotion freezes the field SHAPE, not the parser internals: a future bounded-safety fix (e.g. anything bestiary#23 surfaces) patches the EXIF/ISOBMFF reader without touching the frozen shape.
