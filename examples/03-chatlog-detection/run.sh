#!/usr/bin/env bash
# Example 03 — content-detected chatlog. No extension trick; it reads the shape.
# Run from anywhere; writes the manifest + human report to ./out/.
set -euo pipefail
cd "$(dirname "$0")"
# is_chatlog is set even without --specialists; --specialists adds the rich
# turn/speaker breakdown and the chatlog vector.
file-observer sample_logs --specialists -o out
echo
echo "Manifest + report written to ./out/. Look at files[0].is_chatlog,"
echo "files[0].specialist_metadata.chatlog, and the chatlog vector in"
echo "vectors_collected[]."
