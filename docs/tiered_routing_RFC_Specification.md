# RFC — Tiered-routing consumption pattern (docs + example)

**Status:** APPROVED (2026-07-15)
**Author:** file-observer Claude · **Date:** 2026-07-15
**Version axes:** **docs / examples only — NO code, NO manifest change.** SCANNER / LOGIC / SCHEMA all
**FROZEN**. Ships as a docs PR (the v1.43 doc-sweep / example-10 precedent — a new example + a tutorial
section, no version bump). *(D0: version treatment is a decision — see §5.)*
**Issue:** #135 (r/mcp feedback). Capstone of the consumption-safety arc (v1.40 prevention / v1.41
detection / v1.42 audit bridge / v1.43 loader / v1.44 category-survival).

---

## 1. Motivation

The r/mcp thread asked for **tiered routing on the per-file signals** — "blocking-for-flagged vs
advisory-for-rest" — instead of an all-or-nothing gate. fo already emits everything a consumer needs to
do this; what's missing is a *runnable demonstration* that turns the capability into a pattern.

Two recent releases made the pattern first-class:
- **v1.42 `--receipt`** — a compact, safe, per-file audit record carrying `receipt_id`, `path_id`,
  `safety_flags`, and a lexicon hit-summary.
- **v1.44** — the lexicon **per-category** breakdown now survives the safe projection, so routing can be
  *by category*, not just presence.

Measured (2026-07-15), a per-file receipt record with a lexicon:
```json
{ "receipt_id": "742c…", "path_id": "fecc…",
  "safety_flags": ["lexicon_match"],
  "lexicon": { "body_hits": 1, "metadata_hits": 0,
               "categories": { "secrets": 1, "profanity": 0 }, "metadata_categories": {} } }
```
That is *exactly* a tiered-routing input: `safety_flags` + per-category counts, keyed by an id, with no
raw path or content. The gap is purely demonstrative.

## 2. The charter boundary (load-bearing)

**fo observes; the consumer decides.** fo supplies the *signal* (flags, per-category counts); the
routing **policy** — which signal maps to which tier, and the thresholds — is the consumer's, always.
The example must make this unmistakable: the policy map is clearly the *consumer's*, editable, and
labelled as a decision, never a fo verdict. This is observe-don't-interpret made concrete, and it's why
#135 is *docs*, not a fo feature — fo will never route, threshold, or decide read/skip (the same charter
line as `--receipt`, which records what fo saw, never what you did).

## 3. Design — route on the receipt

The recommended input is the **`--receipt`** output (grounded in §1): it's compact, safe by
construction (no raw path/content), purpose-built as the observation↔decision bridge, and it already
carries `safety_flags` + `lexicon.categories` per file. Routing on it also *demonstrates* the bridge —
the consumer's read/skip decision references the `receipt_id` fo emitted, so the two honest logs meet.

**Three tiers** (the r/mcp "blocking vs advisory", generalized):

| tier | meaning | example driver |
|---|---|---|
| **block** | do not feed to the model (reject / human review) | a high-risk category hit (`secrets`) or a hard safety_flag (`has_macros`) |
| **review** | feed, but flag/log for a lighter pass | a softer category (`profanity`) or a soft flag |
| **pass** | feed normally | no hit |

The consumer supplies a **policy map** — `{category → tier}` and `{safety_flag → tier}`, with `pass` as
the default — and each file gets the **most severe** matching tier. fo never supplies this map.

## 4. What ships

- **`examples/11-tiered-routing/`** — a runnable example: a small `uploads/` tree, a benign lexicon whose
  categories map to tiers, and a `route.py` consumer script that reads `fo … --lexicon … --receipt` and
  buckets each file → block / review / pass by the consumer policy map, printing `receipt_id → tier` (and
  the driving signal). Live-verified excerpt; benign placeholder terms only.
- **A tutorial section** ("Routing on the signal — tiered consumption"), closing the arc explicitly:
  **detect** (§12 lexicon) → **safe hand-off** (§11 `--trusted-only`) → **route by tier** (this) →
  **audit** (§13 `--receipt`). Fixes the loop the r/mcp thread opened.
- Examples-index row (11); README one-liner if it fits the Scan section.

## 5. Decisions (forks + leans)

- **D0 — version treatment.** (a) docs-only PR, no version bump (example-10 / PR #145 precedent) · (b) a
  versioned minor for attribution + a HISTORY row. **Lean: (a)** — it's docs + an example, no code; a
  SCANNER bump for pure docs overstates it.
- **D1 — tiers.** 3 (block/review/pass) vs 2 (block/advisory, the literal r/mcp framing). **Lean: 3** —
  strictly more useful; the 2-tier is the degenerate case (drop `review`).
- **D2 — signal source.** lexicon categories only / safety_flags only / **both**. **Lean: both** — the
  example shows category-driven *and* flag-driven routing composing (max-severity wins); real consumers
  use both.
- **D3 — routing input.** the `--receipt` output vs the `--trusted-only` manifest. **Lean: receipt** —
  compact, purpose-built, and it demonstrates the bridge; note `--trusted-only` works too (a footnote).
- **D4 — placement.** a new example 11 + a tutorial section (discoverable, matches 08/09/10) vs folding
  into §12. **Lean: new example + section.**

## 6. Non-goals

- **fo does not route, threshold, or decide.** This is a *recommended consumer pattern*, not a fo
  feature — no CLI flag, no manifest field. The policy is the consumer's.
- Not a per-consumer connector (the recipes-not-connectors rule) — a generic, editable example.
- No new lexicon capability; no MCP change. The receipt / trusted-only / lexicon surfaces are as shipped.

## 7. Verification

The example's committed excerpt is verified against a live scan (the examples convention); `route.py`
runs on the freshly-scanned receipt and prints deterministic tier assignments. No fo behavior changes, so
no test-suite change — the drift-guards + the examples index row cover it.
