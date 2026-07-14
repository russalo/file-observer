#!/usr/bin/env bash
# Example 10 — bring-your-own lexicon: screen untrusted files before an AI reads them.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf out && mkdir -p out

echo "Scanning sample_uploads/ with a consumer content screen (lexicon.txt)…"
file-observer sample_uploads --specialists --lexicon lexicon.txt --stdout \
  > out/manifest.json 2> out/load.log

echo
echo "--- load-time provenance (goes to STDERR; never the manifest) ---"
grep -i 'loaded lexicon' out/load.log || true

echo
echo "--- lexicon vector: per-category counts across the corpus ---"
python3 -c "import json;m=json.load(open('out/manifest.json', encoding='utf-8'));v=[x for x in m['vectors_collected'] if x['vector_id']=='lexicon'];print(json.dumps(v[0]['summary'],indent=2) if v else 'no lexicon vector')"

echo
echo "--- files a consumer would route to review (lexicon_match flag) ---"
python3 -c "import json;m=json.load(open('out/manifest.json', encoding='utf-8'));[print(' ',f['path'],'->',f.get('safety_flags')) for f in m['files'] if 'lexicon_match' in (f.get('safety_flags') or [])]"

echo
echo "--- proof: the lexicon's TERM LIST never enters the manifest ---"
python3 - <<'PY'
import json
m = json.load(open("out/manifest.json", encoding="utf-8"))
terms = ("banana", "cherry", "mango", "example-marker", "sample-flagword")
# The lexicon-DERIVED surface: the per-file lexicon_match namespace + the corpus lexicon vector.
lex_surface = json.dumps(
    [f.get("specialist_metadata", {}).get("lexicon_match") for f in m["files"]]
    + [v for v in m["vectors_collected"] if v["vector_id"] == "lexicon"]
)
leaked = [t for t in terms if t in lex_surface]
print("  lexicon-derived fields carry any term?  ", leaked or "NO — only counts/density/totals, category names, and a dictionary_id")
print("  NOTE: a term that ALSO appears in a document's body shows up in THAT file's")
print("        content_preview — as the document's own (untrusted) content, not as a lexicon term.")
print("        Strip those with --trusted-only before handing the manifest to a model (see example 09).")
PY
