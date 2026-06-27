# Standards Tracking

This is the scanner's living awareness of standards, formats, and conventions adjacent to what we do. It exists so we don't lose track of what's out there, what we've decided, and what we owe.

The document follows three buckets: **tracking** (what we know about), **touch points** (when we look at it), and **audits** (when we verify the documentation matches the code).

> **Rule against bureaucracy:** This is a habit, not a process. If a section becomes paperwork instead of useful, simplify it. The goal is to spend five minutes thinking about standards at the right moments, not to fill out forms.

---

## 1. Tracking

Three short lists. Move items between them as decisions get made.

### 1.1 Awareness — things we know about, no decision yet

Things on the radar but not committed to. Some will graduate; some will be parked indefinitely. That's fine.

| Item | Category | Notes |
|---|---|---|
| **PREMIS** | Preservation | Closest conceptual fit. Library/archive/government segment unlock. Worth its own spec eventually. See `scratch/standards_roadmap.md`. |
| **SPDX** | SBOM | License compliance + audit trail format. ISO/IEC 5962. Useful as export option for LLM training and pipeline credibility. |
| **CycloneDX** | SBOM | Lightweight alternative to SPDX, security-focused. Same use case as SPDX export. |
| ~~Dublin Core~~ | ~~Metadata~~ | ~~Graduated to Adopted in v0.9~~ |
| **PRONOM** | Format identification | UK National Archives registry. Could add PUID lookup for known formats. Cheap credibility win. |
| **DBoM** | Data governance | GDPR Article 30 use cases. Wait for a real customer ask. |
| **JHOVE** | Format validation | Different tool with different goals. Position scanner as upstream layer, not integration. |
| **Apache Tika** | Content extraction | Direct competitor in some markets. Marketing positioning, not adoption. |
| **C2PA / Content Credentials** | Provenance / authenticity | **High-value strategic fit for the `provenance` seam.** Cryptographically-signed provenance manifests, embedded by camera makers (Leica/Sony/Nikon) + AI generators (the AI-content signal) + Adobe/MS tooling. C2PA-*presence* detection would extend `provenance`/`digitization` — observe-with-disclosure, not verification. Likely v1.17+. Researched 2026-06-15. |
| **XMP (ISO 16684-1 / Adobe)** | Metadata | Graduated to *Moving toward v1.16* (presence). Listed here for cross-ref — also feeds the future C2PA/IPTC provenance work. |
| **IPTC Photo Metadata (IIM / XMP)** | Metadata | Creator/copyright/caption on pro/edited photos; feeds `author_aggregate`/`provenance`. Maps onto the same EXIF/XMP fields MWG reconciles. Awareness for now; graduate with the provenance-image work. Researched 2026-06-15. |
| **MWG (Metadata Working Group) guidelines** | Metadata reconciliation | "Guidelines for Handling Image Metadata" (Adobe/Canon/MS) — how EXIF/IPTC/XMP equivalent fields (DateTime, Creator) map + reconcile. **Design input, deliberately NOT adopted as a reconciler:** the MWG itself stalled and ExifTool became the de-facto authority, so file-observer will REPORT each source's value (observe-don't-interpret), not pick a winner. ExifTool is the reconciliation reference + the falsify-first oracle for v1.16 (as pypdf was for v1.8). Researched 2026-06-15. |

### 1.2 Moving toward — decided to support, not yet built

Items we've committed to in principle. They have an intended target version. They're not yet implemented.

| Item | Target version | Form | Status |
|---|---|---|---|
| **Android video GPS (ISO 6709 in `udta`/`©xyz`)** | TBD (gated) | The Android counterpart to the iPhone QuickTime `location.ISO6709` GPS-presence already shipped — coordinates live in `moov`→`udta`→`©xyz`. | **GATED** — needs a real Android `.mp4`/`.mov` sample to validate (the last open capture-metadata follow-up). |
| **Full XMP depth (ISO 16684-1)** | TBD | Beyond presence: parse the XMP packet for creator / edit-history / rights. | **PRESENCE-ONLY today** (`xmp_present`, v1.16); a full parse is the ungated upgrade. |
| **CAD container metadata (DGN / DWG)** | TBD (candidate) | Observe-only structural metadata for CAD drawings. | **CANDIDATE-tier** (CONVENTIONS §3.1) — heavy new untrusted-binary parser, prevalence-gated; not committed. |

_(The image/video capture-metadata standards that used to sit here — EXIF, HEIF Exif item, XMP presence, ISOBMFF + Apple QuickTime keys — all SHIPPED in v1.16–v1.20 and moved to §1.3 below.)_

### 1.3 Adopted — implemented and current

Items the scanner actively supports. The form here is "what we ship that this standard requires."

