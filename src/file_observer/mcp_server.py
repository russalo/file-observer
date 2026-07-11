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
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as _e:   # a friendly message instead of a bare traceback (leg-4/gemini);
    # still an ImportError so `pytest.importorskip` skips cleanly when the [mcp] extra isn't installed.
    raise ImportError(
        'file-observer-mcp needs the MCP SDK — install it with:  pip install "file-observer[mcp]"'
    ) from _e

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    manifest_to_json,
    build_schema_document,
    schema_to_markdown,
    parse_lexicon,
)

_ROOT: Path | None = None  # optional --root allowlist (defense-in-depth)
# v1.39: optional bring-your-own-lexicon, configured at SERVER STARTUP (`--lexicon <path>`), NOT a
# per-call tool arg. A tool argument is constructed by the calling LLM, so a terms-inline param would
# put the (consumer-private) terms straight into the agent's context — backwards. The startup flag keeps
# the terms in a config file the agent never sees; only the term-free results (counts + category names +
# dictionary_id) ever cross the wire. Parsed/validated once in main().
_LEXICON: dict | None = None

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


def _scan(source_dir: Path, specialists: bool, previous_manifest: str | None = None):
    # v1.39: thread the startup lexicon + an optional previous-manifest (delta) into the EXISTING config.
    # The returned manifest is byte-identical to a CLI scan with the same settings (front-door contract).
    return Scanner(source_dir=source_dir, config=ScannerConfig(
        enable_specialists=specialists, lexicon=_LEXICON, previous_manifest=previous_manifest)).scan()


def _resolve_previous_manifest(previous_manifest_path: str | None) -> str | None:
    """v1.39: validate an optional prior-manifest path for a delta scan. A path (not sensitive), NOT
    --root-restricted (it's a read-only manifest input the agent names, not a scan tree). Must exist +
    be a file; a non-manifest file degrades gracefully inside fo's delta code (never crashes)."""
    if previous_manifest_path is None:
        return None
    p = Path(previous_manifest_path).expanduser().resolve()
    if not p.is_file():
        raise ValueError(f"previous_manifest_path is not a file: {previous_manifest_path}")
    return str(p)


def _lexicon_notable(m) -> dict | None:
    """v1.39: the per-category lexicon summary for scan_summary's `notable` (so the agent sees WHICH
    categories hit, not just the aggregate `lexicon_match` safety_flag). Term-free — from the vector
    summary (counts + category names + lexicon_id). None when no lexicon is configured."""
    if _LEXICON is None:
        return None
    for v in m.vectors_collected:
        if v.get("vector_id") == "lexicon":
            return v.get("summary")
    return None


def _count_files_bounded(d: Path, cap: int) -> int:
    """Cheap file count (NO scanning) up to cap+1 — bounds the WORK before a full scan, so pointing a
    tool at a huge tree (e.g. `/`) is refused BEFORE fo reads/hashes every file (leg-2/gem-pro DoS fix).
    Returns the exact count if <= cap, else a value > cap (the exact overflow is irrelevant)."""
    n = 0
    for _root, _dirs, files in os.walk(d, followlinks=False):
        n += len(files)
        if n > cap:
            return n
    return n


@mcp.tool()
def scan_summary(path: str, specialists: bool = False, max_files: int = 1000,
                 previous_manifest_path: str | None = None) -> str:
    """Context-friendly overview of a directory: file counts, text/binary split, and NOTABLE
    observations (chatlogs, MIME-vs-extension mismatches, polyglots, at-risk formats, safety flags
    like macros/JavaScript/geotagged, degraded/error files, duplicate clusters). Read-only,
    deterministic — never opens or runs a file. START HERE. `specialists` (default off) enables
    deeper per-format extraction; leave off for a fast overview. GUARDED by `max_files`: a tree
    larger than that is refused before scanning (narrow the path) so it can't run away on a huge tree.
    `previous_manifest_path` (optional): a path to a manifest saved from a prior scan — the response
    then carries a `delta` (added/modified/removed/unchanged counts). If the server was started with
    `--lexicon`, a `lexicon` block (per-category term counts) is included — an observation, never a verdict."""
    d = _resolve_in_root(path)
    if not d.is_dir():
        raise ValueError(f"not a directory (use scan_file for a single file): {path}")
    prev = _resolve_previous_manifest(previous_manifest_path)
    n = _count_files_bounded(d, max_files)
    if n > max_files:
        return json.dumps({
            "guarded": True,
            "reason": f"more than {max_files} files under {d}; refused before scanning to bound work",
            "hint": "narrow the path, or call again with a higher max_files",
        }, indent=2, ensure_ascii=False)
    m = _scan(d, specialists, previous_manifest=prev)
    q = m.quality
    notable = {
        "degraded_files": q.degraded_files,
        "error_files": q.error_files,
        "mime_mismatches": q.mime_mismatches,
        "polyglots_detected": q.polyglots_detected,
        "specialist_failures": q.specialist_failures,
        "chatlog_files": q.chatlog_files,
        "safety_flags": q.safety_flags,
        "duplicate_clusters": len(q.duplicate_clusters or []),
    }
    lex = _lexicon_notable(m)
    if lex is not None:
        notable["lexicon"] = lex
    if m.delta is not None:
        notable["delta"] = {k: len(getattr(m.delta, k)) for k in
                            ("added", "modified", "removed", "unchanged", "rescan_candidates")}
    return json.dumps({
        "path": str(d),
        "scanner_version": SCANNER_VERSION,
        "summary": m.summary,
        "stats": asdict(m.stats),
        "notable": notable,
    }, indent=2, ensure_ascii=False, default=str)


