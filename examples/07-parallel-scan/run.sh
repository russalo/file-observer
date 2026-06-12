#!/usr/bin/env bash
# Example 07 — parallel scan. More workers = faster; the output is byte-identical.
# Run from anywhere. Scans with 1 and 4 workers and compares the checksum.
set -euo pipefail
cd "$(dirname "$0")"

file-observer sample_tree --workers 1 -o out/w1
file-observer sample_tree --workers 4 -o out/w4

w1=$(python3 -c "import json,glob;print(json.load(open(glob.glob('out/w1/manifest_*.json')[0]))['manifest_checksum'])")
w4=$(python3 -c "import json,glob;print(json.load(open(glob.glob('out/w4/manifest_*.json')[0]))['manifest_checksum'])")

echo
echo "workers=1 manifest_checksum: $w1"
echo "workers=4 manifest_checksum: $w4"
if [ "$w1" = "$w4" ]; then
  echo "IDENTICAL — parallelism changed the speed, not the observation."
else
  echo "DIFFERENT — that must never happen; worker count is not allowed to affect output."
  exit 1
fi
