#!/usr/bin/env bash
# Example 06 — schema discovery. Ask file-observer what it can emit. No scan.
# Run from anywhere; writes both schema formats to ./out/.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out

# JSON: machine-readable, for a consumer to load.
file-observer --schema --schema-format json > out/schema.json
# Markdown: human-readable, the same thing docs/SCHEMA.md is generated from.
file-observer --schema --schema-format md   > out/schema.md

echo "Wrote out/schema.json and out/schema.md."
echo "This introspects the installed build — no directory is scanned."
echo
echo "Surface summary:"
python3 -c "
import json
d=json.load(open('out/schema.json'))
print(f\"  scanner {d['scanner_version']} / logic {d['logic_version']} / schema {d['schema_version']}\")
for k in ('manifest','specialists','vectors','provenance_triggers','error_codes','safety_flags','format_signatures'):
    print(f'  {k}: {len(d[k])}')
"
