#!/usr/bin/env bash
# Example 09 — safe mode. Project a scan down to ONLY fo-derived (trusted) signal, so the
# manifest is safe to hand straight to a model. Run from anywhere; writes to ./out/.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf out; mkdir -p out

# Normal scan: the manifest faithfully ECHOES attacker-controllable strings — the filename,
# the frontmatter author, the content_preview. Useful, but NOT safe to feed a model verbatim.
file-observer sample_docs --specialists --stdout > out/normal.json

# Safe mode: --trusted-only nulls every file-derived string across the whole manifest, adds a
# per-file `path_id` (sha256 of the relative path) as a correlation handle, and a top-level
# `trusted_only: true` marker. What remains is only what file-observer itself computed.
file-observer sample_docs --specialists --trusted-only --stdout > out/trusted-only.json

echo "Wrote out/normal.json and out/trusted-only.json."
echo
python3 -c "
import json
n = json.load(open('out/normal.json')); t = json.load(open('out/trusted-only.json'))
nf = n['files'][0];   tf = t['files'][0]
print('normal manifest:')
print('  path                :', repr(nf['path']))
print('  content_preview     :', 'present' if nf['content_preview'] else 'null')
print()
print('--trusted-only manifest:')
print('  trusted_only marker :', t.get('trusted_only'))
print('  path (file-derived) :', tf['path'], '(nulled)')
print('  path_id (fo-derived):', tf['path_id'][:16] + '…  (safe correlation handle)')
print('  content_preview     :', tf['content_preview'], '(nulled)')
print('  mime_type (fo-kept) :', tf['mime_type'])
print('  safety_flags (kept) :', tf['safety_flags'])
print('  summary (fo-derived):', t['summary'], '(prose dropped — it names authors/paths)')
print()
inj = 'ignore_previous_instructions'; who = 'Mallory Attacker'
print('injection filename present?   normal:', inj in json.dumps(n), ' trusted-only:', inj in json.dumps(t))
print('attacker author name present? normal:', who in json.dumps(n), ' trusted-only:', who in json.dumps(t))
"
