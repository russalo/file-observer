# file-observer examples

Self-contained, runnable examples — one folder per concept. Each has its own
input files, a `run.sh`, and a README with the salient output excerpt + a link
to the matching [tutorial](../docs/TUTORIAL.md) section.

These are the canonical examples that the tutorial and external posts link to.
They're decoupled from the test suite (their own inputs) so the links and
excerpts stay stable across releases.

| # | Example | Shows |
|---|---|---|
| 01 | [First scan](01-first-scan/) | Point at a folder → one deterministic manifest |
| 02 | [PDF metadata](02-pdf-metadata/) | Specialist extraction: page_count, producer, provenance |
| 03 | [Chatlog detection](03-chatlog-detection/) | Content-detected conversational structure (not extension-driven) |
| 04 | [Determinism](04-determinism/) | Same input → identical `manifest_checksum` (the pipeline property) |
| 05 | [Delta scan](05-delta-scan/) | What changed between two scans (added / modified / removed) |
| 06 | [Schema discovery](06-schema-discovery/) | `--schema` — the complete output surface, no guessing |
| 07 | [Parallel scan](07-parallel-scan/) | `--workers N` — faster, byte-identical output |
| 08 | [MCP server](08-mcp-server/) | `file-observer-mcp` — the read-only tools an agent calls (`scan_summary`, …) |
| 09 | [Safe mode](09-trusted-only/) | `--trusted-only` — a projection safe to hand to a model (nulls attacker-controllable strings) |
| 10 | [Lexicon screen](10-lexicon-screen/) | `--lexicon` — screen untrusted files for consumer-defined terms before an AI reads them |
| 11 | [Tiered routing](11-tiered-routing/) | route each file block / review / pass on `safety_flags` + lexicon category, over the `--receipt` |

## Running an example

```bash
cd 01-first-scan
./run.sh          # writes the full manifest + report to ./out/
```

Each `run.sh` is self-contained. The committed README shows a curated excerpt of
the salient fields (stable across versions); `run.sh` produces the full live
manifest (which carries the current `scanner_version`).

## A note on output committed here

We commit **inputs + commands + a salient excerpt**, never full manifests.
A full manifest carries `scanner_version` and a `manifest_checksum` that change
each release — committing them would rot. The excerpts show the fields each
example is *about*; `run.sh` is the source of truth for the whole.

Requires `file-observer` installed (`pip install file-observer`; some examples
use the `[pdf]` extra). See the [tutorial](../docs/TUTORIAL.md#2-install).
