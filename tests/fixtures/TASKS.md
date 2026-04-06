# Tasks

Tags: `[PKM]` pipeline infra · `[TIQ→Git]` prep for cp-project · `[SEN→Git]` prep for Sentinel · `[WORK]` CP Construction · `[Personal]`

---

## Active

### PKM — Phase 1: Fix Routing Rules + Execute Batch

- [x] `1.1` Fix `routing-rules.yaml` — embedded-tags pre-check (content before filename patterns)
- [x] `1.2` Fix `routing-rules.yaml` — WinCan/wc- → WORK/1881 (was hitting lore/narrative)
- [x] `1.3` Fix `routing-rules.yaml` — `.url` extension fallback as own tier in classify()
- [x] `1.4` Fix `routing-rules.yaml` — Sentinel HTML demos → SEN/ui/
- [x] `1.5` Fix embedded tags regex — allow trailing text after tags before closing `*`
- [x] `1.6` Fix SEN log/CLN files → `[SEN][LOG]` (were hitting SEN_ARCH catch-all)
- [x] `1.7` Fix PKP.md + Hybrid_Org_Strat false-positive SEN_ARCH → PKP rules
- [x] `1.8` Fix SCHEMA_BOOTSTRAP → `[TIQ][ARCH]` (was hitting SEN_ARCH via content)
- [x] `1.9` Run scan — 61 files staged, classifications verified clean
- [x] `1.10` Review STAGING.md and execute batch — 50 files moved, 8 skipped (see note)
  - *Note: 8 files remain in drop/ for manual cleanup from delldev:*
  - *→ Delete: 4 `.url` shortcuts, `artifact-claude-chat-dump.zip`, `Full_Chat_Transcript_2026-03-22.txt`*
  - *→ Review: `VISION.pdf` (unclassified PDF — unknown content), `files.zip` (unknown zip)*

### PKM — Phase 3 (remaining)

- [x] `3.3` Stub `watcher.py` — orphaned sidecar detection placeholder

### PKM — Knowledge Gap Closure (2026-04-03)
#
# Goal: replace inference with documented ground truth in infrastructure/ YAML files.
# Files live at: AI-Workspace/PKP/infrastructure/
# For each task: open the file, fill in UNKNOWN entries, verify ASSUMED entries.
# When done, change comment to # KNOWN: verified [date]

- [ ] `KG.1` `nodes.yaml` — Verify/correct all ASSUMED entries. Fill in UNKNOWN hardware specs for delldev, mbp disk, omen CPU. (delldev: check Settings > About; mbp: About This Mac)
- [ ] `KG.2` `nodes.yaml` + `networks.yaml` — Fill in home network details: router, subnet, ISP, home IPs for each node. (check router admin panel)
- [ ] `KG.3` `nodes.yaml` — Fill in russ-iphone capture method: how do files get from iPhone to drop/ today? (nodes.yaml > russ-iphone > capture_to_vault.method)
- [ ] `KG.4` `domains.yaml` — Fill in drop/ readiness threshold: your personal rule for what goes in drop/. (domains.yaml > PKP > drop_readiness_threshold)
- [ ] `KG.5` `services.yaml` — Verify bossdev: is LiteLLM actually running? What port? What does it proxy to? (`ss -tlnp | grep litellm` on bossdev)
- [ ] `KG.6` `services.yaml` — Verify origin-core: is Docker installed? What services are running? (`which docker`, `systemctl list-units --state=running`)
- [ ] `KG.7` `services.yaml` — Fill in mini current purpose: what is mini actually being used for right now?
- [ ] `KG.8` `domains.yaml` — Fill in TrenchIQ: where does Postgres run for local dev? Where does Django dev server run?
- [ ] `KG.9` `domains.yaml` — Fill in SEN: where does world state JSON live? Where does lore live? Which node runs the agents?
- [ ] `KG.10` `primitives.yaml` — Fill in API key locations: which nodes have ANTHROPIC_API_KEY set? (delldev, bossdev, origin-core)

