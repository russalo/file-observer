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
    _reached_through_reparse,
    _write_stdout_utf8,
)


# --- B: the .csv pin + the causal chain it defeats ------------------------------------------------
def test_csv_pinned_to_text_csv():
    # the pin holds cross-platform; on Windows this OVERRIDES the registry's vnd.ms-excel
    assert mimetypes.guess_type("x.csv") == ("text/csv", None)


def test_vnd_ms_excel_is_binary_but_text_csv_is_not():
    # documents+guards the causal chain: WITHOUT the pin a Windows .csv (-> vnd.ms-excel) would be
    # binary; WITH the pin (-> text/csv) it is not.
    assert "application/vnd.ms-excel" in BINARY_MIME_TYPES
    assert "text/csv" not in BINARY_MIME_TYPES


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


# --- A: the reparse-ancestor helper (mocked — POSIX cannot make a junction) ------------------------
def test_reached_through_reparse_detects_and_never_raises(tmp_path: Path, monkeypatch):
    root = tmp_path
    junction = root / "jlink"; junction.mkdir()
    inner = junction / "inside.txt"; inner.write_text("x", encoding="utf-8")
    normal = root / "plain.txt"; normal.write_text("y", encoding="utf-8")

    REPARSE = 0x400

    class FakeStat:
        def __init__(self, attrs): self.st_file_attributes = attrs

    real_lstat = os.lstat

    def fake_lstat(p):
        if Path(p) == junction:
            return FakeStat(REPARSE)   # the junction dir carries the reparse attribute
        return FakeStat(0)

    monkeypatch.setattr(os, "lstat", fake_lstat)
    assert _reached_through_reparse(inner, root) is True     # inside a reparse dir
    assert _reached_through_reparse(normal, root) is False    # not

    # never raises on OSError/AttributeError -> treated as not-a-reparse
    def boom(p): raise OSError("boom")
    monkeypatch.setattr(os, "lstat", boom)
    assert _reached_through_reparse(inner, root) is False
    monkeypatch.setattr(os, "lstat", real_lstat)


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
    assert SCANNER_VERSION == "1.46.0"
    assert LOGIC_VERSION == "1.24.0"   # A+B: cross-platform routing-LOGIC change (v1.15 precedent)
    assert SCHEMA_VERSION == "1.23"    # no new field / shape change
