#!/usr/bin/env bash
# Example 02 — PDF specialist extraction. Pulls structured metadata out of a PDF.
# Run from anywhere; writes the manifest + human report to ./out/.
# Needs the [pdf] extra for object-stream / encrypted PDFs:  pip install "file-observer[pdf]"
set -euo pipefail
cd "$(dirname "$0")"
rm -rf out          # start clean so re-runs don't accumulate timestamped manifests
file-observer sample_pdf --specialists -o out
echo
echo "Manifest + report written to ./out/. Open the manifest and look at"
echo "files[0].specialist_metadata.pdf and the provenance vector in"
echo "vectors_collected[] — that's what --specialists added."