| Item | Since version | Form | Notes |
|---|---|---|---|
| **Dublin Core** | 0.9 | DOCX specialist extracts `dc:title` → `document.title`, `dc:creator` → `document.author`. Alignment documented in PUBLIC_CONTRACT.md §1.4. | First item promoted through the standards tracking workflow. |
| **EXIF (CIPA DC-008)** | 1.16 | Image `make`/`model`/`orientation`/`datetime_original` + GPS-presence (→ `geotagged`) from TIFF/IFD0 + Exif sub-IFD + the GPS IFD; JPEG (APP1) + HEIC. Hand-parsed (stdlib/`struct`, no Pillow). | Moved from §1.2 — implemented v1.16.0. |
| **HEIF Exif item (ISO/IEC 23008-12)** | 1.16 | HEIC EXIF via `meta`→`iinf`/`iloc` Exif-item (version-aware `iloc`); HEIC dims from EXIF pixel dims (the `ispe` tile-trap avoided). | The iPhone-HEIC path. |
| **XMP presence (ISO 16684-1 / Adobe)** | 1.16 | `xmp_present` via the Adobe namespace marker (JPEG APP1 / HEIF XMP item). Presence only — full depth is a §1.2 upgrade. | |
| **ISOBMFF + Apple QuickTime keys + ISO 6709 (video)** | 1.17–1.20 | `video_structure` for `.mp4`/`.mov`/`.m4v`: codec/duration/dims/`creation_date` (mvhd) + `make`/`model` + GPS-presence (`location.ISO6709`) + `creation_date_qt` (the QuickTime creationdate key, TZ-bearing). Hand-rolled ISOBMFF walk, stdlib/`struct`. | Apple path adopted; Android `udta`/`©xyz` GPS still §1.2-gated. Oracle-validated `exiftool`-exact. |
| **ID3v2 + MPEG-1/2 Audio (ISO/IEC 11172-3 / 13818-3)** | 1.25 | `audio` namespace for `.mp3`: ID3v2.2/2.3/2.4 tags + a bounded MPEG frame-header parse (`format`/`bitrate`/`duration_s`, Xing/CBR). Stdlib. | The lone net-new untrusted-binary parser of Candidate B; v1.8.1-hardened. |
| **MS-CFB + MS-OLEPS (OLE2 property sets)** | 0.7 / 1.25 | OLE2 compound-file reading via `olefile` for `.doc`/`.xls`/`.msg`/`.ppt`: `SummaryInformation` (title/author/app) + `DocumentSummaryInformation` (slide_count). | OLE2 specialists declare a full-file-deviation provenance (v1.25.1). |
| **JSON Schema (draft 2020-12)** | 1.27 | FO **emits** a standard JSON Schema of the manifest — `docs/manifest.schema.json`, via `--schema --schema-format json-schema` — for any-language validation/codegen. | The first standard FO *produces* (vs consumes); generated from the dataclasses, drift-guarded. |

### 1.4 Obligations — things we don't get to ignore

Things we should be aware of even if we haven't acted on them. License obligations from dependencies, legal disclosures, regulatory acknowledgments, security advisories tied to formats we touch.

| Item | Source | What it requires | Status |
|---|---|---|---|
| `python-magic` license (PSF/MIT) | dependency | Attribution in distribution | Acknowledge in LICENSE/NOTICE when project goes public |
| `chardet` license (LGPL 2.1) | dependency | Source/binary distinction; attribution | Same |
| `olefile` license (BSD-2) | optional dependency | Attribution | Same |
| `defusedxml` license (PSF) | optional dependency | Attribution | Same |
| `PyYAML` license (MIT) | optional dependency | Attribution | Same |

**Rule:** Anything in this list that needs action gets a date or a triggering event next to it. Don't let things rot here without a follow-up.

**Related discipline — CVE response readiness:** Each of the dependencies above will eventually receive a security advisory filed in the CVE (Common Vulnerabilities and Exposures) database. Preparedness for that inevitability is tracked separately in `scratch/inevitable_track.md §3.1` rather than here, because CVE response is a *process* concern (do we have a SECURITY.md, a disclosure contact, a response-time commitment) rather than a *standards* concern.

---

## 2. Touch Points

Specific moments in the existing workflow when we look at this document. We do not invent new ceremonies — we attach to things that already happen.

### 2.1 When drafting a new RFC (`docs/v{X}.0_RFC_DRAFT.md`)

Five-minute pass:
1. Skim **Awareness** — does anything fit this version's scope?
2. Skim **Moving toward** — does this version land any of those?
3. Skim **Obligations** — does this version touch anything that triggers an obligation?

Outcomes:
- Move items from Awareness → Moving toward (if committing)
- Move items from Moving toward → Adopted (if shipping in this version)
- Add new items to Awareness if they came up while drafting
- Add notes to the RFC if a standard shaped a decision

### 2.2 When locking a version (promoting `_DRAFT.md` → `_Specification.md`)

Five-minute pass:
1. Verify all "Moving toward" items targeted at this version are either Adopted or explicitly deferred
2. Update Adopted entries with the version they shipped in
3. If anything got deferred, push the target to a future version with a reason

### 2.3 When opening a PR for a version release

The PR description includes a one-line "standards" note if anything in this document changed. If nothing changed, no note. The PR itself includes commits to this document if it was updated.

### 2.4 Discretionary look-up — once in a while

