"""v1.46.3 (patch) — MCP hardening from bestiary's consumer-seat shakedown.

#161: scan_file nulls `sidecar_exists` — it checks the file's NEIGHBOURHOOD, which the isolated
      single-file copy doesn't have, so it was a misleading False. asset_matches is content-derived
      and unaffected. The manifest (scan_directory) is UNCHANGED.
#162: the pre-scan work guard's `max_files` is clamped to a server ceiling (LLM-constructed args must
      not defeat the guard); the floor also fixes a negative "more than -1 files" message.

MCP-surface only → the manifest is unchanged → LOGIC/SCHEMA frozen (the v1.38.1 precedent).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from file_observer.scanner import LOGIC_VERSION, SCANNER_VERSION, SCHEMA_VERSION

mcp_server = pytest.importorskip("file_observer.mcp_server", reason="mcp SDK not installed ([mcp] extra)")


def _fn(tool):
    return getattr(tool, "fn", tool)   # unwrap the FastMCP tool to the raw function


# --- #161: scan_file observes sidecar_exists on the ORIGINAL (not the isolated copy) --------------
def test_scan_file_observes_sidecar_on_original(tmp_path: Path):
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0stub\n")
    (tmp_path / "photo.jpg.json").write_bytes(b'{"sidecar": true}\n')   # a real sidecar in the neighbourhood
    rec = json.loads(_fn(mcp_server.scan_file)(str(tmp_path / "photo.jpg"), specialists=False))
    # the isolated copy has no neighbour, but we re-observe the sidecar on the original path → correct True
    assert rec["sidecar_exists"] is True, "scan_file must observe the real sidecar (was a silent False)"
    assert isinstance(rec.get("asset_matches"), list), "asset_matches is content-derived → still present"


def test_scan_file_sidecar_false_when_absent(tmp_path: Path):
    (tmp_path / "lonely.jpg").write_bytes(b"\xff\xd8\xff\xe0stub\n")   # no sidecar beside it
    rec = json.loads(_fn(mcp_server.scan_file)(str(tmp_path / "lonely.jpg"), specialists=False))
    assert rec["sidecar_exists"] is False   # correctly False (a real observation, not the copy artifact)


def test_scan_directory_sidecar_unaffected(tmp_path: Path):
    # the MANIFEST contract is unchanged — scan_directory still observes the sidecar correctly
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0stub\n")
    (tmp_path / "photo.jpg.json").write_bytes(b'{"sidecar": true}\n')
    man = json.loads(_fn(mcp_server.scan_directory)(str(tmp_path), specialists=False, max_files=200))
    jpg = next(f for f in man["files"] if f["path"] == "photo.jpg")
    assert jpg["sidecar_exists"] is True


# --- #162: max_files clamp -----------------------------------------------------------------------
def test_clamp_bounds_and_floor():
    assert mcp_server._clamp_max_files(10_000_000) == mcp_server.SERVER_MAX_FILES   # over-set → ceiling
    assert mcp_server._clamp_max_files(-1) == 1                                     # negative → floor 1
    assert mcp_server._clamp_max_files(0) == 1
    assert mcp_server._clamp_max_files(50) == 50                                    # in-range → unchanged
    assert mcp_server.SERVER_MAX_FILES >= 1000                                      # generous but finite


def test_guard_uses_clamped_max_files(tmp_path: Path):
    # a small tree with a huge caller max_files: the clamp is applied, the scan still runs normally
    # (the DoS lever — an unbounded walk+hash on a huge tree — is removed because the guard now caps at
    # SERVER_MAX_FILES, not the caller's arbitrary value).
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x\n", encoding="utf-8")
    man = json.loads(_fn(mcp_server.scan_directory)(str(tmp_path), specialists=False, max_files=10_000_000))
    assert "files" in man and len(man["files"]) == 5   # normal small scan unaffected by the clamp


def test_version_axes():
    assert SCANNER_VERSION == "1.46.3"
    assert LOGIC_VERSION == "1.24.2"   # MCP-surface patch — manifest logic unchanged
    assert SCHEMA_VERSION == "1.23"
