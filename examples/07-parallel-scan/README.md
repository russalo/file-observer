# Example 07 — Parallel scan

**What it shows:** `--workers N` scans files across a process pool to go faster — and the manifest is **byte-identical regardless of N**. Parallelism is a performance knob, never a correctness one.

→ Tutorial section: [Going faster, and continuous mode](../../docs/TUTORIAL.md#9-going-faster-and-continuous-mode)

## The input

`sample_tree/` — a small nested tree (6 files across `docs/`, `data/`, and the root) so there's something for multiple workers to divide.

## Run it

```bash
./run.sh
```

It scans the same tree with `--workers 1` (serial) and `--workers 4` (process pool) and compares the two `manifest_checksum` values.

```bash
file-observer sample_tree --workers 1 -o out/w1
file-observer sample_tree --workers 4 -o out/w4
```

## What you get

Two worker counts, **one checksum**:

```
workers=1 manifest_checksum: 3c419f0fedecef447d51e86bac56c50944426133a65a5c8087c80392e78a5d83
workers=4 manifest_checksum: 3c419f0fedecef447d51e86bac56c50944426133a65a5c8087c80392e78a5d83
IDENTICAL — parallelism changed the speed, not the observation.
```

The `files[]` array is in the same order both times, too — not just the same set of records, the same sequence.

(As in [Example 04](../04-determinism/), the **equality across worker counts** is the invariant; the absolute digest is specific to this build's `ScanContext`, so your run may print a different — but matching — pair.)

## What just happened

- **Worker count is a runtime detail, deliberately excluded from the output.** Like `scan_id`, `--workers` has no causal link to *what the files are*, so it isn't recorded in `meta.config` and can't affect the checksum. The same input scanned with 1 worker or 8 produces the same bytes — [Example 04](../04-determinism/)'s contract, extended across processes.
- **It holds because the per-file scan is pure.** Each file's record is computed without touching shared scanner state; the corpus-level counters are derived from the finished records afterward, and the process pool preserves input order. So there's no race that could reorder `files[]` or perturb a count.
- **This is what makes parallelism safe to just turn on.** You don't trade reproducibility for speed. Cache keys, deltas, and signatures all keep working at `--workers 16` exactly as they did serial.
- **`--watch` is the same idea over time.** The tutorial's §9 continuous mode re-runs this same one-shot scan on filesystem events — each emit is byte-identical to a one-shot invocation at that filesystem state. Speed and triggering change; the observation never does.

Back to the [examples index](../) · the [tutorial](../../docs/TUTORIAL.md) · or [`docs/SCHEMA.md`](../../docs/SCHEMA.md) for the full surface.