*Reference: AI-Workspace/PKP/infrastructure/ — README.md explains comment conventions*

### PKM — Recurring: Assumption Audit

- [ ] `⟳ RECUR` Before any architectural or operational session work, verify:
  - Are any pipeline assumptions from Assumption-Audit-2026-04-02.md now invalidated?
  - Have new assumptions been introduced by the previous session?
  - Does the mutation contract still reflect actual write authorities?
  - *Reference: AI-Workspace/PKP/docs/Assumption-Audit-2026-04-02.md*

### PKM — ADR-003 Candidates

- [ ] `ADR3.1` Define UUID ownership — who assigns it, at what point, and sorter UUID-preservation rule
- [ ] `ADR3.2` Define `classification_source` field — `rule-match | llm-tentative | human-confirmed` (modifies ADR-001)
- [ ] `ADR3.3` Codify single execution node rule — only one machine may hold execute() lock at a time
- [ ] `ADR3.4` Write ADR-003 with minimum scope: UUID ownership + classification_source (defer Pre-Stage-0 shapes)

### PKM — Architecture Priorities (from diagnostic 2026-04-02)

- [ ] `A.1` 3-2-1 backup — set up `rclone` on origin-core to mirror Dropbox to off-site location nightly
  - *Dropbox syncs deletes — it is not a backup. Define RTO/RPO first, then configure.*
- [ ] `A.2` Headless `--root` arg — add to `inbox_sorter.py` during Phase 4; enables any mesh node to run the sorter
- [ ] `A.3` Pre-commit hooks — add frontmatter schema validation at GitHub repo init (post Phase 4); blocks bad FM from reaching Hugo
- [ ] `A.4` Hugo Content Adapters PoC — before writing any Phase 6 templates, prove out Content Adapters pattern with one sidecar read
  - *Locked decision: no `.Site.Data` global loading in this project — see ADR-002*

### PKM — Doc Cleanup (MBP review 2026-04-02)

- [ ] `D.1` MCD.md — delete or reduce to pointer to CLAUDE.md
- [ ] `D.2` WORKSPACE-SYSTEM.md — archive (superseded by WORKSPACE-TARGET.md)
- [ ] `D.3` COWORK-SESSION-CONTEXT.md — archive or update; stale session goals + fixed bugs listed
- [ ] `D.4` ADR-001 + ADR-002 — check off completed action items (Phases 1–3 done)
- [ ] `D.5` WORKSPACE-TARGET.md §12 — update Known Gaps (FM injection done, backfill + folder rename still open)
- [ ] `D.6` WORKSPACE-TARGET.md §7 — add mbp to device mesh; rename russ-dell-laptop → delldev
- [ ] `D.7` DECISIONS.md — populate as canonical decision log or declare ROADMAP.md authoritative
- [ ] `D.8` ADR-002 — add "target state, not current" note to stage gate paths section

### PKM — Agent Log

- [ ] `L.1` Wire `execute()` in `inbox_sorter.py` to auto-append a summary block to `AGENT-LOG.md` after each batch run
  - *Fields: date, interface=inbox_sorter.py, host, task_ref (from arg or env), files_moved count, files_skipped count*
  - *Append-only — never overwrite existing entries*

### PKM — Backfill

- [ ] `backfill` Inject front matter into 50 files moved in Phase 1 (pre-Phase 2, no FM yet)
  - *Need a backfill script or sorter flag — run against vault destinations only*

### WORK — Job 1881

- [ ] `[WORK]` Job 1881 - Traffic Control Phasing Plan
  - [ ] `[WORK]` Job 1881 - Detour Plan Revision — Baseline Rd, Linden Ave to Maple Ave
- [ ] `[WORK]` Job 1881 - Intersection Flagging Plan — Idyllwild Ave
- [ ] `[WORK]` Job 1881 - Get Temporary Sewer Bypass Contingency Plan approved by Mike Pfister
- [ ] `[WORK]` Job 1881 - Submit Temporary Sewer Bypass Contingency Plan to City of Rialto (after approval)

