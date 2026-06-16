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
**Current:** `1.15.1`

### 1.2 LOGIC_VERSION
**What it is:** The version of the routing decision logic — code that decides `is_binary`, `requires_vision`, `requires_specialist_tool`, the SPECIALIST_TOOLS dict, SUPPORTED_EXTENSIONS, SPECIALIST_NAMESPACE.
**Where it lives:** `LOGIC_VERSION` constant in `src/file_observer/scanner.py`, `ScanContext.logic_version` in every manifest.
**When it bumps:** Any time the same file would route differently than before.
**Format:** `MAJOR.MINOR.PATCH`. May lag SCANNER_VERSION.
**Current:** `1.5.1`
**Internal rule:** When in doubt, bump it. Stale LOGIC_VERSION causes silent reproducibility bugs across environments.

### 1.3 SCHEMA_VERSION
**What it is:** Version of the manifest shape — what fields exist, what they're named, how they nest.
**Where it lives:** `SCHEMA_VERSION` constant, `manifest.schema_version` field, included in checksum preimage.
**When it bumps:**
- MINOR (0.x → 0.x+1): additive changes (new fields, new namespaces, new vectors)
- MAJOR (x.0 → x+1.0): breaking changes (removal, rename, type change)
- No bump for patch releases
**Format:** `MAJOR.MINOR` (no patch)
**Current:** `1.9`  (1.8→1.9 at v1.14.0 — the promotion pass)
**Note:** This IS a public contract field. As of v1.0, downstream consumers depend on it. See `PUBLIC_CONTRACT.md` for the consumer-facing rules.

### 1.4 VECTOR_VERSION (per vector, since v0.9)
**What it is:** Version of an individual vector pattern's counting logic (`method_version` in `vectors_collected[]`).
**Where it lives:** `vectors_collected[].method_version`, identity digest preimage.
**When it bumps:** When detection rules, regex patterns, or counting logic change.
**Format:** Single integer.
**Current vectors:**
- `chatlog` method_version: 9 (v1.4.0: content-shape gate over the retained stop-list — `utterance_ratio≥0.6` via function-word/punctuation/length arms, FP-lexicon dominance, version-tag structure vote-against, FAQ complete-set exclusion; provisional `content_shape` surfaced — a density floor was prototyped then dropped in review, surfaced not gated. Prior: 8 = v1.2.4 case-insensitive stop-list + embedded-dialogue parity; 7 = v1.2.3 FAQ stop-list; 6 = v1.2.2 recurrence + stop-list; 5 = v1.2.1 distinct-speaker + co-signal; 4 = v1.2 generalized conversational JSON/JSONL; 3 = v0.10.1 JSONL role detection + v0.9.1 stop-list/H3 threshold)
- `reference_tokens` method_version: 2 (v0.9.2: URL-stripped path counting)
- `author_aggregate` method_version: 1 (v0.10.0: corpus-scoped)
- `filename_patterns` method_version: 1 (v0.10.0: file-scoped)
- `provenance` method_version: 2 (v1.10.0: + OLE2 producing-app feeds the toolchain; v1.6.0: corpus-scoped — normalized toolchain (closed table), production era, digitization origin; complements author_aggregate). STABLE v1.14.
**Internal rule:** A vector at version N in two scanner releases must produce identical counts on identical input. If counts could differ, bump the vector version. This is enforced by the identity digest — same digest guarantees same output.

### 1.5 DICTIONARY_ID (per customer dictionary, future v0.10+)
**What it is:** Identifier for a word list, pattern set, or configuration that drives a vector.
**Where it lives:** `signal_provenance` `detail.term_dictionary_id`, vector configuration registry.
**When it bumps:** When dictionary contents change. Dictionaries are immutable once published — a change is a new ID, not a modification.
**Format:** `{namespace}_{descriptor}_{period}` — e.g., `example_terms_2026_q2`
**Current:** N/A
**Internal rule:** Never edit a published dictionary in place. Always publish a new ID and let consumers opt in.

### 1.6 Quick Reference

| Concern | Constant | Format | Current | Internal/Public |
|---|---|---|---|---|
| Package release | `SCANNER_VERSION` | `MAJOR.MINOR.PATCH` | 1.11.0 | Internal |
| Routing logic | `LOGIC_VERSION` | `MAJOR.MINOR.PATCH` | 1.4.3 | Internal* |
| Manifest shape | `SCHEMA_VERSION` | `MAJOR.MINOR` | 1.8 | **Public** |
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

**Candidate registry (v1.10):**
| Candidate | Held because | Sweep-side harvest (not in the manifest) | Promotion trigger |
|---|---|---|---|
| CAD (DGN/DWG) | heavy new parser on untrusted binary | prevalence via `format_sig_dist` | enough real-corpus CAD to justify a red-teamed reader |
| image EXIF | location/privacy sensitivity | EXIF-presence count (marker only, never GPS values) | demand + a settled observe-presence framing |
| word-twisting provenance | data-gated on the tagged RPG corpus | the corpus tagging itself (external) | tagged corpus exists + hypothesis validates |

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
