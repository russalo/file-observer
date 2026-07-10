"""file-observer MCP server — the agent-native front-door (v1.37, prototype).

Exposes fo's EXISTING manifest / summary / schema through the Model Context Protocol so an agent can
scan a file tree READ-ONLY and DETERMINISTICALLY — "look before you touch." fo never opens, executes,
or modifies a file, so it is safe to point at UNTRUSTED input. Observe-only: the tools return
observations, never verdicts — the agent interprets. A NEW SURFACE: the manifest returned is
byte-identical to ``scan()`` (no LOGIC/SCHEMA change).

Run:  ``file-observer-mcp``  (stdio) — or ``python -m file_observer.mcp_server``.
Optional ``--root <dir>`` restricts scans to a subtree (defense-in-depth; off by default).
Needs the ``mcp`` SDK: ``pip install "file-observer[mcp]"``.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    manifest_to_json,
    build_schema_document,
    schema_to_markdown,
)

_ROOT: Path | None = None  # optional --root allowlist (defense-in-depth)

mcp = FastMCP(
    name="file-observer",
    instructions=(
        "file-observer performs a deterministic, READ-ONLY observation pass over a file tree and returns a "
        "manifest of what is in it — content-detected MIME type, structure, metadata, and provenance — WITHOUT "
        "opening, executing, or modifying any file. Use it to see what is in an unknown or untrusted folder "
        "BEFORE you ingest or open it. It observes and reports; it does NOT classify, judge, or decide whether a "
        "file is safe — you interpret the observation. It is not a file watcher. Start with `scan_summary` for a "
        "context-friendly overview; use `scan_file` to drill into one file; `scan_directory` for the full manifest "
        "(guarded by file count); `describe_surface` for the complete output schema."
    ),
)


def _resolve_in_root(path: str) -> Path:
    """Resolve + (optionally) enforce the --root allowlist. fo's own resolve-containment (v1.8.1)
    still applies inside the scan; this is a coarse server-level gate on the scan ROOT."""
    rp = Path(path).expanduser().resolve()
    if _ROOT is not None and rp != _ROOT and _ROOT not in rp.parents:
        raise ValueError(f"path is outside the allowed root {_ROOT}: {path}")
    return rp


def _scan(source_dir: Path, specialists: bool):
    return Scanner(source_dir=source_dir, config=ScannerConfig(enable_specialists=specialists)).scan()


@mcp.tool()
def scan_summary(path: str, specialists: bool = False) -> str:
    """Context-friendly overview of a directory: file counts, text/binary split, and NOTABLE
    observations (chatlogs, MIME-vs-extension mismatches, polyglots, at-risk formats, safety flags
    like macros/JavaScript/geotagged, degraded/error files, duplicate clusters). Read-only,
    deterministic — never opens or runs a file. START HERE. `specialists` (default off) enables
    deeper per-format extraction; leave off for a fast overview."""
    d = _resolve_in_root(path)
    m = _scan(d, specialists)
    q = m.quality
    out = {
        "path": str(d),
        "scanner_version": SCANNER_VERSION,
        "summary": m.summary,
        "stats": asdict(m.stats),
        "notable": {
            "degraded_files": q.degraded_files,
            "error_files": q.error_files,
            "mime_mismatches": q.mime_mismatches,
            "polyglots_detected": q.polyglots_detected,
            "specialist_failures": q.specialist_failures,
            "chatlog_files": q.chatlog_files,
            "safety_flags": q.safety_flags,
            "duplicate_clusters": len(q.duplicate_clusters or []),
        },
    }
    return json.dumps(out, indent=2, ensure_ascii=False)


@mcp.tool()
def scan_file(path: str, specialists: bool = True) -> str:
    """The full observation record for ONE file: identity, content-detected MIME (+ whether it
    matches the extension), routing flags, safety flags, per-field signal provenance, and — with
    specialists — format-specific metadata. Read-only, deterministic. Use after `scan_summary`
    flags a specific file."""
    fp = _resolve_in_root(path)
    if not fp.is_file():
        raise ValueError(f"not a file (use scan_summary/scan_directory for a folder): {path}")
    # fo scans a directory; scan the parent and return this file's record.
    m = _scan(fp.parent, specialists)
    for r in m.files:
        if (fp.parent / r.path).resolve() == fp:
            return json.dumps(asdict(r), indent=2, ensure_ascii=False, default=str)
    raise ValueError(f"file not found in scan (excluded — e.g. a symlink out of tree?): {path}")


@mcp.tool()
def scan_directory(path: str, specialists: bool = False, max_files: int = 200) -> str:
    """The FULL manifest JSON for a directory — every FileRecord. GUARDED: if the tree has more than
    `max_files` files, returns the compact summary + a note instead (a full manifest would overflow
    the context) — narrow the path or raise max_files. Read-only, deterministic; the manifest is
    byte-identical to the `file-observer` CLI."""
    d = _resolve_in_root(path)
    m = _scan(d, specialists)
    n = m.stats.total_files
    if n > max_files:
        return json.dumps({
            "guarded": True,
            "reason": f"{n} files exceeds max_files={max_files}; a full manifest would overflow context",
            "hint": "narrow the path, or call again with a higher max_files",
            "summary": m.summary,
            "stats": asdict(m.stats),
        }, indent=2, ensure_ascii=False)
    return manifest_to_json(m)


@mcp.tool()
def describe_surface(format: str = "md") -> str:
    """The COMPLETE output surface fo can emit — every manifest field, specialist + its metadata
    fields, vector, safety flag, error code, provenance trigger, and preservation tier. The reference
    when writing a consumer or reasoning about the manifest shape. `format`: 'md' (default) or 'json'."""
    doc = build_schema_document()
    if format == "json":
        return json.dumps(doc, indent=2, ensure_ascii=False)
    return schema_to_markdown(doc)


def main() -> None:
    ap = argparse.ArgumentParser(prog="file-observer-mcp",
                                 description="file-observer MCP server (stdio) — read-only file observation for agents.")
    ap.add_argument("--root", metavar="DIR",
                    help="restrict all scans to this subtree (defense-in-depth; off by default).")
    args = ap.parse_args()
    global _ROOT
    if args.root:
        _ROOT = Path(args.root).expanduser().resolve()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
