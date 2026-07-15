# 11 · Tiered routing — block / review / pass, on the signal

**Concept:** an all-or-nothing gate ("is this file safe? yes/no") throws away most of what File
Observer tells you. The per-file signal — `safety_flags` + which lexicon **category** hit — lets a
consumer route each file to a *tier*: **block** it, send it for lighter **review**, or **pass** it
through. This is the capstone of the "consume untrusted files safely" arc: **detect** (lexicon) →
**safe hand-off** (`--trusted-only`) → **route by tier** (here) → **audit** (`--receipt`).

**The one rule:** File Observer *observes*, you *decide*. It emits the counts and flags; the **policy**
that maps a category or flag to a tier is yours — never a File Observer verdict.

## Route on the receipt

`--receipt` gives a compact, safe, per-file record that already carries everything routing needs —
`safety_flags`, the lexicon `categories`, and a `receipt_id` (the join key a downstream read/skip log
references). Routing on it also *closes the audit bridge*: your decision points back at the exact
`receipt_id` File Observer emitted.

```json
{ "receipt_id": "b5a807…", "path_id": "…",
  "safety_flags": ["lexicon_match"],
  "lexicon": { "categories": { "secrets": 1, "profanity": 0 }, … } }
```

## The consumer policy (`route.py`)

The whole decision is a small, editable map — this is *your* policy, not File Observer's:

```python
CATEGORY_TIER = {"secrets": "block", "profanity": "review"}
FLAG_TIER     = {"has_macros": "block", "has_javascript": "review"}
# most-severe tier wins; default is "pass"
```

`route.py` reads the receipt on stdin, applies the map, and buckets each file.

## Run it

```bash
./run.sh
```

## What you'll see

```text
[BLOCK] 2 file(s)
    receipt_id=…  driver=secrets(metadata)
    receipt_id=…  driver=secrets
[REVIEW] 1 file(s)
    receipt_id=…  driver=profanity
[PASS] 1 file(s)
    receipt_id=…  driver=—
```

`credentials.md` tripped the `secrets` category in its **body** → **block**; `banana-backup.md` tripped
`secrets` in its **filename** (metadata, `secrets(metadata)`) → **block** — a term hiding where the body
scan can't look still routes (the v1.41 metadata sweep); `transcript.md` tripped `profanity` →
**review**; `readme.md` was clean → **pass**. Change the policy map and the routing changes — File
Observer's output didn't.

## Why this is safe

The receipt carries **no raw path or content** — a `receipt_id` / `path_id` correlates each decision
back to a file *you* hashed, so the routing input is safe to persist and to feed a model. The lexicon
terms never appear (only per-category counts). And File Observer records only what it *saw* — it never
records the block/review/pass decision itself; that stays *your* orchestrator's log, joined to fo's
observation by the `receipt_id`.

See also: [10 — lexicon screen](../10-lexicon-screen/) (the detect step), [09 — safe mode](../09-trusted-only/)
(the safe hand-off), and the tutorial's safety sections.
