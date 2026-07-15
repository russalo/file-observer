#!/usr/bin/env bash
# Example 11 — tiered routing: a consumer block/review/pass policy over fo's receipt.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf out && mkdir -p out
echo "Screening uploads/ → receipt, then applying the CONSUMER routing policy (route.py)…"
file-observer uploads --specialists --lexicon lexicon.txt --receipt --stdout \
  > out/receipt.json 2> out/scan.log
echo
python3 route.py < out/receipt.json
