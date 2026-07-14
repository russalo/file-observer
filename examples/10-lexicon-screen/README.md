# 10 · Bring-your-own lexicon — screen untrusted files before an AI reads them

**Concept:** File Observer is *not* an AI, so it can safely read files an LLM shouldn't.
Give it a consumer-supplied **lexicon** — category-tagged terms you care about — and it
counts them per file and raises a `lexicon_match` flag on any hit. You get a cheap,
deterministic **pre-screen**: know a file is a guardrail-trip risk *before* it reaches a model.

It is an **observation, never a verdict** — fo reports counts and density; *you* set the
threshold and decide what to do.

## The lexicon (`lexicon.txt`)

An **EasyList-style** text list (JSON is also accepted):

```text
! Title: example-content-screen
! Version: 2026.07
[fruit]
banana
cherry
mango
[placeholder-flag]
example-marker
sample-flagword
```

`!`/`#` are comments; `! Key: value` is a header; `[name]` opens a category; every other
line is one literal term. The terms here are **benign placeholders** — a real deployment
supplies its own sensitive lists and keeps them out of version control.

## Run it

```bash
./run.sh
```

`run.sh` scans `sample_uploads/` with `--lexicon lexicon.txt`.

## What you'll see

```text
--- load-time provenance (goes to STDERR; never the manifest) ---
file-observer: loaded lexicon source 'lexicon.txt' [example-content-screen] · 5 terms · v2026.07

--- lexicon vector: per-category counts across the corpus ---
{
  "lexicon_id": "example-content-screen",
  "files_matched": 1,
  "category_hits": {
    "fruit": 2,
    "placeholder-flag": 1
  }
}

--- files a consumer would route to review (lexicon_match flag) ---
  uploaded_note.md -> ['lexicon_match']
```

`uploaded_note.md` tripped the screen (it mentions `banana`, `cherry`, `example-marker`);
`clean_readme.md` did not.

## The privacy boundary

The lexicon's **term list is never emitted** — the manifest carries only the term-free derived
results: per-category **counts + density** (and `total_hits`/`total_tokens`), the **category
names**, and a content-hash **`dictionary_id`** (which moves if the list changes, catching silent
drift). File Observer never echoes the terms themselves from your config file — into the manifest
or its error logs.

One nuance the example proves: a term that *also* appears in a scanned document's body shows
up in **that file's `content_preview`** — as the document's own (untrusted) content, not as a
lexicon term. Strip those before handing the manifest to a model with **`--trusted-only`**
(see [example 09](../09-trusted-only/)).

## More ways to source a lexicon

- **JSON** instead of text: `{"lexicon_id": "...", "categories": {"cat": ["term", ...]}}`.
- **Compose several lists:** repeat the flag — `--lexicon base.txt --lexicon overlay.json`
  (unioned, order-independent).
- **A subscription index:** `--lexicon-index lists.txt` names member lists to union.
- fo composes **local** files only — it never fetches; keep your lists updated with whatever
  tool you like.

## Where this fits

This is the **detection** step of the "consume untrusted files safely" arc:
**detect** (this lexicon screen) → **safe hand-off** (`--trusted-only`, [example 09](../09-trusted-only/))
→ **audit** (`--receipt`). See the tutorial's safety section for the full story.
