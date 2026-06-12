#!/usr/bin/env bash
# Example 04 — determinism. Scan the same bytes twice; the checksum is identical.
# Run from anywhere. Writes two manifests to ./out/ and diffs their checksum.
set -euo pipefail
cd "$(dirname "$0")"

file-observer sample_data -o out/run-a
file-observer sample_data -o out/run-b

a=$(python3 -c "import json,glob;print(json.load(open(glob.glob('out/run-a/manifest_*.json')[0]))['manifest_checksum'])")
b=$(python3 -c "import json,glob;print(json.load(open(glob.glob('out/run-b/manifest_*.json')[0]))['manifest_checksum'])")

echo
echo "run A manifest_checksum: $a"
echo "run B manifest_checksum: $b"
if [ "$a" = "$b" ]; then
  echo "IDENTICAL — same bytes in, same observation out."
else
  echo "DIFFERENT — that should not happen for unchanged input."
  exit 1
fi
