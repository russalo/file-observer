# Documentation Review — Next-Agent Readability Audit
**Date:** 2026-04-02
**Reviewer:** Cowork session on MBP (this session)
**Scope:** All documentation a new agent would encounter following the session start checklist

---

## What I Did

Read every file in the chain a new agent would follow: `/mnt/CLAUDE.md` (local) → `/mnt/Claude/CLAUDE.md` (shared) → TASKS.md → ROADMAP.md → ADR-001 → ADR-002 → WORKSPACE-TARGET.md → WORKSPACE-SYSTEM.md → COWORK-SESSION-CONTEXT.md → routing-rules.yaml → inbox_sorter.py header → MCD.md → DECISIONS.md. Also checked the project lane folders (SEN/, TIQ/, PKP/) and the STAGING.md queue.

---

## Overall Assessment

The documentation is strong. An agent following the session start checklist would understand the project, its scope, the pipeline architecture, and what to do. The problems are not missing information — they're **stale state**, **duplication with drift**, and **unclear authority** between overlapping docs.

---

## Problem 1: CLAUDE.md "Current Pipeline State" is frozen at pre-Phase 1

The shared CLAUDE.md (lines 144–152) says:

> "Phase 1 active — fix four routing rule bugs, then execute the 57-file batch"
> "Sorter does NOT yet inject front matter or create sidecars (Phase 2)"

Phases 1, 2, and 3 are done. 50 files moved. Front matter injection working. Audit ledgers working. An agent reading this would think it needs to start fixing routing rules that are already fixed.

**Fix:** Update the "Current Pipeline State" section in CLAUDE.md to reflect Phases 1–3 complete. Point to ROADMAP.md for live status instead of duplicating phase state inline.

---

## Problem 2: MCD.md is stale and redundant

`MCD.md` in the project root duplicates the project instructions from the Cowork project settings and the CLAUDE.md "Working in This Cowork Project" section. Its "Current state" line says "Phase 1 active." It adds nothing that isn't already in CLAUDE.md or the Desktop per-project instructions.

**Fix:** Either delete MCD.md or convert it to a one-liner that says "See CLAUDE.md § Working in This Cowork Project." Right now it's a stale copy that will mislead an agent that reads it.

---

## Problem 3: WORKSPACE-SYSTEM.md vs WORKSPACE-TARGET.md — unclear which is authoritative

Both describe the pipeline, folder structure, and tag taxonomy. WORKSPACE-SYSTEM.md is dated 2026-04-01 and uses the old folder paths (`inbox/drop/`, no numbered stages). WORKSPACE-TARGET.md is dated 2026-04-02 and is explicitly labeled "the North Star." But a new agent reading WORKSPACE-SYSTEM.md first would get confused — it describes a simpler pipeline that contradicts the target.

WORKSPACE-SYSTEM.md also has a "What's Still To Define" section listing things that are now defined (routing rules, sorter script). Its "Known Issues in Sorter" are all fixed.

**Fix:** Either archive WORKSPACE-SYSTEM.md (move to 99_Archive or mark as superseded) or merge its unique content into WORKSPACE-TARGET.md. There should be one authoritative system design doc, not two with conflicting states.

---

## Problem 4: COWORK-SESSION-CONTEXT.md is stale

This file (lines 80–115) has session goals from 2026-04-01 with a mix of checked and unchecked items. Its "Known Issues in Sorter" section lists five bugs — all now fixed. Its "Hardware Available" section doesn't include the MBP's current role or Ollama. Its "Current Session Goals" section says "Replace this section each session" but hasn't been replaced.

**Fix:** Either update it to current state or mark it as a session-log artifact and stop pointing agents to it. Right now it's a trap — it looks current but isn't.

---

## Problem 5: AI & Automation Stack in CLAUDE.md is stale

Lines 78–85 of the shared CLAUDE.md say:

> "LiteLLM — not yet installed anywhere (planned)"
> "Ollama — not yet installed anywhere (planned — omen is primary target once integrated)"

LiteLLM is on bossdev. Ollama is on the MBP with qwen3-coder:30b running. Claude Code is on the MBP. This section hasn't been updated to match reality.

**Fix:** Update the AI & Automation Stack section to reflect installed state. Point to `system_state.yaml` as the authoritative source rather than maintaining a parallel list.

---

## Problem 6: ADR-001 and ADR-002 action items don't reflect completed work

