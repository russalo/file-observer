# File Observer Project Conventions

File Observer has two kinds of conventions:

- **Internal conventions** — how *we* keep the project consistent. Naming, version bump rules, document promotion paths, tracking inventories. These exist for the contributors, not for users.
- **Public contracts** — what *consumers* of the manifest can count on. Schema versioning rules, namespace stability, fingerprint guarantees, deprecation policy. These exist for downstream systems and become commitments at v1.0.

This document covers the **internal** conventions. Public contracts live in `docs/PUBLIC_CONTRACT.md`.

---

## 1. Versioned Concerns (internal tracking)

The scanner has five distinct things that carry versions. They are independent — bumping one does not require bumping the others.

### 1.1 SCANNER_VERSION
**What it is:** Package release version (semver).
**Where it lives:** `pyproject.toml`, `SCANNER_VERSION` constant in `src/file_observer/scanner.py`, scanner module docstring, `meta.config` of every manifest, `manifest_v{version}_{timestamp}.json` filenames.
**When it bumps:** Any release.
**Format:** `MAJOR.MINOR.PATCH`
**Current:** `1.40.0`

### 1.2 LOGIC_VERSION
**What it is:** The version of the routing decision logic — code that decides `is_binary`, `requires_vision`, `requires_specialist_tool`, the SPECIALIST_TOOLS dict, SUPPORTED_EXTENSIONS, SPECIALIST_NAMESPACE.
**Where it lives:** `LOGIC_VERSION` constant in `src/file_observer/scanner.py`, `ScanContext.logic_version` in every manifest.
**When it bumps:** Any time the same file would route differently than before.
**Format:** `MAJOR.MINOR.PATCH`. May lag SCANNER_VERSION.
**Current:** `1.21.0`  (1.20.0→1.21.0 at v1.38.0 — bring-your-own-lexicon term observer: a new baseline-tier content derivation (per-category term counts + density on a consumer-supplied lexicon); manifest_checksum moves ONLY for lexicon-supplied scans (the v1.30 gated-feature precedent), no routing flip; 1.19.0→1.20.0 at v1.36.0 — defusedxml→purexml XML-dependency changeover: fo opts into purexml's structural caps (RECOMMENDED_LIMITS: max_depth=1000/max_attributes=256/max_bytes=100 MiB) → rejects pathologically-deep/oversized XML defusedxml parsed (output changes on PATHOLOGICAL input only, the v1.30.2 precedent; parse byte-identical on real files); ALSO ScanContext.dependencies records purexml in place of defusedxml → manifest_checksum moves on EVERY manifest (dep record is in every ScanContext, Pillar 1 explains it); no routing flip; prior 1.18.0→1.19.0 at v1.35.0 — AI-session per-model usage attribution (increment 3): a new provisional `ai_session.usage_by_model` (per-model token-usage sums, keyed on the co-located model) — VALUES move `manifest_checksum` on ai_session corpora (the v1.29/v1.33 values-move precedent → LOGIC bump), no routing flip, ai_session method_version 1→2; prior 1.17.0→1.18.0 at v1.34.0 — chatlog session axes (recall#62): three new flat chatlog scalars (first_timestamp/last_timestamp = min/max turn timestamp normalized to canonical ISO-8601 UTC; cwd = first-seen) — new observed values move `manifest_checksum` on timestamped/cwd-bearing chatlog corpora (the v1.29/v1.33 values-move precedent → LOGIC bump), no routing flip, is_chatlog unchanged, chatlog method_version 10→11; prior 1.16.0→1.17.0 at v1.33.0 — AI-session observation increment 1: a new `ai_session` namespace on is_chatlog-detected AI session logs carries token-usage sums + a producer-schema fingerprint; VALUES move `manifest_checksum` on AI-session corpora (the v1.29 values-move precedent → LOGIC bump), no routing flag flips; prior 1.15.3→1.16.0 at v1.32.0 — new content-detection routing: the generic kv-fact-block specialist (FR #114) sets `is_fact_block` + a `fact_block` dispatch on a text body that is a `key: value` block (additive: False→True only); prior UNCHANGED at v1.31.0 — the capture-metadata promotion is designation-only, no routing/value change; 1.15.2→1.15.3 at v1.30.2 — ReDoS/bounded-time hardening, 3 content regexes made linear; 1.15.1→1.15.2 at v1.30.1 — self-inclusion skip anchored to the resolved output dir; 1.15.0→1.15.1 at v1.30.0 — discovery skips fo's own default output dir; 1.14.1→1.15.0 at v1.29.0 — chatlog detection recognizes agentic (tool-turn) sessions: a turn with a conversational role + a text-bearing block (backward-compat) OR a distinctive agentic block (`thinking`/`tool_use`/`tool_result`) counts in detection AND turn-counting signals → `is_chatlog` routes additively (False→True, strict superset) on tool-heavy logs + chatlog `method_version` 9→10 (generic `image`/`document` excluded — leg-1 review FP fix); prior 1.14.0→1.14.1 at v1.25.1 — OLE2 specialists (`.doc`/`.xls`/`.msg`/`.ppt`) declare a full-file deviation in `signal_provenance` (`ole2_full_file_required`) instead of the false `bounded_sample` → manifest-surface change, the v1.8.2/v1.9.1 precedent; 1.13.0→1.14.0 at v1.25.0 — audio (`.mp3`) + legacy presentation (`.ppt`) extraction → `requires_specialist_tool` routing change; 1.12.4→1.13.0 at v1.24.0 — office+image extraction adds specialists for `.pptx`/`.odp`/`.odt`/`.ods`/`.jp2`/`.tiff`/`.tif` → `requires_specialist_tool` routing change; 1.12.3→1.12.4 at v1.23.3 — bzip2 dual-magic + `_OneOf` matcher, recognizes empty bzip2; 1.12.2→1.12.3 at v1.23.2 — corroborated PDF-header sniff: `%PDF-` window 256→1024 + structural corroboration; prior 1.12.1→1.12.2 at v1.23.1 — PDF-header FP fix)
**Internal rule:** When in doubt, bump it. Stale LOGIC_VERSION causes silent reproducibility bugs across environments.

