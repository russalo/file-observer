# Front Matter Schema Review

Evaluation of ADR-001 / WORKSPACE-TARGET §3 schema against sorting goals.
**Date:** 2026-04-02
**Reviewed by:** Claude Code (bossdev)

---

## What's Working Well

The schema is clean and the implementation in `build_front_matter()` matches the spec
closely. The two-layer approach (YAML for machines, inline `#tags` for humans) is the
right call — no friction between sorter automation and Obsidian usage.

Good decisions already locked in:
- `uuid` as stable link between front matter and Type B JSON — survives renames
- `source` derived from filename prefix (`gdrive`, `cowork`, `drop`) — zero effort
- `stage` mirroring the folder number — single source of truth with a readable alias
- Folder path as primary taxonomy — avoids redundant `project` + `tags` repeating what
  the path already says

---

## Recommendations

### 1. `project` is redundant with the folder — keep it anyway

The folder path already encodes project (`SEN/`, `WORK/`, etc.), and WORKSPACE-TARGET
§2 calls this out: "Folder path IS the primary taxonomy." But `project` in front matter
is still necessary for Hugo taxonomy queries and Obsidian Dataview. No change needed —
just confirming this is the right tradeoff.

### 2. `tags` field is doing double duty — split project tags from domain tags

Right now `parse_tags("[WORK][1881]")` returns `project="WORK", tags=["1881"]`. That
works for simple cases, but look at `[SEN][OSS][ART]` — the sorter puts `SEN` in
`project` and `["OSS", "ART"]` in `tags`. Meanwhile `[WORK][DOCTOOLS][PDF][CONVERTER]`
produces `tags: ["DOCTOOLS", "PDF", "CONVERTER"]`.

The problem: `PDF` and `CONVERTER` are **format/type descriptors**, not the same kind of
thing as `DOCTOOLS` or `OSS`. When Hugo builds a `/tags/PDF/` taxonomy page, you'll get
every PDF in the system — not useful. And `CONVERTER` is a tool category, not a document
topic.

**Recommendation:** Strip format/type tags (`PDF`, `XLSX`, `CONVERTER`, `GEN`, `LOG`)
from the front matter `tags` field. Either:
- (a) Don't put them in `tags` at all — the file extension already tells you it's a PDF
- (b) Add a separate `type` field: `type: pdf-converter` or `type: session-log`

Option (a) is simpler and sufficient for now. In `routing-rules.yaml`, the `[WORK][DOCTOOLS][PDF][CONVERTER]` tag string is only used for routing — the front matter
doesn't need all four. The rule's `front_matter.tags` override could explicitly list
only the meaningful tags:

```yaml
- label: "WORK_DOCTOOLS_PDF"
  tags: "[WORK][DOCTOOLS][PDF][CONVERTER]"  # used for routing
  front_matter:
    project: "WORK"
    sub_project: "DOCTOOLS"
    tags: [DOCTOOLS]                         # only meaningful tags in front matter
```

This keeps routing working (all four tags resolve destinations) while front matter stays
clean. The `parse_tags()` auto-derivation becomes the fallback, not the primary source.

### 3. `sub_project` should be promoted from optional to auto-populated

ADR-001 lists `sub_project` as optional/human-added, but the routing rules already know
it — `WORK_1881` has `sub_project: "1881"`, `WORK_DOCTOOLS_*` has `sub_project: "DOCTOOLS"`.
The sorter already injects it from `rule['front_matter']`.

The schema doc should reflect reality: `sub_project` is **sorter-injected when known,
human-editable otherwise**. Not purely optional.

### 4. Missing field: `rule_matched` in front matter

The Type B JSON records which rule classified the file (`rule_matched: "WORK_1881"`),
but the front matter doesn't. This is useful for debugging misclassifications — you can
open any `.md` file and immediately see *why* it landed here without hunting for the
hidden JSON sidecar.

**Recommendation:** Add `rule_matched` as an optional front matter field, injected by
the sorter. Light, useful, zero human effort:

```yaml
---
uuid: "..."
title: "..."
project: WORK
tags: [1881]
date: 2026-04-02
source: drop
status: staged
stage: staging
rule_matched: WORK_1881
---
```

### 5. `title` derivation loses information on some filenames

`derive_title()` strips `gdrive-SEN-` prefixes and date patterns, which is good. But
for files like `Absolutely—this is the right move.md`, the title becomes the entire
filename minus `.md` — which is a sentence fragment from a chat, not a useful title.

This is a human-review problem, not an automation problem. The sorter can't know what a
good title is for ambiguous filenames. But consider adding a `title_source: derived`
field so future scripts (or the human during HITL) can filter for files that need title
cleanup. Low priority — Phase 3+ concern.

### 6. `date` should prefer embedded dates over file mod time

`build_front_matter()` uses `file_path.stat().st_mtime`. But Dropbox sync changes mtime
on every machine — the file mod date on bossdev won't match the original creation date.
Files like `Brainstorm Summary 2026-03-26.pdf` have the real date *in the filename*.

**Recommendation:** Add a date extraction step before falling back to mtime:

```python
# Try filename date first
date_match = re.search(r'(\d{4}[-_]\d{2}[-_]\d{2})', filename)
if date_match:
    file_date = date_match.group(1).replace('_', '-')
else:
    file_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
```

This is a small change with high value — the date field becomes meaningful rather than
reflecting "when Dropbox last synced."

### 7. `render_front_matter()` doesn't quote tag values

Line 311: `tags: [{", ".join(tags)}]` produces `tags: [1881, ARCH]`. YAML parsers will
read `1881` as an integer, not a string. Hugo and Obsidian may handle this fine in
practice, but it's a latent bug.

**Recommendation:** Quote tag values:

```python
tags_str = ", ".join(f'"{t}"' for t in tags)
lines.append(f'tags: [{tags_str}]' if tags else "tags: []")
```

Produces `tags: ["1881", "ARCH"]` — unambiguously strings.

---

## Summary — Priority Order

| # | Change | Effort | Impact | When |
|---|--------|--------|--------|------|
| 7 | Quote tag values in render | One line | Prevents YAML type bugs | Now |
| 6 | Filename date extraction | ~5 lines | Meaningful dates vs mtime noise | Now |
| 4 | Add `rule_matched` to front matter | ~3 lines | Debug misclassifications fast | Now |
| 2 | Strip format tags from front matter | YAML edits | Cleaner Hugo taxonomies | Phase 2 |
| 3 | Document `sub_project` as auto-populated | Doc edit | Schema matches reality | Phase 2 |
| 5 | `title_source` field | Low priority | HITL title cleanup | Phase 3+ |
| 1 | No change needed | — | Confirming existing decision | — |
