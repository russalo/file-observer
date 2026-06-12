#!/usr/bin/env bash
# Example 01 — your first scan. Produces the full manifest for sample_project/.
# Run from anywhere; writes the manifest + human report to ./out/.
set -euo pipefail
cd "$(dirname "$0")"
file-observer sample_project -o out
echo
echo "Manifest + report written to ./out/. The manifest is the JSON; the .md is"
echo "the human-readable summary. Re-run and the manifest_checksum is identical"
echo "(scan_id / generated_at are excluded from the checksum — that's the point)."
