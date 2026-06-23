# Example 06 — Schema discovery

**What it shows:** you don't have to read the source (or guess) to know what file-observer can emit. Ask the installed build directly with `--schema`, and it prints its complete output surface — then exits without scanning anything.

→ Tutorial section: [Discovering the full output surface](../../docs/TUTORIAL.md#7-discovering-the-full-output-surface)

## The input

**None.** This is the one example with no `sample_*/` folder — `--schema` introspects the *build*, not a directory. It's a separate surface from a scan.

## Run it

```bash
./run.sh
# or directly:
file-observer --schema                      # complete surface, JSON
file-observer --schema --schema-format md   # human-readable
```

## What you get

A description of everything the build can emit, introspected from the installed code so it's always accurate for *your* version (counts shown as `N` — run it for your build's actual numbers):

```
scanner <your build> / logic <…> / schema <…>
manifest:            N   (dataclasses: FileRecord, DeltaRecord, ErrorRecord, …)
specialists:          N   (pdf, image, video, document, spreadsheet, email, chatlog — + their fields)
vectors:              N   (chatlog, reference_tokens, provenance, …)
provenance_triggers: N   (every `trigger` a signal_provenance entry can carry)
error_codes:         N
safety_flags:         N   (has_javascript, has_macros, geotagged, …)
format_signatures:   N
```

The JSON form is for a consumer to load; the Markdown form is human-readable — it's literally what [`docs/SCHEMA.md`](../../docs/SCHEMA.md) is generated from:

```markdown
### `FileRecord`

| field | type |
|---|---|
| `path` | `str` |
| `mime_type` | `str` |
| `checksum_sha256` | `str` |
| …
```

## What just happened

- **The schema is code-derived, not hand-maintained.** `--schema` reflects over the actual dataclasses and registries in the running build — so it can never drift from what a scan really produces. (A committed `docs/SCHEMA.md` is the generated snapshot, and a test fails if it falls out of sync.)
- **It's a separate surface — the manifest is untouched.** `--schema` added zero bytes to what a scan emits; it's a read *about* the build, not a change *to* it. Same scanner version, byte-identical manifests.
- **This is the reference when you're writing a consumer.** Every manifest field, every specialist and its metadata fields, every vector, safety flag, error code, provenance trigger, format signature, and preservation tier — enumerated from one place. No reading `scanner.py` to find out what `xref_type` can be.
- **It closes the "self-evidencing but not self-describing" gap.** A manifest already proves *how* each field was derived (via `signal_provenance`); `--schema` lets a consumer learn what the build *could* emit before it ever runs a scan.

Next: [Example 07](../07-parallel-scan/) — scanning faster without changing the output. Or the [tutorial](../../docs/TUTORIAL.md#7-discovering-the-full-output-surface).
