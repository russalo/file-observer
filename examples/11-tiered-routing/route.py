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
    for flag in rec.get("safety_flags", []):
        if flag in FLAG_TIER:
            drivers.append(flag)
            if TIER_RANK[FLAG_TIER[flag]] > TIER_RANK[tier]:
                tier = FLAG_TIER[flag]
    for cat, n in (rec.get("lexicon") or {}).get("categories", {}).items():
        if n > 0 and cat in CATEGORY_TIER:
            drivers.append(cat)
            if TIER_RANK[CATEGORY_TIER[cat]] > TIER_RANK[tier]:
                tier = CATEGORY_TIER[cat]
    return tier, drivers


receipt = json.load(sys.stdin)
buckets = {"block": [], "review": [], "pass": []}
for rec in receipt["receipts"]:
    tier, drivers = route(rec)
    buckets[tier].append((rec["receipt_id"][:12], drivers))

for tier in ("block", "review", "pass"):
    print(f"[{tier.upper()}] {len(buckets[tier])} file(s)")
    for rid, drivers in buckets[tier]:
        print(f"    receipt_id={rid}…  driver={', '.join(drivers) or '—'}")
