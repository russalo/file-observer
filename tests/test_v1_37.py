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
mcp_server = pytest.importorskip("file_observer.mcp_server", reason="mcp SDK not installed ([mcp] extra)", exc_type=ImportError)

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

    def test_scan_directory_guard_fires_before_scanning(self):
        # the guard bounds WORK: it refuses BEFORE the expensive scan (leg-2/gem-pro DoS fix), so the
        # response is a note (reason/hint), not a scanned summary.
        g = json.loads(mcp_server.scan_directory(str(FIXTURES), max_files=2))
        assert g.get("guarded") is True and "reason" in g and "hint" in g

    def test_scan_summary_guard_fires_before_scanning(self):
        g = json.loads(mcp_server.scan_summary(str(FIXTURES), max_files=2))
        assert g.get("guarded") is True and "reason" in g

    def test_scan_file_observes_only_the_one_file(self, tmp_path):
        # scan_file must NOT scan siblings (leg-1/leg-2 converged) — a temp-dir isolation returns exactly
        # one record, with the caller's real path, and identical content to an in-place scan.
        (tmp_path / "target.txt").write_text("hello world")
        (tmp_path / "sibling_a.bin").write_bytes(b"\x00\x01\x02")
        (tmp_path / "sibling_b.md").write_text("# not requested")
        rec = json.loads(mcp_server.scan_file(str(tmp_path / "target.txt")))
        assert rec["path"] == str((tmp_path / "target.txt").resolve())
        assert rec["mime_type"].startswith("text/")
        # its checksum matches an in-place scan of the same bytes (content-identical)
        from file_observer.scanner import Scanner, ScannerConfig
        m = Scanner(source_dir=tmp_path, config=ScannerConfig()).scan()
        inplace = next(r for r in m.files if r.path == "target.txt")
        assert rec["checksum_sha256"] == inplace.checksum_sha256

    def test_scan_directory_is_checksum_identical_to_scan(self):
        # the FRONT-DOOR contract: the MCP manifest IS scan()'s manifest (byte-identical modulo the
        # volatile scan_id/generated_at — the standard determinism framing).
        via_mcp = json.loads(mcp_server.scan_directory(str(FIXTURES), max_files=100000))
        oracle = json.loads(manifest_to_json(Scanner(source_dir=FIXTURES, config=ScannerConfig()).scan()))
        assert via_mcp["manifest_checksum"] == oracle["manifest_checksum"]
        for m in (via_mcp, oracle):
            m["meta"]["scan_id"] = ""; m["meta"]["generated_at"] = ""
        assert via_mcp == oracle   # identical once the two volatile fields are neutralized

    def test_describe_surface_rejects_bad_format(self):
        with pytest.raises(ValueError):
            mcp_server.describe_surface("xml")

    def test_scan_summary_rejects_non_directory(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        with pytest.raises(ValueError):
            mcp_server.scan_summary(str(tmp_path / "a.txt"))   # a file, not a dir

    def test_scan_file_does_not_mutate_the_target(self, tmp_path):
        # leg-4/Codex P1: scan_file must be READ-ONLY on the target — a copy, not a hardlink (which would
        # bump the target's link-count/ctime). Assert the target's stat is unchanged across a scan_file call.
        import os as _os
        f = tmp_path / "t.txt"; f.write_text("payload")
        before = _os.stat(f)
        mcp_server.scan_file(str(f))
        after = _os.stat(f)
        assert before.st_nlink == after.st_nlink == 1   # no hardlink was created
        assert before.st_ctime == after.st_ctime         # ctime unchanged → not mutated

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
