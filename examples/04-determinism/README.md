# Example 04 — Determinism

**What it shows:** scan the same bytes twice and you get the same `manifest_checksum`, every time. This is the property that makes file-observer safe to put in a pipeline — you can cache on it, diff against it, and trust it.

→ Tutorial section: [Determinism and deltas](../../docs/TUTORIAL.md#8-determinism-and-deltas-in-a-pipeline)

## The input

`sample_data/` — a tiny fixed folder (`orders.csv`, `notes.md`). The content never changes between the two runs.

## Run it

```bash
./run.sh
```

It scans `sample_data/` twice (into `out/run-a` and `out/run-b`) and compares the two `manifest_checksum` values.

## What you get

Two runs, two manifests, **one checksum**:

```
run A manifest_checksum: 2db7f239719fabc6f5d221f4a362806e61d28e1fa3a5dd1fb8a48d71018f3e6b
run B manifest_checksum: 2db7f239719fabc6f5d221f4a362806e61d28e1fa3a5dd1fb8a48d71018f3e6b
IDENTICAL — same bytes in, same observation out.
```

The **equality** is the invariant being shown; the absolute digest is specific to this build's `ScanContext` (scanner version, libmagic presence, …), so your run may print a different — but internally identical — pair.

…even though the two runs have different volatile metadata:

| field | run A | run B |
|---|---|---|
| `meta.scan_id` | `6e8e4f78-…` | `d0a7a7b5-…` |
| `meta.generated_at` | `2026-06-11T21:56:57…` | `2026-06-11T21:56:58…` |

## What just happened

- **The checksum is a SHA-256 over the whole manifest *minus* `scan_id` and `generated_at`.** Those two fields are genuinely volatile — a fresh UUID and a wall-clock timestamp each run — and they carry no information about the *files*. Excluding them is what lets the checksum mean "the observation is identical" rather than "the run is identical."
- **Determinism is a designed-in contract, not an accident.** The scanner version, the logic version, and the rules behind every derived field are all fingerprinted; identical inputs plus an identical `ScanContext` are guaranteed to produce an identical manifest. When the logic changes, the version moves — so a checksum change is always *explained*.
- **This is what "safe in a pipeline" means.** Cache a file's record keyed on its checksum and you never re-process unchanged input. Compare last run's checksum to this run's and a match means "nothing to do." [Example 05](../05-delta-scan/) builds the per-file version of that into the `delta` block; [Example 07](../07-parallel-scan/) shows the checksum holds even across parallel workers.

Next: [Example 05](../05-delta-scan/) — what changed between two scans. Or the [tutorial](../../docs/TUTORIAL.md#8-determinism-and-deltas-in-a-pipeline).
