# Example 08 — MCP server (use File Observer from an AI agent)

`file-observer[mcp]` exposes File Observer as an **[MCP](https://modelcontextprotocol.io/) server** —
a read-only, deterministic tool an AI agent can call to see *what's in a file tree* before it opens or
ingests anything. A safe **"look before you touch"** pass over unknown or untrusted files: File Observer
never opens, executes, or modifies content, stays in-tree, and never crashes, so an agent can point it at
files it doesn't trust and get a manifest of what's there — not a verdict, an observation.

## Install + run

```bash
pip install "file-observer[mcp]"
file-observer-mcp                                   # stdio server
# or zero-install:  uvx --from "file-observer[mcp]" file-observer-mcp
```

## Wire it into an MCP client

Add to your client config (Claude Desktop's `claude_desktop_config.json`, or Claude Code's MCP config):

```json
{
  "mcpServers": {
    "file-observer": { "command": "file-observer-mcp", "args": [] }
  }
}
```

Server-startup flags (in `"args"`):

- `--root /path/you/allow` — lock scans to a subtree (defense-in-depth).
- `--lexicon terms.txt` (repeatable) / `--lexicon-index lists.txt` — apply a consumer content screen to
  every scan (see [example 10](../10-lexicon-screen/)). Configured **at startup, not as a tool arg**, so
  the private terms never enter the agent's context — only term-free counts cross the wire.
- `--trusted-only` — force safe mode for every call (see [example 09](../09-trusted-only/)).

## The four tools (progressive disclosure — built for an agent's context budget)

| tool | what it returns | when |
|---|---|---|
| `scan_summary(path, specialists=false)` | compact overview: file counts, text/binary split, and notable observations (chatlogs, MIME-vs-extension mismatches, polyglots, macros/JavaScript, geotagged, at-risk formats, degraded files, duplicate clusters) | **start here** — ~300 tokens even on a big folder |
| `scan_file(path, specialists=true)` | the full observation record for one file: identity, content-MIME, routing flags, safety flags, per-field provenance, format metadata | drill in after the summary flags something |
| `scan_directory(path, specialists=false, max_files=200)` | the full manifest (checksum-identical to a CLI scan, same specialists setting) — **guarded**: refused before scanning if the tree exceeds `max_files` (bounds context + work) | the escape hatch for a full dump |
| `describe_surface(format="md")` | the complete output schema — every field/specialist/vector/flag | the reference when writing a consumer |

Everything is read-only and deterministic (same bytes → same result). The tools **observe and report**;
the agent decides what to do with the observation.

Two per-call params on `scan_summary`/`scan_file`/`scan_directory` mirror the CLI safe surfaces:
`trusted_only=true` returns the safe-mode projection ([example 09](../09-trusted-only/)); `receipt=true`
returns the compact tamper-evident screening receipt (`receipt_id`/`path_id` per file). A per-call
`previous_manifest_path` runs a delta.

## Try it programmatically (no MCP client needed)

The tool functions are plain Python — you can call them directly to see the shapes:

```python
import json
from file_observer.mcp_server import scan_summary, scan_file, describe_surface

print(scan_summary("."))          # compact overview of the current tree
# → {path, scanner_version, summary, stats, notable{chatlogs, mime_mismatches, polyglots, safety_flags, ...}}
```

Run `./run.sh` (or `python demo.py`) here for a live overview of this examples directory.