Both ADRs have Phase 1–3 action items still showing unchecked checkboxes, even though the work is done. ROADMAP.md and TASKS.md have been updated correctly, but the ADR action item lists have not.

**Fix:** Check off completed items in ADR-001 (§ Action Items) and ADR-002 (§ Action Items). The ADRs should reflect the decision AND the execution status. Alternatively, remove the action item sections from ADRs entirely and point to TASKS.md — action tracking in two places guarantees drift.

---

## Problem 7: WORKSPACE-TARGET.md § Known Gaps is stale

Section 12 lists gaps like "Sorter does not inject front matter" and "Sorter does not create Type A sidecars" — both now working. Several of the 8 gaps listed are resolved.

**Fix:** Update §12 to mark resolved gaps and add any new ones (e.g., "50 Phase 1 files need front matter backfill", "Folder structure not yet renamed to numbered scheme").

---

## Problem 8: WORKSPACE-TARGET.md § Device Mesh doesn't include MBP

Section 7 lists machine roles but doesn't mention the MBP at all. It lists `russ-dell-laptop` (now `delldev`) as the hands/HITL machine and `omen` as the future GPU node. The MBP is the most capable node on the mesh and isn't represented.

**Fix:** Add `mbp` to §7 with its role (always-on Cowork + local LLM). Update `russ-dell-laptop` to `delldev`.

---

## Problem 9: DECISIONS.md is empty

The file exists in `context/` but has no content. Decisions are being logged in ROADMAP.md (Decision Log table), WORKSPACE-SYSTEM.md (Decisions Log section), and ADR-001/002 (inline). There's no single place to check "what was decided and why."

**Fix:** Either populate DECISIONS.md as the canonical decision log and stop duplicating decisions in other files, or delete it and declare ROADMAP.md's Decision Log table as authoritative. Russell's preference ("Decisions go in DECISIONS.md before context is lost") suggests the former.

---

## Problem 10: Folder structure is not yet numbered but docs assume it

WORKSPACE-TARGET.md describes `00_Inbox/`, `10_Staging/`, `40_Prod/` etc. The actual filesystem still uses `inbox/`, `SEN/`, `TIQ/`, etc. (old flat structure). ROADMAP.md correctly notes this is a Phase 4 task. But ADR-002 references `10_Staging/` paths as if they exist. A new agent reading ADR-002 might try to write to `10_Staging/WORK/1881/` and find it doesn't exist.

**Fix:** This is a known Phase 4 task, not a documentation bug per se. But ADR-002 should note explicitly that the numbered paths are target state, not current state, to avoid confusion. A one-line note at the top of the Stage Gate Model section would suffice.

---

## Summary of Recommended Actions

| # | File | Action | Effort |
|---|------|--------|--------|
| 1 | CLAUDE.md | Update "Current Pipeline State" to Phases 1–3 complete | 5 min |
| 2 | MCD.md | Delete or reduce to pointer | 2 min |
| 3 | WORKSPACE-SYSTEM.md | Archive or merge into TARGET | 15 min |
| 4 | COWORK-SESSION-CONTEXT.md | Update or archive | 10 min |
| 5 | CLAUDE.md | Update AI & Automation Stack section | 5 min |
| 6 | ADR-001 + ADR-002 | Check off completed action items or remove action sections | 10 min |
| 7 | WORKSPACE-TARGET.md §12 | Update known gaps | 5 min |
| 8 | WORKSPACE-TARGET.md §7 | Add MBP to device mesh | 5 min |
| 9 | DECISIONS.md | Populate or declare another file authoritative | 15 min |
| 10 | ADR-002 | Add "target state, not current" note to stage gate section | 2 min |

Total estimated effort: ~75 minutes of focused cleanup.

---

## What Works Well

The session start checklist in CLAUDE.md is the right pattern — it gives a new agent a clear reading order. TASKS.md is well-structured with clear tags and phase grouping. ROADMAP.md is the best-maintained file — current state section is accurate, phases are marked correctly. The routing-rules.yaml has excellent inline comments explaining rule ordering. ADR-001 and ADR-002 are thorough architectural decisions that give strong context on *why* the system works this way.

The main issue is not quality — it's currency. The docs were written fast during a productive sprint and the system state moved faster than the documentation could keep up. A single cleanup pass would bring everything into alignment.
