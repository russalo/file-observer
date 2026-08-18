"""v1.42 — screening receipt + bridge id (`--receipt`, #133 Phase 3).

Falsify-first. The receipt is a projection of the built manifest + a per-file tamper-evident
`receipt_id` (the observation↔decision bridge). Core falsifications: the id VERIFIES (recomputable),
it's TAMPER-EVIDENT (content/scan change → id change), the length-prefixed preimage is COLLISION-safe,
and the receipt is SAFE (no raw path). Plus: default manifest byte-identical (front-door), CLI, MCP.
"""
from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from file_observer.scanner import (
    RECEIPT_DOC_VERSION,
    Scanner,
    ScannerConfig,
    _receipt_id,
    compute_manifest_checksum,
    manifest_to_receipt,
)

LEX = {"lexicon_id": "t", "categories": {"fruit": ["banana", "cherry"]}}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "alpha.md").write_text("first file, some prose\n", encoding="utf-8")
    (tmp_path / "beta.txt").write_text("second file, other prose\n", encoding="utf-8")
    return tmp_path


def _receipt(tree: Path, *, lexicon=None, workers: int = 1):
    m = Scanner(tree, ScannerConfig(enable_specialists=True, lexicon=lexicon, workers=workers)).scan()
    return m, json.loads(manifest_to_receipt(m))


# --- 1. verifiability: the id recomputes from (manifest_checksum + path + hash) ---------
def test_receipt_id_verifies(tree: Path):
    m, r = _receipt(tree)
    assert r["receipt_doc_version"] == RECEIPT_DOC_VERSION
    assert len(r["receipts"]) == 2
    by_id = {rec["receipt_id"] for rec in r["receipts"]}
    for f in m.files:
        expect = _receipt_id(m.manifest_checksum, f.path, f.checksum_sha256)
        assert expect in by_id, "emitted receipt_id must equal the recomputed id (verifiable)"


# --- 2. tamper-evidence: content change → id change ------------------------------------
def test_tamper_evident(tree: Path):
    _, r1 = _receipt(tree)
    (tree / "alpha.md").write_text("first file, MUTATED content\n", encoding="utf-8")
    _, r2 = _receipt(tree)
    ids1 = {rec["path_id"]: rec["receipt_id"] for rec in r1["receipts"]}
    ids2 = {rec["path_id"]: rec["receipt_id"] for rec in r2["receipts"]}
    # alpha.md's receipt_id must have changed; beta.txt's path_id is stable but its receipt_id
    # also moves because manifest_checksum moved (the whole scan changed) — both are fine.
    changed = [pid for pid in ids1 if ids1[pid] != ids2.get(pid)]
    assert changed, "a content change must change at least the mutated file's receipt_id"


# --- 3. collision safety of the length-prefixed preimage ------------------------------
def test_receipt_id_no_collision():
    mc = "0" * 64
    # without length-prefixing, ("ab","c") and ("a","bc") would share the preimage "abc"
    assert _receipt_id(mc, "ab", "c") != _receipt_id(mc, "a", "bc")
    # and it matches an explicit length-prefixed recompute
    a, b, c = mc, "sub/dir/file.md", "d" * 64
    preimage = f"{len(a)}:{a}{len(b)}:{b}{len(c)}:{c}"
    assert _receipt_id(a, b, c) == sha256(preimage.encode()).hexdigest()


# --- 4. safe by construction: no raw path / file-derived string in a receipt ----------
def test_receipt_no_raw_path(tmp_path: Path):
    (tmp_path / "Zinjsecret_filename.md").write_text("body\n", encoding="utf-8")
    m, r = _receipt(tmp_path)
    txt = json.dumps(r)
    assert "Zinjsecret_filename" not in txt, "raw path/filename must not appear in a receipt"
    for rec in r["receipts"]:
        assert "path" not in rec and isinstance(rec["path_id"], str) and len(rec["path_id"]) == 64


