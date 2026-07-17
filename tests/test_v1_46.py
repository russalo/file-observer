"""v1.46 — native-Windows / NTFS hardening (Windows shakedown findings).

Three fixes:
  A. reparse-aware discovery containment — the v1.8.1 symlink-escape guard is extended to NTFS
     junctions/reparse-point dirs (rglob descends into them on Windows, not POSIX) via a Windows-only
     skip of files reached THROUGH a reparse-point dir — closes the out-of-tree junction escape + the
     in-tree-junction double-count. POSIX symlink handling is unchanged (leg-1 refined this away from
     an unconditional resolve()-for-every-file that would silently drop a mid-scan-deleted file).
  B. pin .csv -> text/csv so the Windows MIME registry's application/vnd.ms-excel (a BINARY MIME)
     doesn't flip is_binary True on the no-libmagic path and kill csv_headers.
  C. byte-safe --watch/--schema stdout (route through stdout.buffer UTF-8 like the main --stdout).

Falsify-first vs 1.45.0. NOTE (honest scope): the JUNCTION-specific behavior of (A) is only
reproducible on native NTFS — POSIX rglob does not descend into directory symlinks, so a Linux unit
test cannot create the escaping case. The Linux tests here cover the retained v1.8.1 symlink
containment (an out-of-tree file symlink is excluded), the reparse-ancestor helper (mocked), and the
version axes; the junction escape/double-count is validated by the Tailnet Windows shakedown re-run
(RFC §5).
"""
from __future__ import annotations

import io
import mimetypes
import os
import sys
from pathlib import Path

import pytest

from file_observer.scanner import (
    BINARY_MIME_TYPES,
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
    _should_prune_dir,
    _write_stdout_utf8,
)


# --- B: the .csv pin + the causal chain it defeats ------------------------------------------------
def test_csv_pinned_to_text_csv():
    # the pin holds cross-platform; on Windows this OVERRIDES the registry's vnd.ms-excel
    assert mimetypes.guess_type("x.csv") == ("text/csv", None)


def test_vnd_ms_excel_is_binary_but_text_csv_is_not(tmp_path: Path):
    # Reproduce the Windows failure MECHANISM on Linux via detect_binary directly:
    # the Windows registry MIME (application/vnd.ms-excel) flips is_binary True → the
    # text tier (csv_headers) is skipped; the v1.46 pin forces text/csv, which stays
    # text. NOTE: the pin is a NO-OP on Linux (guess_type is already text/csv there),
    # so the true end-to-end falsifier — fail@1.45, pass@1.46 — is the Windows suite's
    # test_csv_headers_extracted, validated by the Ally X shakedown re-run (RFC §5).
    assert "application/vnd.ms-excel" in BINARY_MIME_TYPES
    assert "text/csv" not in BINARY_MIME_TYPES
    sc = Scanner(tmp_path, ScannerConfig())
    sample = b"name,age\nalice,30\nbob,25\n"
    is_bin_excel, _ = sc.detect_binary(sample, "application/vnd.ms-excel")
    is_bin_csv, _ = sc.detect_binary(sample, "text/csv")
    assert is_bin_excel is True, "the registry MIME → binary (the bug the pin avoids on Windows)"
    assert is_bin_csv is False, "text/csv (the pin) → text → csv_headers reachable"


def test_csv_stays_text_with_headers(tmp_path: Path):
    (tmp_path / "data.csv").write_text("name,age\nalice,30\nbob,25\n", encoding="utf-8")
    m = Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan()
    rec = next(f for f in m.files if f.path == "data.csv")
    assert rec.is_binary is False
    headers = (rec.structural or {}).get("csv_headers") if isinstance(rec.structural, dict) else None
    # structural may be a dataclass; fetch defensively
    if headers is None and rec.structural is not None:
        headers = getattr(rec.structural, "csv_headers", None)
    assert headers == ["name", "age"]


# --- A: unconditional resolve()-containment (security, Linux-testable via a file symlink) ----------
@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_out_of_tree_file_symlink_excluded(tmp_path: Path):
    outside = tmp_path / "outside"; outside.mkdir()
    secret = outside / "secret.txt"; secret.write_text("SECRET\n", encoding="utf-8")
    tree = tmp_path / "tree"; tree.mkdir()
    (tree / "real.txt").write_text("in tree\n", encoding="utf-8")
    os.symlink(secret, tree / "link.txt")   # escapes the tree
    m = Scanner(tree, ScannerConfig()).scan()
    paths = {f.path for f in m.files}
    assert "real.txt" in paths
    assert not any("link" in p or "secret" in p for p in paths), "out-of-tree symlink LEAKED"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_in_tree_file_symlink_kept(tmp_path: Path):
    target = tmp_path / "target.txt"; target.write_text("hi\n", encoding="utf-8")
    os.symlink(target, tmp_path / "alias.txt")   # in-tree symlink -> resolves in-tree -> kept
    m = Scanner(tmp_path, ScannerConfig()).scan()
    paths = {f.path for f in m.files}
    assert "target.txt" in paths and "alias.txt" in paths


