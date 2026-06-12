#!/usr/bin/env bash
# Example 05 — delta scan. Scan, change some files, rescan against the first
# manifest, and read what changed out of the `delta` block.
# Works on a COPY under ./out/work so the committed sample_repo/ stays pristine.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf out && mkdir -p out
cp -r sample_repo out/work

# 1. First scan — the baseline.
file-observer out/work -o out/prev
prev=$(ls out/prev/manifest_*.json)

# 2. Change the tree: modify a file, add one, remove one.
printf '\ndef farewell(name):\n    return f"bye, {name}"\n' >> out/work/app.py
echo "DEBUG=true" > out/work/.env.example
rm out/work/config.yaml

# 3. Rescan against the first manifest.
file-observer out/work --previous-manifest "$prev" -o out/now

echo
echo "delta block:"
python3 -c "import json,glob;print(json.dumps(json.load(open(glob.glob('out/now/manifest_*.json')[0]))['delta'], indent=2))"