### WORK — Admin

- [ ] `[WORK]` David Martinez — email setup — coordinate with ABSS Networks (support@abssnetworks.com)
  - [x] Confirmed employee: David Martinez
  - [x] Email sent to ABSS Networks re: setup (2026-04-03, 9:38 AM) — no ticket yet
  - [ ] ABSS Networks confirms fix applied
  - [ ] Verify David can send/receive

---

## Staging — Ready to Pass Through

Tasks that prep content for graduation to a project repo. Work happens here; output
drops into the target repo when done.

- [ ] `[TIQ→Git]` Condense Django model notes → clean schema decision doc for TIQ DB
  - Goal: one clear doc capturing the Labor/Equipment/Materials model decisions, ready to commit to russalo/cp-project DECISIONS.md or as a migration reference
  - Source: existing notes in AI-Workspace staging folders

---

## Waiting On

- [ ] `[WORK]` Dry Utility Takeoff for Rob Clark Construction — waiting on remaining plan sets
  - Have: SCE plans · Still need: Gas + all other dry utility sets
  - Waiting on: Mark Pfister

---

## PKM Backlog (Phases 4–6)

### PKM — Phase 4: Folder Rename

- [ ] `4.1` Create numbered folders alongside old structure (00_Inbox → 40_Prod → 99_Archive)
- [ ] `4.2` Update all hardcoded paths in `inbox_sorter.py`
- [ ] `4.3` Update all destination paths in `routing-rules.yaml`
- [ ] `4.4` Run scan to verify paths — do NOT execute until clean
- [ ] `4.5` Remove old folder structure after confirmed clean

### PKM — Phase 5: Enrich Scripts

- [ ] `5.1` Write `chunker.py` — split large session logs into topic files
- [ ] `5.2` Write `summarizer.py` — inject TL;DR for long docs
- [ ] `5.3` Write `tag_promoter.py` — promote inline #tags to front matter
- [ ] `5.4` Write `promote.py` — moves files between stages, updates `stage` field

### PKM — Phase 6: Hugo Publishing

- [ ] `6.1` Set up Hugo project at `AI-Workspace/hugo-site/`
- [ ] `6.2` Test `hugo serve` locally
- [ ] `6.3` Deploy on bossdev or origin-core — serve at Tailscale address
- [ ] `6.4` Add Hugo shortcodes for status badges, tag chips, sidecar indicators

---

## Someday

- [ ] `[Personal]` Renew truck registration

---

## Done

- [x] ~~`[WORK]` Job 1881 - Temporary Sewer Bypass Contingency Plan - Draft~~ (2026-03-18)
- [x] ~~`[PKM]` Phase 1 complete — routing rules fixed (1.1–1.9), 50 files executed to vault (1.10)~~ (2026-04-02)
- [x] ~~`[PKM]` Phase 2 complete — front matter injection, UUID, Type A sidecars; 27/27 tests pass~~ (2026-04-02)
- [x] ~~`[PKM]` Phase 3 (3.1, 3.2) complete — Type B JSON audit ledger, UUID linkage verified~~ (2026-04-02)
- [x] ~~`[PKM]` Write WORKSPACE-TARGET.md — full system target state monument~~ (2026-04-02)
- [x] ~~`[PKM]` Write ADR-001 — metadata schema (front matter, tags, sidecars)~~ (2026-04-02)
- [x] ~~`[PKM]` Write ADR-002 — pipeline architecture (stage gates, sorter contract)~~ (2026-04-02)
- [x] ~~`[PKM]` Write ROADMAP.md — 6-phase implementation plan~~ (2026-04-02)
- [x] ~~`[PKM]` Unify STAGING.md tags across all 57 files~~ (2026-04-01)
- [x] ~~`[PKM]` Set up PyCharm project with Scan Inbox + Execute Staging run configs~~ (2026-04-01)