# --- A: the reparse-dir prune helper (mocked — POSIX cannot make a junction) -----------------------
def test_should_prune_dir_reparse_and_failclosed(tmp_path: Path, monkeypatch):
    # v1.46.8 (#169): prune gates on the NAME-SURROGATE tag bit, not the bare reparse bit.
    # A junction (name surrogate) prunes; a NON-surrogate reparse dir (OneDrive Files-On-
    # Demand / Data-Dedup) must DESCEND — pruning it dropped its in-tree subtree silently.
    root = tmp_path
    root_resolved = root.resolve()
    junction = root / "jlink"
    junction.mkdir()
    cloud = root / "cloud"
    cloud.mkdir()
    normal = root / "plain"
    normal.mkdir()

    REPARSE = 0x400
    real_lstat = os.lstat

    class FakeStat:
        def __init__(self, attrs, tag=0):
            self.st_file_attributes = attrs
            self.st_reparse_tag = tag

    def fake_lstat(p, *a, **k):
        pp = Path(p)
        if pp == junction:
            return FakeStat(REPARSE, 0xA0000003)   # IO_REPARSE_TAG_MOUNT_POINT — name surrogate
        if pp == cloud:
            return FakeStat(REPARSE, 0x9000001A)   # IO_REPARSE_TAG_CLOUD — NOT a surrogate
        if pp == normal:
            return FakeStat(0)                       # normal dir
        return real_lstat(p, *a, **k)               # delegate so resolve() still works

    monkeypatch.setattr(os, "lstat", fake_lstat)
    assert _should_prune_dir(junction, root_resolved) is True    # name surrogate → prune (contained)
    assert _should_prune_dir(cloud, root_resolved) is False      # non-surrogate reparse → DESCEND (#169)
    assert _should_prune_dir(normal, root_resolved) is False     # normal in-tree → descend


def test_should_prune_dir_failclosed_on_inconclusive(tmp_path: Path, monkeypatch):
    # Force the INCONCLUSIVE-attribute-read path PORTABLY: POSIX os.lstat() lacks
    # st_file_attributes (AttributeError) but Windows HAS it (so a normal dir there
    # is correctly identified as non-reparse and never reaches the fallback). Raise
    # OSError for exactly the two dirs under test — the helper's `except (OSError,
    # AttributeError)` catches it on every OS → the fail-closed resolve()-containment
    # runs: an in-tree dir is kept, an out-of-tree one pruned. Delegate for all other
    # paths so resolve() still works.
    root = tmp_path / "root"; root.mkdir(); root_resolved = root.resolve()
    intree = root / "d"; intree.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    real_lstat = os.lstat

    def fake_lstat(p, *a, **k):
        try:
            hit = Path(p) in (intree, outside)
        except TypeError:
            hit = False
        if hit:
            raise OSError("simulated inconclusive attribute read")
        return real_lstat(p, *a, **k)

    monkeypatch.setattr(os, "lstat", fake_lstat)
    assert _should_prune_dir(intree, root_resolved) is False      # inconclusive → resolves in-tree → keep
    assert _should_prune_dir(outside, root_resolved) is True       # inconclusive → resolves out-of-tree → prune (fail-closed)


def test_windows_reparse_dir_pruned_from_walk(tmp_path: Path, monkeypatch):
    # end-to-end: simulate Windows + a reparse dir; iter_files must NOT descend into it
    # (no records under it) — closes escape/double-count/DoS BEFORE materializing its subtree.
    tree = tmp_path / "t"; tree.mkdir()
    (tree / "real.txt").write_text("keep", encoding="utf-8")
    j = tree / "jlink"; j.mkdir(); (j / "inside.txt").write_text("dup", encoding="utf-8")
    import file_observer.scanner as s
    monkeypatch.setattr(s, "_WINDOWS", True)
    monkeypatch.setattr(s, "_should_prune_dir", lambda p, root_resolved: p.name == "jlink")
    m = s.Scanner(tree, s.ScannerConfig()).scan()
    paths = {f.path for f in m.files}
    assert "real.txt" in paths
    assert not any("jlink" in p for p in paths), "reparse dir was descended into"


# --- C: byte-safe stdout helper -------------------------------------------------------------------
def test_write_stdout_utf8_uses_buffer(monkeypatch):
    buf = io.BytesIO()

    class FakeStdout:
        buffer = buf
        def write(self, s): raise AssertionError("must use .buffer, not text write")

    fs = FakeStdout(); fs.buffer = buf
    monkeypatch.setattr(sys, "stdout", fs)
    _write_stdout_utf8("héllo ✓\n")
    assert buf.getvalue() == "héllo ✓\n".encode("utf-8")


def test_write_stdout_utf8_falls_back_without_buffer(monkeypatch):
    sink = io.StringIO()   # no .buffer attribute
    monkeypatch.setattr(sys, "stdout", sink)
    _write_stdout_utf8("plain\n")
    assert sink.getvalue() == "plain\n"


# --- version axes ---------------------------------------------------------------------------------
def test_version_axes():
    assert tuple(int(p) for p in SCANNER_VERSION.split(".")) >= (1, 46, 0)   # floor (v1.46.1 bumped SCANNER)
    assert tuple(int(p) for p in LOGIC_VERSION.split(".")) >= (1, 24, 0)   # floor (v1.46.1 bumped LOGIC)
    assert SCHEMA_VERSION == "1.23"    # no new field / shape change
