#!/usr/bin/env python3
"""Example 11 — a CONSUMER's tiered-routing policy over File Observer's screening receipt.

File Observer OBSERVES (it emits per-file `safety_flags` + lexicon `categories` in the receipt);
the CONSUMER DECIDES. The POLICY below is yours to edit — it is NOT a File Observer verdict.
Reads a receipt on stdin (`fo … --lexicon … --receipt --stdout`), buckets each file by the
most-severe matching tier, and keys the decision by `receipt_id` — the bridge id a downstream
read/skip log references.
"""
import json
import sys

# --- YOUR policy (edit this) — category / safety_flag -> tier -----------------------------
CATEGORY_TIER = {"secrets": "block", "profanity": "review"}
FLAG_TIER = {"has_macros": "block", "has_javascript": "review"}
TIER_RANK = {"pass": 0, "review": 1, "block": 2}          # most-severe wins
# -----------------------------------------------------------------------------------------


def route(rec):
    """Return (tier, drivers) for one receipt record — pure consumer logic over fo's signal."""
    tier, drivers = "pass", []

    def bump(t):
        nonlocal tier
        if TIER_RANK[t] > TIER_RANK[tier]:
            tier = t

    for flag in rec.get("safety_flags", []):
        if flag in FLAG_TIER:
            drivers.append(flag)
            bump(FLAG_TIER[flag])
    # A category hit in the BODY *or* the file-derived metadata (filename / EXIF / producer, v1.41)
    # counts — a term hiding in metadata is exactly what the body scan can't see.
    lex = rec.get("lexicon") or {}
    body, meta = lex.get("categories", {}), lex.get("metadata_categories", {})
    for cat in sorted(set(body) | set(meta)):
        if cat not in CATEGORY_TIER:
            continue
        b, m = body.get(cat, 0), meta.get(cat, 0)
        if b > 0 or m > 0:
            drivers.append(cat if b > 0 else f"{cat}(metadata)")
            bump(CATEGORY_TIER[cat])
    return tier, drivers


try:
    receipt = json.load(sys.stdin)
    records = receipt["receipts"]
except (json.JSONDecodeError, KeyError, TypeError):
    sys.exit("route.py: expected a file-observer `--receipt` JSON document on stdin")
buckets = {"block": [], "review": [], "pass": []}
for rec in records:
    tier, drivers = route(rec)
    buckets[tier].append((rec["receipt_id"][:12], drivers))

for tier in ("block", "review", "pass"):
    print(f"[{tier.upper()}] {len(buckets[tier])} file(s)")
    for rid, drivers in buckets[tier]:
        print(f"    receipt_id={rid}…  driver={', '.join(drivers) or '—'}")
