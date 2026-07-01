"""v1.30.1 — anchor the self-inclusion skip to fo's ACTUAL output dir (leg-2/OpenAI red-team).

Falsify-first: these fail against v1.30.0, which skipped ANY directory named
`file-observer-manifests` at any depth (a bare-name match) — silently dropping an unrelated
user dir of that name (① silent data loss) — and whose output write wasn't wrapped (② traceback
on a non-writable output). v1.30.1 anchors the skip to the resolved output dir and fails loud
on a bad output path.
"""
import json
import subprocess
import sys
from pathlib import Path

from file_observer import scan


def _run(args, cwd):
    return subprocess.run([sys.executable, "-m", "file_observer.scanner", *args],
                          capture_output=True, text=True, cwd=cwd)


def test_unrelated_same_named_dir_is_not_dropped(tmp_path):
    """① The MAJOR fix: a user directory named `file-observer-manifests` that is NOT fo's
    output must be scanned. The programmatic API sets no skip → includes it (v1.30.0's
    UNCONDITIONAL bare-name skip wrongly dropped it, even via the API)."""
    src = tmp_path / "tree"; src.mkdir()
    (src / "a.txt").write_text("real\n")
    d = src / "docs" / "file-observer-manifests"; d.mkdir(parents=True)
    (d / "kept.md").write_text("legit user content\n")
    m = scan(src)
    paths = {fr.path for fr in m.files}
    assert "a.txt" in paths
    assert any("file-observer-manifests/kept.md" in p for p in paths), \
        "an unrelated file-observer-manifests dir must NOT be dropped"


def test_actual_output_dir_still_skipped_on_rescan(tmp_path):
    """Self-inclusion still prevented for the common case: a bare `fo .` re-scan skips its
    OWN default output dir (both runs write to cwd/file-observer-manifests)."""
    src = tmp_path / "proj"; src.mkdir(); (src / "a.txt").write_text("x\n")
    assert _run(["."], cwd=src).returncode == 0
    assert (src / "file-observer-manifests").is_dir()
    assert _run(["."], cwd=src).returncode == 0            # 2nd run, same default output
    latest = sorted((src / "file-observer-manifests").glob("manifest_*.json"))[-1]
    paths = {f["path"] for f in json.loads(latest.read_text())["files"]}
    assert "a.txt" in paths
    assert not any("file-observer-manifests" in p for p in paths), \
        "a re-scan must skip its own default output dir"


def test_output_write_failure_is_clean_not_traceback(tmp_path):
    """② A non-creatable output path fails LOUD + clean (rc=1), not a traceback."""
    src = tmp_path / "src"; src.mkdir(); (src / "a.txt").write_text("x\n")
    blocker = tmp_path / "blocked"; blocker.write_text("i am a file, not a dir\n")
    out = _run([str(src), "-o", str(blocker)], cwd=tmp_path)   # mkdir over a file → OSError
    assert out.returncode == 1, out.stderr
    assert "cannot write output" in out.stderr
    assert "Traceback" not in out.stderr


def test_valid_scan_still_byte_identical(tmp_path):
    """Contract freeze for a tree WITHOUT fo's output dir: CLI `-o` == programmatic scan()."""
    src = tmp_path / "src"; src.mkdir(); (src / "a.md").write_text("# t\n\nb\n")
    odir = tmp_path / "o"
    out = _run([str(src), "-o", str(odir)], cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    written = json.loads(next(odir.glob("manifest_*.json")).read_text())
    assert written["manifest_checksum"] == scan(src).manifest_checksum


def test_str_skip_output_dir_does_not_crash(tmp_path):
    """leg-4/gemini: a str (not Path) skip_output_dir must not crash iter_files (never-crash —
    other path-config fields like ignore_file/previous_manifest are str-typed)."""
    from file_observer.scanner import Scanner, ScannerConfig
    src = tmp_path / "s"; src.mkdir(); (src / "a.txt").write_text("x\n")
    m = Scanner(src, ScannerConfig(skip_output_dir=str(src / "file-observer-manifests"))).scan()
    assert m.stats.total_files == 1   # scanned cleanly, no AttributeError


def test_stdout_rescan_skips_prior_output_dir(tmp_path):
    """leg-4/Codex: `fo . --stdout` must skip a PRIOR `fo .`'s output dir (self-inclusion),
    even though the stdout run itself writes no file."""
    src = tmp_path / "proj"; src.mkdir(); (src / "a.txt").write_text("x\n")
    assert _run(["."], cwd=src).returncode == 0            # bare run writes ./file-observer-manifests/
    assert (src / "file-observer-manifests").is_dir()
    out = _run([".", "--stdout"], cwd=src)                 # stdout rescan
    assert out.returncode == 0, out.stderr
    paths = {f["path"] for f in json.loads(out.stdout)["files"]}
    assert "a.txt" in paths
    assert not any("file-observer-manifests" in p for p in paths), \
        "a --stdout rescan must skip fo's output location"
