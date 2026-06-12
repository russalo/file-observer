# file-observer tutorial

A guided tour, from first scan to pipeline integration. Every section links to a
runnable [example](../examples/). Stable section anchors — external posts link
here, so the headings don't churn.

> **New to the project?** file-observer is a **deterministic observation layer**:
> point it at files, get back a JSON manifest of what they are and what's in them.
> Think the `file` command + Apache Tika's metadata + cryptographic provenance,
> built to be *reproducible* so it's safe in a pipeline. It is **not** a file
> watcher, an ingester, an OCR engine, or a classifier — it observes and reports;
> you decide what to do with the observation.

## 1. What it is (and is not)

**Is:** a one-shot, read-only scan of a directory that emits a deterministic JSON
manifest. Identical bytes in → identical manifest out (modulo a scan id and
timestamp, which are excluded from the checksum). Every derived field records
*how* it was derived. Specialists pull structured metadata per format. Vectors
aggregate signals across the corpus.

**Is not:** it never executes file content, modifies your files, opens network
connections, or runs embedded scripts/macros. Its whole job is to *look* and
*describe*. The `--watch` mode (§9) re-runs the same one-shot scan on filesystem
events — it's a trigger loop around the deterministic observer, not an
intelligent watcher.

Why determinism matters: in an ingestion pipeline you want the same file to
produce the same record every run, so you can cache, diff, and trust the output.
The `manifest_checksum` is the handle for that (§4, [Example 04](../examples/04-determinism/)).

## 2. Install

```bash
pip install file-observer
```

Optional extras for richer extraction:

```bash
pip install "file-observer[pdf]"      # object-stream + encrypted PDF metadata (pypdf + cryptography)
pip install "file-observer[msg]"      # OLE2 .msg/.doc/.xls (olefile)
pip install "file-observer[watch]"    # --watch FS-event mode (watchfiles)
pip install "file-observer[pdf,msg,watch]"  # everything
```

The CLI is `file-observer` (or the shorthand `fo`).

## 3. Your first scan

→ [Example 01](../examples/01-first-scan/)

```bash
file-observer path/to/folder -o out
```

You get `out/manifest_v{VERSION}_{timestamp}.json` (the structured record) and a
`report_….md` (a human summary). One `FileRecord` per discovered file: identity,
filesystem metadata, checksum, content-detected MIME, routing flags, and — when
enabled — specialist metadata.

MIME is detected from **content**, not the extension: rename `logo.png` to
`logo.txt` and file-observer still reports `image/png`.

## 4. Reading a FileRecord

→ [Example 01](../examples/01-first-scan/), [Example 02](../examples/02-pdf-metadata/)

The fields that matter most in a pipeline:

- `checksum_sha256` — content identity; dedup and change-detection key.
- `mime_type` + `mime_analysis` — detected MIME, and whether it matches the extension.
- `is_binary`, `requires_specialist_tool`, `requires_vision` — derived routing flags.
- `signal_provenance` — per-derived-field record of *how* it was derived (`layer`,
  `method`, `trigger`). Nothing derived is unexplained.
- `safety_flags` — structural indicators (`has_javascript`, `has_macros`, …) —
  observations, never threat verdicts.

`manifest_checksum` (top level) is the SHA-256 over the whole manifest minus the
volatile `scan_id`/`generated_at`. It is the determinism contract.

## 5. Specialists — per-format extraction

→ [Example 02](../examples/02-pdf-metadata/)

By default file-observer stays at the universal/baseline tiers (fast, no format
parsing). Add `--specialists` to pull structured metadata per format:

```bash
file-observer path/to/folder --specialists -o out
```

PDF yields `page_count`, `producer`, `xref_type`, encryption state, …; images
yield dimensions; Office formats yield author/title/application; emails yield
the envelope. Specialists observe within declared byte bounds — `null` means
"not seen within bounds," not "absent."

## 6. Chatlog detection

→ [Example 03](../examples/03-chatlog-detection/)

file-observer detects conversational structure by **content**, not extension. A
`.md` or `.txt` or `.jsonl` whose content reads as a dialogue (speaker turns,
or role/content JSON across ConvoKit / ShareGPT / oasst / hh-rlhf schemas) gets
`is_chatlog: true` and a `chatlog` vector with turn counts, speakers, and shape
signals. This runs even with specialists disabled.

## 7. Discovering the full output surface

→ [Example 06](../examples/06-schema-discovery/)

You don't have to guess what file-observer can emit. Ask it:

```bash
file-observer --schema                      # complete surface, JSON
file-observer --schema --schema-format md   # human-readable
```

It prints every manifest field, every specialist + its metadata fields, every
vector, safety_flag, error code, provenance trigger, format signature, and
preservation tier — introspected from the installed build, so it's always
accurate. This is the reference when you're writing a consumer.

## 8. Determinism and deltas in a pipeline

→ [Example 04](../examples/04-determinism/), [Example 05](../examples/05-delta-scan/)

- **Determinism:** scan the same bytes twice → identical `manifest_checksum`.
  Cache on it; trust it.
- **Deltas:** pass `--previous-manifest prev.json` and the manifest gains a
  `delta` block — `added` / `modified` / `removed` / `unchanged` /
  `rescan_candidates` — so a pipeline only re-processes what changed.

## 9. Going faster, and continuous mode

→ [Example 07](../examples/07-parallel-scan/)

- **Parallel:** `--workers N` scans files across a process pool. The output is
  **byte-identical regardless of N** — parallelism changes speed, never the
  observation.
- **Continuous:** `--watch` re-runs the scan on filesystem events and emits each
  scan's delta as one JSONL line on stdout. Each emitted scan is byte-identical
  to a one-shot invocation at that filesystem state. Pipe it into a consumer for
  near-real-time observation. (Requires the `[watch]` extra.)

## Where to go next

- The [examples](../examples/) — runnable, one per concept.
- [`docs/SCHEMA.md`](SCHEMA.md) — the complete output surface (generated by `--schema`).
- [`docs/PUBLIC_CONTRACT.md`](PUBLIC_CONTRACT.md) — what's stable to build against.
- [`docs/LIMITATIONS.md`](LIMITATIONS.md) — what file-observer deliberately doesn't do.