@mcp.tool()
def scan_file(path: str, specialists: bool = True) -> str:
    """The full observation record for ONE file: identity, content-detected MIME (+ whether it
    matches the extension), routing flags, safety flags, per-field signal provenance, and — with
    specialists — format-specific metadata. Read-only, deterministic. Use after `scan_summary`
    flags a specific file."""
    fp = _resolve_in_root(path)
    if not fp.is_file():
        raise ValueError(f"not a file (use scan_summary/scan_directory for a folder): {path}")
    # fo scans a DIRECTORY, so to observe ONLY this file (not its siblings — leg-1/leg-2 fix) scan a
    # temp dir containing a COPY of it. A COPY (not a hardlink): `os.link` would bump the target inode's
    # link-count + ctime, MUTATING a file fo promises never to touch (leg-4/Codex P1). `copy2` only READS
    # the target (same footprint as a normal scan) → read-only preserved. Report the caller's real path.
    # NOTE: the isolated scan can't see the target's DIRECTORY CONTEXT, so a context-dependent field
    # (`sidecar_exists`, `asset_matches`) reflects the isolated copy, not the original's neighbourhood.
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / fp.name
        shutil.copy2(fp, copy)
        m = _scan(Path(td), specialists)
        for r in m.files:
            if r.path == fp.name:
                d = asdict(r)
                d["path"] = str(fp)   # the caller's real path, not the temp basename
                return json.dumps(d, indent=2, ensure_ascii=False, default=str)
    raise ValueError(f"could not observe file (unreadable / excluded): {path}")


@mcp.tool()
def scan_directory(path: str, specialists: bool = False, max_files: int = 200,
                   previous_manifest_path: str | None = None) -> str:
    """The FULL manifest JSON for a directory — every FileRecord. GUARDED: if the tree has more than
    `max_files` files it is refused BEFORE scanning (returns a note) — both to avoid overflowing the
    context AND to bound the work (a huge tree isn't read/hashed) — narrow the path or raise max_files.
    Read-only, deterministic; the manifest is checksum-identical to a CLI scan run with the same
    `specialists` setting (default: off, matching the CLI default). `previous_manifest_path` (optional):
    a path to a manifest saved from a prior scan — the manifest's `delta` block is then populated
    (added/modified/removed/unchanged/rescan_candidates). If the server was started with `--lexicon`,
    each text file carries `specialist_metadata.lexicon_match` (per-category counts; observation, not verdict)."""
    d = _resolve_in_root(path)
    if not d.is_dir():
        raise ValueError(f"not a directory (use scan_file for a single file): {path}")
    prev = _resolve_previous_manifest(previous_manifest_path)
    n = _count_files_bounded(d, max_files)   # bound WORK: refuse before the expensive scan (leg-2/gem-pro DoS fix)
    if n > max_files:
        return json.dumps({
            "guarded": True,
            "reason": f"more than {max_files} files under {d}; a full manifest would overflow context",
            "hint": "narrow the path, call scan_summary for an overview, or raise max_files",
        }, indent=2, ensure_ascii=False)
    return manifest_to_json(_scan(d, specialists, previous_manifest=prev))


@mcp.tool()
def describe_surface(format: str = "md") -> str:
    """The COMPLETE output surface fo can emit — every manifest field, specialist + its metadata
    fields, vector, safety flag, error code, provenance trigger, and preservation tier. The reference
    when writing a consumer or reasoning about the manifest shape. `format`: 'md' (default) or 'json'."""
    if format not in ("md", "json"):
        raise ValueError(f"invalid format {format!r}: expected 'md' or 'json'")
    doc = build_schema_document()
    if format == "json":
        return json.dumps(doc, indent=2, ensure_ascii=False)
    return schema_to_markdown(doc)


def main() -> None:
    ap = argparse.ArgumentParser(prog="file-observer-mcp",
                                 description="file-observer MCP server (stdio) — read-only file observation for agents.")
    ap.add_argument("--root", metavar="DIR",
                    help="restrict all scans to this subtree (defense-in-depth; off by default).")
    ap.add_argument("--lexicon", metavar="PATH",
                    help="apply a consumer-supplied JSON lexicon {lexicon_id, categories:{cat:[terms]}} to "
                         "every scan — per-category term counts + a lexicon_match flag (v1.38 guardrail "
                         "pre-screen). Configured HERE at startup (not a tool arg) so the private terms "
                         "never enter an agent's context; only term-free counts cross the wire. Off by default.")
    args = ap.parse_args()
    global _ROOT, _LEXICON
    if args.root:
        root = Path(args.root).expanduser().resolve()
        if not root.is_dir():   # fail fast at startup, not on every later tool call (leg-4/gemini)
            ap.error(f"--root is not a directory: {args.root}")
        _ROOT = root
    if args.lexicon:
        try:   # parse + validate ONCE at startup — a bad lexicon fails fast, not on every tool call
            _LEXICON = parse_lexicon(json.loads(Path(args.lexicon).read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            ap.error(f"--lexicon could not be loaded: {exc}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
