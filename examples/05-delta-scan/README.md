# Example 05 — Delta scan

**What it shows:** give file-observer the previous manifest and it tells you exactly what changed — added, modified, removed, unchanged — so a pipeline re-processes only the delta, not the whole tree.

→ Tutorial section: [Determinism and deltas](../../docs/TUTORIAL.md#8-determinism-and-deltas-in-a-pipeline)

## The input

`sample_repo/` — the committed baseline (`app.py`, `config.yaml`, `README.md`). `run.sh` copies it to `out/work`, scans it, then changes the copy:

- **modifies** `app.py` (appends a function)
- **adds** `.env.example`
- **removes** `config.yaml`
- leaves `README.md` untouched

## Run it

```bash
./run.sh
```

It scans the baseline (→ `out/prev`), mutates the working copy, then rescans with `--previous-manifest` (→ `out/now`).

```bash
# the load-bearing flag:
file-observer out/work --previous-manifest out/prev/manifest_*.json -o out/now
```

## What you get

The `delta` block in the second manifest:

```json
{
  "previous_manifest_checksum": "23e0f8547a72e000dc422fb266db57ff563baee86a0fd946174e9949a1978b70",
  "added":     [".env.example"],
  "modified":  ["app.py"],
  "removed":   ["config.yaml"],
  "unchanged": ["README.md"],
  "rescan_candidates": []
}
```

## What just happened

- **The delta is computed from content checksums, not timestamps.** A file lands in `modified` because its `checksum_sha256` changed, and in `unchanged` because it didn't — so a touched-but-identical file (re-saved, re-copied, `mtime` bumped) correctly stays `unchanged`. No false churn.
- **`previous_manifest_checksum` anchors the comparison.** The delta records which manifest it was diffed against, so the chain is auditable: you can prove this scan was compared to that exact prior state.
- **This is the per-file form of [Example 04](../04-determinism/).** Determinism makes the whole-manifest checksum trustworthy; the delta block applies the same content-identity logic file-by-file. A pipeline reads `added` + `modified` and ignores the rest — incremental processing for free.
- **`rescan_candidates` flags files worth a deeper look** (e.g. a previously bounded/partial read) even when their bytes didn't change — empty here, populated when the scan couldn't fully observe a file the first time.

Next: [Example 07](../07-parallel-scan/) — the delta and checksum hold even across parallel workers. Or the [tutorial](../../docs/TUTORIAL.md#8-determinism-and-deltas-in-a-pipeline).