Outside of the RFC cycle, occasionally lift our heads and look at:
- **Forward** — emerging standards, drafts, RFCs in adjacent communities
- **Adjacent** — what parallel domains are doing (preservation, SBOM, content extraction, observability)
- **Legacy** — older standards that might still be relevant for compatibility

Add anything interesting to the Awareness list. No commitment required.

**Cadence:** No fixed schedule. When something prompts it (a blog post, a customer mention, an article like this morning's PDF extraction piece), spend ten minutes and update the Awareness list. The point is to keep the list warm, not to schedule meetings.

---

## 3. Audits

Two checks that run alongside the existing version workflow. Both are documentation-vs-code consistency checks. Treat them with the same seriousness as test coverage.

### 3.1 Documentation audit (per minor version, before merge)

Walk these verification points:

- [ ] Every constant in `SCANNER_VERSION`, `LOGIC_VERSION`, `SCHEMA_VERSION` matches what's in `pyproject.toml` and the module docstring
- [ ] Every entry in the CONVENTIONS.md tracking inventory matches the actual code (specialists, namespaces, magic signatures, safety flags, error codes)
- [ ] Every error code emitted by the scanner has a row in PUBLIC_CONTRACT.md (if it's a stable code) or an explicit "internal only" note
- [ ] Every safety flag emitted has a row in PUBLIC_CONTRACT.md
- [ ] Every specialist namespace has a row in PUBLIC_CONTRACT.md with stability marker
- [ ] Every public field has a stability statement (stable / internal / experimental)
- [ ] STANDARDS_TRACKING.md (this file) reflects any standards activity from the version
- [ ] Compliance report exists for the version

**Rule:** If a check fails, fix the docs in the same PR. Documentation drift compounds — three versions of skipped audits and the docs are useless.

### 3.2 Standards consistency audit (when an item moves between sections)

When a standard moves Awareness → Moving toward → Adopted → (Obligations), verify:

- [ ] CONVENTIONS.md tracking inventory updated if the change introduces new constants/fields
- [ ] PUBLIC_CONTRACT.md updated if the change affects what consumers can count on
- [ ] Per-version RFC notes the standards work
- [ ] Compliance report cites the standard if it shaped a requirement
- [ ] Any code referencing the standard has tests
- [ ] LICENSE/NOTICE updated if obligation changed

This audit happens at the same moment as the move. Don't move an item without updating the connected documents.

---

## 4. What This Document Looks Like in Practice

A normal cycle:

1. **Drafting v0.8** — open `STANDARDS_TRACKING.md`, look at Awareness. Notice PRONOM lookup is small enough to fit. Move it from Awareness to Moving toward, target v0.8.

2. **Implementing v0.8** — build the PRONOM lookup. Tests pass. Commit references the standard.

3. **Locking v0.8** — promote draft to spec. Move PRONOM from Moving toward → Adopted, mark "since 0.8". Update CONVENTIONS.md tracking inventory with the new PUID field. Update PUBLIC_CONTRACT.md with PUID stability statement.

4. **PR merge** — documentation audit checklist runs. Standards consistency audit confirms PRONOM moved cleanly.

5. **Months later** — someone asks "does scanner support PRONOM?" — the answer is in the Adopted table with the version. Done.

A discretionary look-up:

1. **Article appears** about a new metadata format from the Library of Congress. Spend ten minutes reading. Add to Awareness with a one-line note. Move on.

2. **Six months later** — drafting v1.2. The format is mentioned in a customer conversation. Awareness list reminds us we already noticed it. Decide whether to graduate it.

That's the entire workflow. Three lists, four touch points, two audits. Habit, not bureaucracy.

---

## 5. When to Update This Document

- When a standard becomes relevant enough to track (add to Awareness)
- When you decide to support a standard (move to Moving toward)
- When you ship support (move to Adopted)
- When an obligation surfaces (add to Obligations)
- When an awareness item is no longer relevant (remove with a note in the changelog)
- During the per-version touch points (verify the document is current)

---

## 6. Sources of Standards News

A short list of where to look during discretionary look-ups. Add to it as we find good sources.

- [DCMI](https://www.dublincore.org/) — Dublin Core and metadata applications
- [Library of Congress Standards](https://www.loc.gov/standards/) — PREMIS, METS, MODS
- [OWASP CycloneDX](https://cyclonedx.org/) — SBOM and adjacent
- [SPDX](https://spdx.dev/) — SBOM
- [UK National Archives PRONOM](https://www.nationalarchives.gov.uk/PRONOM/) — file format identification
- [DBoM Project](https://dbom-project.readthedocs.io/) — Data Bill of Materials
- Tech press for emerging document/AI/preservation news

---

## 7. The Discipline

This document is one of three documents the scanner needs to keep up-to-date alongside the code:

- **CONVENTIONS.md** — internal naming, version constants, tracking inventory
- **PUBLIC_CONTRACT.md** — what consumers can count on
- **STANDARDS_TRACKING.md** — what we know about, what we're moving toward, what we owe

All three are updated in the same PR as the code change that affects them. Documentation drift between releases is the failure mode we're protecting against. Five minutes of thinking at the right moment beats two hours of archaeology three months later.
