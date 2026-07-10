"""v1.37 — MCP server (agent-native front-door). Falsify-first.

A new `file-observer-mcp` stdio entry point + `[mcp]` extra exposes fo's EXISTING manifest/summary/schema
through the Model Context Protocol — read-only, deterministic, 4 tools with progressive disclosure. A NEW
SURFACE: the manifest returned is checksum-identical to `scan()` → LOGIC + SCHEMA UNCHANGED.

Contracts:
  - the 4 tools return the expected shapes; `scan_summary` is compact (context-friendly);
  - `scan_directory` is checksum-identical to `scan()` (the front-door contract) + its size guard fires;
  - `--root` refuses a scan outside the allowlist;
  - LOGIC/SCHEMA unchanged (a new surface, not a manifest change).

Version axes: SCANNER 1.36.0→1.37.0 · LOGIC unchanged (1.20.0) · SCHEMA unchanged (1.21).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_observer.scanner import (
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
    Scanner, ScannerConfig, manifest_to_json,
)

# the MCP server needs the optional `mcp` SDK ([mcp] extra) — skip when absent.
mcp_server = pytest.importorskip("file_observer.mcp_server", reason="mcp SDK not installed ([mcp] extra)")

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


class TestTools:
    def test_scan_summary_is_compact_and_structured(self):
        s = mcp_server.scan_summary(str(FIXTURES))
        d = json.loads(s)  # valid JSON
        assert set(d) >= {"path", "scanner_version", "summary", "stats", "notable"}
        assert d["scanner_version"] == SCANNER_VERSION
        assert isinstance(d["summary"], str) and d["summary"]
        # context-friendly: a full-fixtures overview must stay small (the progressive-disclosure point)
        assert len(s) < 8000, f"scan_summary too big for context: {len(s)} chars"

    def test_scan_file_returns_one_record(self):
        f = next(FIXTURES.glob("*.pdf"), None) or next(FIXTURES.glob("*.md"))
        rec = json.loads(mcp_server.scan_file(str(f)))
        assert rec["path"].endswith(f.name)
        assert "mime_type" in rec and "is_binary" in rec

    def test_scan_file_rejects_a_directory(self):
        with pytest.raises(ValueError):
            mcp_server.scan_file(str(FIXTURES))

    def test_scan_directory_guard_fires(self):
        g = json.loads(mcp_server.scan_directory(str(FIXTURES), max_files=2))
        assert g.get("guarded") is True and "summary" in g

    def test_scan_directory_is_checksum_identical_to_scan(self):
        # the FRONT-DOOR contract: the MCP manifest IS scan()'s manifest (byte-identical modulo the
        # volatile scan_id/generated_at — the standard determinism framing).
        via_mcp = json.loads(mcp_server.scan_directory(str(FIXTURES), max_files=100000))
        oracle = json.loads(manifest_to_json(Scanner(source_dir=FIXTURES, config=ScannerConfig()).scan()))
        assert via_mcp["manifest_checksum"] == oracle["manifest_checksum"]
        for m in (via_mcp, oracle):
            m["meta"]["scan_id"] = ""; m["meta"]["generated_at"] = ""
        assert via_mcp == oracle   # identical once the two volatile fields are neutralized

    def test_describe_surface(self):
        md = mcp_server.describe_surface("md")
        assert md.startswith("# File Observer output schema")
        js = json.loads(mcp_server.describe_surface("json"))
        assert "manifest" in js and "specialists" in js


class TestSafety:
    def test_root_allowlist_refuses_outside(self, tmp_path, monkeypatch):
        # --root restricts scans to a subtree; an outside path is refused (defense-in-depth)
        inside = tmp_path / "ok"; inside.mkdir()
        (inside / "a.txt").write_text("hi")
        monkeypatch.setattr(mcp_server, "_ROOT", tmp_path.resolve())
        # inside the root → fine
        json.loads(mcp_server.scan_summary(str(inside)))
        # outside the root → refused
        with pytest.raises(ValueError):
            mcp_server.scan_summary("/etc")


class TestVersioning:
    def test_new_surface_no_contract_change(self):
        def _v(s): return tuple(int(p) for p in s.split("."))
        assert _v(SCANNER_VERSION) >= (1, 37, 0)
        assert _v(LOGIC_VERSION) >= (1, 20, 0)   # UNCHANGED — a new surface, not a manifest change
        assert _v(SCHEMA_VERSION) >= (1, 21)      # UNCHANGED