# --- 5. determinism across workers ----------------------------------------------------
def test_receipt_deterministic_across_workers(tree: Path):
    _, r1 = _receipt(tree, workers=1)
    _, r2 = _receipt(tree, workers=2)
    assert {x["receipt_id"] for x in r1["receipts"]} == {x["receipt_id"] for x in r2["receipts"]}


# --- 6. the receipt captures the screening RESULT (lexicon) ---------------------------
def test_receipt_carries_lexicon_result(tmp_path: Path):
    (tmp_path / "banana_note.md").write_text("no lexicon terms in the body here\n", encoding="utf-8")
    m, r = _receipt(tmp_path, lexicon=LEX)
    rec = r["receipts"][0]
    assert "lexicon" in rec
    assert rec["lexicon"]["metadata_hits"] >= 1        # 'banana' in the filename
    assert r["dictionary_id"]                           # the lexicon vector's dictionary_id in the envelope


# --- 7. default manifest byte-identical (front-door: LOGIC/SCHEMA frozen) --------------
def test_default_manifest_unaffected(tree: Path):
    m = Scanner(tree, ScannerConfig(enable_specialists=True)).scan()
    # asking for a receipt is a separate projection; it doesn't change the manifest or its checksum
    _ = manifest_to_receipt(m)
    m2 = Scanner(tree, ScannerConfig(enable_specialists=True)).scan()
    assert compute_manifest_checksum(m) == compute_manifest_checksum(m2)


# --- 8. CLI ---------------------------------------------------------------------------
def test_cli_receipt_stdout(tree: Path):
    proc = subprocess.run(
        [sys.executable, "-m", "file_observer.scanner", str(tree), "--specialists", "--receipt", "--stdout"],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    r = json.loads(proc.stdout)
    assert r["receipt_doc_version"] == RECEIPT_DOC_VERSION and len(r["receipts"]) == 2


# --- 9. MCP ---------------------------------------------------------------------------
def test_mcp_receipt(tree: Path):
    pytest.importorskip("mcp", reason="mcp SDK not installed ([mcp] extra)")  # skip on the OPTIONAL SDK only — a broken
    # file_observer.mcp_server must FAIL, not skip (Codex P1, PR #179)
    import file_observer.mcp_server as mcp
    out = json.loads(mcp.scan_directory(str(tree), specialists=True, receipt=True))
    assert out["receipt_doc_version"] == RECEIPT_DOC_VERSION and len(out["receipts"]) == 2
    one = json.loads(mcp.scan_file(str(tree / "alpha.md"), specialists=True, receipt=True))
    assert len(one["receipts"]) == 1 and len(one["receipts"][0]["receipt_id"]) == 64


# --- leg-4 PR-bot findings -------------------------------------------------------------
def test_receipt_path_posix_normalized():
    """leg-4/gemini: path_id/receipt_id use a POSIX path — a backslash path normalizes so the id is
    platform-independent (a Windows FileRecord.path is already as_posix, but this guarantees it)."""
    from file_observer.scanner import _file_receipt
    mc = "0" * 64
    win = _file_receipt({"path": "sub\\dir\\f.md", "checksum_sha256": "a" * 64}, mc)
    posix = _file_receipt({"path": "sub/dir/f.md", "checksum_sha256": "a" * 64}, mc)
    assert win["receipt_id"] == posix["receipt_id"] and win["path_id"] == posix["path_id"]


def test_mcp_scan_file_receipt_binds_callers_path(tree: Path):
    """leg-4/gemini HIGH + Codex: the MCP scan_file receipt binds to the caller's path reference
    (posix), NOT the resolved absolute str(fp) — so receipt_ids are stable/portable."""
    pytest.importorskip("mcp", reason="mcp SDK not installed ([mcp] extra)")  # skip on the OPTIONAL SDK only — a broken
    # file_observer.mcp_server must FAIL, not skip (Codex P1, PR #179)
    import file_observer.mcp_server as mcp
    p = str(tree / "alpha.md")
    out = json.loads(mcp.scan_file(p, specialists=True, receipt=True))
    assert out["receipts"][0]["path_id"] == sha256(Path(p).as_posix().encode()).hexdigest()


# --- 10. version axes -----------------------------------------------------------------