### 1.3 SCHEMA_VERSION
**What it is:** Version of the manifest shape — what fields exist, what they're named, how they nest.
**Where it lives:** `SCHEMA_VERSION` constant, `manifest.schema_version` field, included in checksum preimage.
**When it bumps:**
- MINOR (0.x → 0.x+1): additive changes (new fields, new namespaces, new vectors)
- MAJOR (x.0 → x+1.0): breaking changes (removal, rename, type change)
- No bump for patch releases
**Format:** `MAJOR.MINOR` (no patch)
**Current:** `1.22`  (1.21→1.22 at v1.38.0 — new provisional `lexicon_match` namespace (lexicon_id/categories/total_hits/total_tokens) + `lexicon` vector + `lexicon_match` safety_flag + `lexicon_full_file` trigger for the bring-your-own-lexicon term observer; a new namespace/vector/flag = contract-shape change, all provisional; 1.20→1.21 at v1.35.0 — new provisional `ai_session.usage_by_model` field (per-model token-usage attribution); a new field in an existing namespace = additive contract change, provisional; 1.19→1.20 at v1.34.0 — three new provisional chatlog fields (first_timestamp/last_timestamp/cwd) for the recall#62 session axes; new fields = additive contract change, provisional; 1.18→1.19 at v1.33.0 — new `ai_session` namespace (vendor/surface/models/id_prefix/object_types/schema_mismatch/usage) for AI-session observation increment 1; a new namespace = contract-shape change, fields provisional; 1.17→1.18 at v1.32.0 — new `fact_block` namespace (pair_count/pairs/duplicate_keys) for the generic kv-fact-block specialist (FR #114); a new namespace = contract-shape change, fields provisional; 1.16→1.17 at v1.31.0 — promotion pass: image EXIF + the entire video namespace provisional→stable, designation-only (a promotion is a contract change; manifest byte-identical); 1.15→1.16 at v1.25.0 — new `audio` namespace (format/bitrate/duration_s/title/artist/album/year) for `.mp3`; `.ppt` reuses the existing `presentation` fields; 1.14→1.15 at v1.24.0 — new `presentation` namespace (slide_count/title/author/application); 1.13→1.14 at v1.23.0 — promotion: `preservation` provisional→stable, designation-only; 1.12→1.13 at v1.20.0 — the `video.creation_date_qt` field; 1.9→1.10/1.11/1.12 across v1.16–1.18 capture-metadata)
**Note:** This IS a public contract field. As of v1.0, downstream consumers depend on it. See `PUBLIC_CONTRACT.md` for the consumer-facing rules.

### 1.4 VECTOR_VERSION (per vector, since v0.9)
**What it is:** Version of an individual vector pattern's counting logic (`method_version` in `vectors_collected[]`).
**Where it lives:** `vectors_collected[].method_version`, identity digest preimage.
**When it bumps:** When detection rules, regex patterns, or counting logic change.
**Format:** Single integer.
**Current vectors:**
- `chatlog` method_version: 11 (v1.34.0: session axes first_timestamp/last_timestamp/cwd feed the rules_hash → 11; v1.29.0: agentic tool-turn block sets → 10; v1.4.0: content-shape gate over the retained stop-list — `utterance_ratio≥0.6` via function-word/punctuation/length arms, FP-lexicon dominance, version-tag structure vote-against, FAQ complete-set exclusion; provisional `content_shape` surfaced — a density floor was prototyped then dropped in review, surfaced not gated. Prior: 8 = v1.2.4 case-insensitive stop-list + embedded-dialogue parity; 7 = v1.2.3 FAQ stop-list; 6 = v1.2.2 recurrence + stop-list; 5 = v1.2.1 distinct-speaker + co-signal; 4 = v1.2 generalized conversational JSON/JSONL; 3 = v0.10.1 JSONL role detection + v0.9.1 stop-list/H3 threshold)
- `reference_tokens` method_version: 3 (v1.30.2: the wiki-link pattern in the rules-definition was bounded for ReDoS → fingerprint moved; v0.9.2: URL-stripped path counting)
- `author_aggregate` method_version: 1 (v0.10.0: corpus-scoped)
- `filename_patterns` method_version: 1 (v0.10.0: file-scoped)
- `provenance` method_version: 2 (v1.10.0: + OLE2 producing-app feeds the toolchain; v1.6.0: corpus-scoped — normalized toolchain (closed table), production era, digitization origin; complements author_aggregate). STABLE v1.14.
- `fact_block` method_version: 1 (v1.32.0: content-detected generic kv-fact-block; gate/veto/caps feed rules_hash, thresholds feed static_tuning_hash). Provisional.
- `ai_session` method_version: 2 (v1.35.0: + per-model usage attribution rule; v1.33.0: usage-map/fingerprint tables feed rules_hash). Provisional.
- `lexicon` method_version: 1 (v1.38.0: bring-your-own-lexicon; the MECHANISM feeds rules_hash, the supplied dictionary feeds `dictionary_id` — see §1.5). File-scoped, registered only when a lexicon is supplied. Provisional.
**Internal rule:** A vector at version N in two scanner releases must produce identical counts on identical input. If counts could differ, bump the vector version. This is enforced by the identity digest — same digest guarantees same output.

### 1.5 DICTIONARY_ID (per customer dictionary — REALIZED in v1.38)
**What it is:** Identifier for a word list, pattern set, or configuration that drives a vector. **First real use: the v1.38 bring-your-own-lexicon term observer** — the consumer-supplied lexicon is the "customer dictionary."
**Where it lives:** the `lexicon` vector's `dictionary_id` (SHA-256 over the canonical-JSON of `lexicon_id` + sorted categories/terms) and the `signal_provenance` `detail.dictionary_id` on the `lexicon_match` field. Feeds the vector `identity_digest` (v0.9 §2.4).
**When it bumps:** Derived from the lexicon CONTENT, so it moves on any term/category change even when the consumer's `lexicon_id` label is unchanged — catching silent lexicon drift (dual-falsification). The terms themselves are never emitted; only the hash.
**Format:** a 64-character lowercase SHA-256 hex digest of the canonical JSON of the supplied lexicon (`lexicon_id` + sorted categories/terms). Not a human-authored slug.
**Current:** no default dictionary ships — each consumer-supplied lexicon produces its own digest at scan time.
**Internal rule:** Editing a lexicon's terms is *automatically* a new ID (the content-derived digest moves) — so "never edit in place" is enforced by construction, not by convention. The consumer's own `lexicon_id` label is a human-readable name only; the digest is the identity.

### 1.6 Quick Reference

| Concern | Constant | Format | Current | Internal/Public |
|---|---|---|---|---|
| Package release | `SCANNER_VERSION` | `MAJOR.MINOR.PATCH` | 1.39.0 | Internal |
| Routing logic | `LOGIC_VERSION` | `MAJOR.MINOR.PATCH` | 1.21.0 | Internal* |
| Manifest shape | `SCHEMA_VERSION` | `MAJOR.MINOR` | 1.22 | **Public** |
| Vector logic (v0.9+) | per-vector | `int` | n/a | **Public** (when shipped) |
| Customer dictionary (v0.10+) | `term_dictionary_id` | `ns_desc_period` | n/a | **Public** (when shipped) |

*LOGIC_VERSION is in the manifest, so it's *visible* to consumers, but it's not a stability commitment — we bump it freely. Consumers use it to detect "did the scanner change how it routes?" but they don't depend on a specific value.

### 1.7 Bump Consistency Rule

When SCANNER_VERSION bumps, ALL of these update together:
- `SCANNER_VERSION` constant in scanner.py
- `pyproject.toml` `version` field
- Module docstring `Version:` line
- `Schema:` line in module docstring (only if SCHEMA_VERSION also bumped)
- Test version assertions

When LOGIC_VERSION or SCHEMA_VERSION bump, those constants update independently — but SCANNER_VERSION usually bumps too (since you're shipping the change).

---

## 2. Document Naming Conventions (internal)

### 2.1 RFC Specifications

**Approved spec:** `docs/v{VERSION}.0_RFC_Specification.md`
- Status field: `**Status:** Approved`
- Title does NOT contain "(DRAFT)"
- Content stable; corrections via errata or rolled into next version

**Draft spec:** `docs/v{VERSION}.0_RFC_DRAFT.md`
- Status field: `**Status:** Draft`
- Title contains "(DRAFT)"
- May be edited, restructured, deleted
- **Promotion to approved:**
  1. Rename file: drop `_DRAFT`, add `_Specification`
  2. Remove "(DRAFT)" from title
  3. Change Status to `Approved`

### 2.2 Compliance Reports

`docs/COMPLIANCE-v{VERSION}.md`
- One per minor version with a corresponding RFC
- Audits implementation against approved RFC requirements
- Tabular: requirement, implementation location, status
- Created after implementation, before PR merge

### 2.3 Other Documents

- `README.md` (repo root) — user-facing project README (also rendered on PyPI via `pyproject.toml`)
- `docs/HISTORY.md` — running index of all versions, specs, and compliance reports (with links to archived items post-v1.0)
- `docs/CONVENTIONS.md` — this file (internal)
- `docs/PUBLIC_CONTRACT.md` — consumer-facing stability commitments
- `docs/STANDARDS_TRACKING.md` — awareness of adjacent standards, formats, obligations
- `docs/SPEC.md` — historical v0.1 base contract (do not modify)
- `CLAUDE.md` — agent instructions (root, not docs/)

### 2.4 Scratch / Working Notes

`scratch/` (gitignored)
- Descriptive names
- Version-targeted files use `v{X}_` prefix when tied to a future release
- Subject to revision/deletion
- Promote to `docs/` when stable

### 2.5 Session Changelog

`changelog/sessions/YYYY-MM-DD_HHMM_v{VERSION}_session.md` (gitignored)
- Append `_pt2`, `_pt3` for multiple sessions per day

### 2.6 Memory Files

`~/.claude/projects/-srv-projects-pkplab-scanner/memory/{type}_{topic}.md`
- `project_*` — state, status, ongoing work
- `feedback_*` — corrections, lessons
- `reference_*` — external pointers
- `user_*` — user profile
- All indexed in `MEMORY.md`

---

## 3. Promotion Path

```
[idea]
  ↓
[scratch/ note]                       informal, subject to change
  ↓
[docs/v{X}.0_RFC_DRAFT.md]            formal proposal, under review
  ↓
[approval]
  ↓
[docs/v{X}.0_RFC_Specification.md]    approved, frozen
  ↓
[implementation on v{X}.0 branch]
  ↓
[docs/COMPLIANCE-v{X}.md]             audit against the spec
  ↓
[PR review + merge to main]
  ↓
[stable in main, version released]
```

**Internal rule:** Don't skip stages. Don't approve a draft without renaming. Don't merge an implementation without compliance. Don't release without tests passing.

### 3.1 Field stability ladder (candidate → provisional → stable, v1.10)

Manifest fields graduate through tiers. The promotion criterion is **settled producing
logic + evidence of value**, not age.

- **candidate** *(below provisional)* — a held observation tracked + measured in the
  review apparatus (`corpus_sweep.py`), **NOT in the manifest** (no contract status,
  no scanner parser surface). Carries a held-reason, a cheap safe **sweep-side harvest**,
  and a promotion trigger. Promote → provisional when the held reason is resolved AND the
  harvest shows the signal is worth surfacing.
- **provisional** (PUBLIC_CONTRACT §2.4) — in the manifest, "may change in a MINOR." Be
  liberal admitting *cheap observe-only* fields (the v0.9 intent — provisional is how we
  gather data); the bar that doesn't relax: observe-only, deterministic, never-crash/bounded
  for any new parser path (v1.8.1).
- **stable** — under the backward-compat policy; not removable/retypable without a MAJOR bump.

**Candidate registry (v1.10) — ACTIVE candidates:**
| Candidate | Held because | Sweep-side harvest (not in the manifest) | Promotion trigger |
|---|---|---|---|
| CAD (DGN/DWG) | heavy new parser on untrusted binary | prevalence via `format_sig_dist` + `recognition_candidates.B_by_family[cad]` (19 `.dwg`, 2026-06-17 scout) | enough real-corpus CAD to justify a red-teamed reader |
| word-twisting provenance | data-gated on the tagged RPG corpus | the corpus tagging itself (external) | tagged corpus exists + hypothesis validates |
| chatlog relay-block extraction (`observed.chatlog.relays:[{from_agent,to_agent,subject,origin_project}]`) | heuristic detection of a self-authored, drifting convention (NOT a spec); chatlog family is alpha-locked + Sentinel-mirrored → coordination-gated; no consumer built yet (recall's relay feature is a held bearing) | `scratch/measure_relay_blocks.py` on the federation chatlog corpus (2026-06-28 sizing: **560 blocks across 17/29 logs**, 63% anchor precision, 65% naive extraction, **20 shape signatures** top-format-only-31% → `scratch/relay_candidate_sizing_2026-06-28.md`) | recall builds the relay consumer + Sentinel coordinated (chatlog-detection LOGIC change → RFC + 4-leg) — and ideally the relay format is **canonicalized first** (the variance is self-inflicted: standardizing the shape lifts extraction 65%→~100%) |
| **[SHIPPED v1.23.2]** corroborated-header MIME sniff (the v1.23.1 Codex-P2 follow-up) | the offset-only window can't separate a real header at offset 257–1024 from a deep literal (e.g. the `.py` `%PDF-1.4` at 864 sits inside the 1024 PDF tolerance); the robust fix — widen to the 1024 spec tolerance AND require a corroborating structural token (`endobj`/`xref`/`trailer`) — exceeds a window-tweak patch | the puresniff clean-room replica (which surfaced the v1.23.1 FP) is the venue to design the robust signature; sweep harvest = count of no-libmagic files with `%PDF-` at offset 257–1024 (currently ~0 in 19.5k corpus) | a real corpus file regresses (renamed/junk-prefixed PDF, no-libmagic) OR puresniff lands the corroborated signature → adopt cross-replica |

**Graduated out of the candidate tier (recorded so the ladder shows its history):**
- **office/media extraction (Candidate B)** → SHIPPED across two phases, both as provisional namespaces: **v1.24** (phase 1: `.pptx`/`.odp`/`.odt`/`.ods` office + `.jp2`/`.tiff` images) and **v1.25** (phase 2: `.mp3` → new `audio` namespace + legacy `.ppt` → `presentation` via OLE2). The measure-first (2026-06-23) found recognition already solid + no consumer, so the family was scoped to the formats that complete an existing parser family at the v1.8.1 bar. CAD (DGN/DWG) stays an ACTIVE candidate (separate row — heavy new parser, prevalence-gated). See PUBLIC_CONTRACT §2.4 + §3.
- **image EXIF** → built into the manifest as **provisional fields in v1.16** (designation corrected to provisional in v1.21.1). See PUBLIC_CONTRACT §2.4.
- **binary content-recognition (Candidate A)** → **SHIPPED as v1.22.0**. It was a routing/LOGIC candidate (not a manifest field), so it graduated by *shipping* (the recognition-only `unsupported_extension`-for-binary change), not by becoming a provisional field. The `recognition_candidates.A_*` sweep harvest stays in `corpus_sweep` (now ~0 — it measures the fix having landed).

A field enters at **candidate or provisional, never directly stable.**

---

## 4. Internal Tracking Inventory

This section is for **us**. It is the running list of everything File Observer currently has. Keep it current.

### 4.1 Versioned constants

| Constant | Location |
|---|---|
| `SCANNER_VERSION` | `src/file_observer/scanner.py` |
| `LOGIC_VERSION` | `src/file_observer/scanner.py` |
| `SCHEMA_VERSION` | `src/file_observer/scanner.py` |
| `version` | `pyproject.toml` |
| `Version:` | scanner.py module docstring |
| `Schema:` | scanner.py module docstring |

### 4.2 Output surface — canonical: `docs/SCHEMA.md`

The complete, **current** inventory of specialist tools, namespaces, per-namespace fields,
vectors, safety flags, error codes, provenance triggers, format signatures, preservation
tiers, and MIME tiers is **auto-generated from the live registries** by `--schema` (v1.13)
and committed as **`docs/SCHEMA.md`**. It is drift-guarded (`test_committed_schema_md_matches_generated`)
and completeness-guarded (a registry can't omit an emitted value). **Read the inventory there
— do not hand-maintain a second copy in this file.** (This section used to enumerate the
surface and quietly drifted several minors behind; the v1.13 self-description made the hand
list redundant, so it was replaced with this pointer.)

Refresh: `python -m file_observer.scanner --schema --schema-format md > docs/SCHEMA.md`
(or `--schema-format summary` for the human-readable prose, v1.19).

Two decisions worth recording that the generated schema doesn't capture:

- **Chatlog is content-detected, not extension-keyed** — it activates via
  `_detect_chatlog_pattern` on decoded baseline text, NOT through `SPECIALIST_TOOLS` /
  `SPECIALIST_NAMESPACE` (those are extension-keyed; registering chatlog there would risk
  accidental routing and mis-inventory a content-based dispatch as extension-based). See
  chatlog `method_version` in §1.4.
- **Short 2-byte ASCII magics are deliberately excluded** from `MAGIC_SIGNATURES` (PE `MZ`,
  BMP) — they collide with prose; `ID3` / bzip2 carry a corroborating byte for the same reason.

### 4.9 Customer dictionaries (future v0.10+)

Empty.

---

## 5. Documentation Requirements per Version

### 5.1 Minor version release (0.x.0)

Required before merge:
- [ ] `docs/v{VERSION}.0_RFC_Specification.md` — approved spec
- [ ] `docs/COMPLIANCE-v{VERSION}.md` — compliance report
- [ ] `README.md` (repo root) — version, schema, feature table updated
- [ ] `docs/HISTORY.md` — new version row added; "Drafts in Flight" updated
- [ ] `CLAUDE.md` — spec references and roadmap updated
- [ ] `docs/CONVENTIONS.md` (this file) — updated only if a *convention* changed (naming, version rules, promotion path). The output-surface inventory is no longer hand-maintained here — it lives in the auto-generated `docs/SCHEMA.md` (next item)
- [ ] **`docs/SCHEMA.md` regenerated** (since v1.13) — any change to the output surface (a new field, vector, specialist, safety_flag, error code, or provenance trigger) MUST be reflected in the generated schema doc + its source registry (`ERROR_CODES` / `SAFETY_FLAGS` / `PROVENANCE_TRIGGERS` / `SPECIALIST_FIELDS`). Regenerate: `python -m file_observer.scanner --schema --schema-format md > docs/SCHEMA.md`. The drift-guard test (`test_committed_schema_md_matches_generated`) fails if it's stale; the completeness tests fail if a registry is missing an emitted value. (Regenerating `docs/SCHEMA.md` is required for *any* new surface value; it is NOT the same as a `SCHEMA_VERSION` bump — see §1.3, that's only for new fields/namespaces/vectors.)
- [ ] `docs/PUBLIC_CONTRACT.md` — updated only if a public contract field changed
- [ ] `docs/STANDARDS_TRACKING.md` — touch point pass: review Awareness, Moving toward, Obligations against this version's scope
- [ ] `pyproject.toml` — version bumped
- [ ] Module docstring — version, schema, spec reference updated
- [ ] All version constants — bumped
- [ ] Test version assertions — updated
- [ ] Tests passing
- [ ] Documentation audit (see STANDARDS_TRACKING.md §3.1) — every constant, error code, safety flag, namespace verified against docs
- [ ] PR description summarizing changes

### 5.2 Patch release (0.x.y)

- [ ] `pyproject.toml` — version bumped
- [ ] Module docstring `Version:` updated
- [ ] `SCANNER_VERSION` constant updated
- [ ] **Do NOT** bump `LOGIC_VERSION` or `SCHEMA_VERSION` unless they actually changed
- [ ] Tests passing

### 5.3 Major version release (x.0.0)

All of the above for minor, plus:
- [ ] Migration guide
- [ ] Deprecation notice in previous minor (one full minor cycle of warning)
- [ ] `SCHEMA_VERSION` MAJOR bump
- [ ] `PUBLIC_CONTRACT.md` updated with breaking change notice
- [ ] **Archive trigger:** All previous major version's RFCs and compliance reports moved to `docs/archive/{previous_major}.x/`. `docs/HISTORY.md` updated with new archive paths. Working `docs/` directory shrinks to: current spec, current compliance, three companion docs (CONVENTIONS/PUBLIC_CONTRACT/STANDARDS_TRACKING), README, HISTORY, and pre-RFC historical documents (SPEC.md, v0.2Spec.md, COMPLIANCE.md).
- [ ] **First major (v1.0) special case:** The v1.0 release is when archival begins. v0.3-v0.x specs and compliance reports move to `docs/archive/0.x/`. Pre-RFC documents (SPEC.md, v0.2Spec.md, COMPLIANCE.md) stay in `docs/` as historical anchors.

---

## 6. PR Conventions

1. **Title:** `v{VERSION}: {short description}`
2. **Body must include:** summary by phase, test count change, schema version statement, test plan checklist
3. **Compliance report committed before merge** (not follow-up)
4. **All review comments addressed before merge**
5. **Branch deleted after merge**

---

## 7. Glossary (internal vocabulary)

- **Scribe vectors** — manifest-level pattern observations across files. The scanner watches for "ravens" and counts them without imputing meaning.
- **Vector fingerprint** — cryptographic identity of a vector instance: vector_id + method_version + config_hash + dictionary_id + scanner_version. Designed in v0.9+.
- **Drift visibility** — property that a stateful consumer can detect changes by diffing per-file signals. Scanner stays per-file; ingestor holds comparison logic.
- **Promotion candidate** — unsupported file extension or pattern appearing in volume across a real corpus, justifying scanner support.
- **Wayne K** — `dc:creator` value that recurs across CP Construction files but doesn't map to a real person. Originated as a Word template default. Mascot for "report the news" philosophy.
- **The asymmetry principle** — new vectors appear faster than promotion candidates, because vectors need fresh perspective and promotions need volume.

---

## 8. When This Document Updates

This is a living reference. Update it at the same time as the code change, not as a follow-up. Update when:

- New versioned concern introduced
- New specialist, namespace, magic signature, safety flag, error code, vector, or dictionary added
- Naming convention changes
- New document type introduced
- Promotion path stage added
