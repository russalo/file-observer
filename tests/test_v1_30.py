"""v1.30.0 — CLI robustness: fail-loud on bad input (#109) + sane default output dir (#110).

Falsify-first: every test here FAILS against v1.29.0 (which silently accepts bad input at
rc=0 and writes the default manifest into the installed package dir). Runtime/CLI behavior
only — the manifest contract is frozen (LOGIC 1.15.0 / SCHEMA 1.16 unchanged); the equality
test proves a valid scan is byte-identical.
"""
import json
import subprocess
import sys
from pathlib import Path

from file_observer import scan


def _corpus(d: Path):
    (d / "a.md").write_text("# Title\n\nbody\n")
    (d / "b.txt").write_text("plain\n")


def _run(args, cwd):
    return subprocess.run([sys.executable, "-m", "file_observer.scanner", *args],
                          capture_output=True, text=True, cwd=cwd)


# ── #109: fail loud on bad input ──────────────────────────────────────────────

def test_nonexistent_source_errors_rc2(tmp_path):
    out = _run([str(tmp_path / "no" / "such" / "dir"), "-o", str(tmp_path / "o")], cwd=tmp_path)
    assert out.returncode == 2
    assert "source directory not found" in out.stderr


def test_file_source_errors_rc2(tmp_path):
    f = tmp_path / "a.txt"; f.write_text("hi\n")
    out = _run([str(f), "-o", str(tmp_path / "o")], cwd=tmp_path)
    assert out.returncode == 2
    assert "not a directory" in out.stderr


def test_workers_below_one_errors_rc2(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    for n in ("0", "-1"):
        out = _run([str(src), "-o", str(tmp_path / "o"), "--workers", n], cwd=tmp_path)
        assert out.returncode == 2, f"--workers {n}: {out.stderr}"
        assert "--workers must be >= 1" in out.stderr


def test_preview_max_negative_errors_rc2(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    out = _run([str(src), "-o", str(tmp_path / "o"), "--preview-max", "-5"], cwd=tmp_path)
    assert out.returncode == 2
    assert "--preview-max must be >= 0" in out.stderr


def test_missing_previous_manifest_warns_not_errors(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    out = _run([str(src), "-o", str(tmp_path / "o"),
                "--previous-manifest", str(tmp_path / "gone.json")], cwd=tmp_path)
    assert out.returncode == 0, out.stderr           # optional input → warn, not error
    assert "warning" in out.stderr.lower()
    assert "previous-manifest" in out.stderr


def test_directory_previous_manifest_warns(tmp_path):
    """leg-4/gemini: a directory (or special file) as --previous-manifest yields no usable
    delta → warn (is_file(), not exists()), still rc=0."""
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    adir = tmp_path / "notafile"; adir.mkdir()
    out = _run([str(src), "-o", str(tmp_path / "o"), "--previous-manifest", str(adir)], cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    assert "warning" in out.stderr.lower() and "not a file" in out.stderr.lower()


def test_empty_real_directory_still_succeeds(tmp_path):
    """The PRESERVED case: a legitimately-empty real dir scans rc=0 with an empty manifest.
    Only nonexistent/non-dir is an error — 0 files is a valid observation."""
    src = tmp_path / "empty"; src.mkdir()
    out = _run([str(src), "-o", str(tmp_path / "o")], cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    m = scan(src)
    assert m.stats.total_files == 0


# ── #110: default output dir is the cwd, never the package ────────────────────

def test_default_output_lands_in_cwd_subdir_not_package(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    run_cwd = tmp_path / "cwd"; run_cwd.mkdir()
    out = _run([str(src)], cwd=run_cwd)              # bare invocation, no -o
    assert out.returncode == 0, out.stderr
    outdir = run_cwd / "file-observer-manifests"
    assert outdir.is_dir(), "default output must be ./file-observer-manifests/ in the cwd"
    manifests = list(outdir.glob("manifest_*.json"))
    assert manifests, "a manifest must be written into the cwd subdir"
    # never the install dir
    assert "site-packages" not in out.stdout
    assert "site-packages" not in str(manifests[0])


def test_default_output_created_if_absent(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    run_cwd = tmp_path / "cwd"; run_cwd.mkdir()
    assert not (run_cwd / "file-observer-manifests").exists()
    out = _run([str(src)], cwd=run_cwd)
    assert out.returncode == 0, out.stderr
    assert (run_cwd / "file-observer-manifests").is_dir()


# ── contract freeze: the manifest itself is unchanged ─────────────────────────

def test_valid_scan_manifest_byte_identical(tmp_path):
    """The freeze proof: a valid CLI scan with -o emits the same manifest_checksum as the
    programmatic API — none of the CLI changes touch what is observed."""
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    odir = tmp_path / "o"
    out = _run([str(src), "-o", str(odir)], cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    written = json.loads(next(odir.glob("manifest_*.json")).read_text())
    assert written["manifest_checksum"] == scan(src).manifest_checksum


# ── leg-1: the default output dir is skipped, so a re-scan can't self-include ──

def test_output_dir_skipped_during_discovery(tmp_path):
    """The tool's own default output dir is skipped at any level — a re-scan of the cwd
    never observes its own prior manifest/report (the leg-1 self-inclusion catch)."""
    src = tmp_path / "tree"; src.mkdir(); _corpus(src)
    outdir = src / "file-observer-manifests"; outdir.mkdir()       # simulate a prior run's output
    (outdir / "manifest_v1.30.0_x.json").write_text("{}")
    (outdir / "report_v1.30.0_x.md").write_text("# r\n")
    m = scan(src)
    paths = {fr.path for fr in m.files}
    assert "a.md" in paths and "b.txt" in paths                    # real content still scanned
    assert not any("file-observer-manifests" in p for p in paths), \
        "the tool's own output dir must be skipped during discovery"


def test_rescan_of_cwd_does_not_self_include(tmp_path):
    """End-to-end: bare `fo .` twice — the second scan does NOT observe the first's output."""
    src = tmp_path / "proj"; src.mkdir(); _corpus(src)
    out1 = _run(["."], cwd=src)
    assert out1.returncode == 0, out1.stderr
    assert (src / "file-observer-manifests").is_dir()              # first run wrote into the tree
    odir = tmp_path / "o"                                          # read the 2nd run via a disjoint -o
    out2 = _run([".", "-o", str(odir)], cwd=src)
    assert out2.returncode == 0, out2.stderr
    written = json.loads(next(odir.glob("manifest_*.json")).read_text())
    paths = {f["path"] for f in written["files"]}
    assert not any("file-observer-manifests" in p for p in paths), \
        "a re-scan of the cwd must not include the prior run's output dir"
