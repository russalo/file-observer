"""v1.28.0 — `--stdout` (manifest to stdout). Falsify-first: fails against v1.27.0.

Pure output-routing: `--stdout` content is byte-identical to the file the same scan
would write (no manifest change). Exercised end-to-end via the CLI subprocess.
"""
import json
import subprocess
import sys
from pathlib import Path

from file_observer import scan
from file_observer.scanner import SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION


def _corpus(d: Path):
    (d / "a.md").write_text("# Title\n\nbody\n")
    (d / "b.txt").write_text("plain\n")


def _run(args, cwd):
    return subprocess.run([sys.executable, "-m", "file_observer.scanner", *args],
                          capture_output=True, text=True, cwd=cwd)


def test_stdout_emits_manifest_and_writes_no_file(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    run_cwd = tmp_path / "cwd"; run_cwd.mkdir()
    out = _run([str(src), "--stdout"], cwd=run_cwd)
    assert out.returncode == 0, out.stderr
    manifest = json.loads(out.stdout)              # stdout IS the manifest (parseable JSON)
    assert "manifest_checksum" in manifest
    # deterministic content matches a programmatic scan
    assert manifest["manifest_checksum"] == scan(src).manifest_checksum
    # no "Manifest written to ..." noise on stdout
    assert "Manifest written" not in out.stdout
    # NO file written into the run CWD
    assert list(run_cwd.iterdir()) == []


def test_stdout_jsonl_format(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    out = _run([str(src), "--stdout", "--format", "jsonl"], cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    assert len(lines) >= 2                          # JSONL: header + per-file lines
    for ln in lines:
        json.loads(ln)                              # each line is valid JSON


def test_stdout_conflicts_with_output(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    out = _run([str(src), "--stdout", "-o", str(tmp_path)], cwd=tmp_path)
    assert out.returncode == 2
    assert "stdout" in out.stderr.lower() and "output" in out.stderr.lower()


def test_stdout_conflicts_with_watch(tmp_path):
    src = tmp_path / "src"; src.mkdir(); _corpus(src)
    out = _run([str(src), "--stdout", "--watch"], cwd=tmp_path)
    assert out.returncode == 2
    assert "stdout" in out.stderr.lower() and "watch" in out.stderr.lower()


def test_stdout_rejected_with_schema(tmp_path):
    # --schema already prints to stdout; --schema --stdout must be rejected, not ignored (leg-4/Codex)
    out = _run(["--schema", "--stdout"], cwd=tmp_path)
    assert out.returncode == 2
    assert "--stdout" in out.stderr


def test_stdout_utf8_non_ascii_metadata(tmp_path):
    # non-ASCII filename must not UnicodeEncodeError on a non-UTF-8 stdout (leg-4/gemini):
    # we write UTF-8 bytes to the buffer, so the bytes parse as UTF-8 regardless of locale.
    src = tmp_path / "src"; src.mkdir()
    (src / "café_résumé.txt").write_text("héllo wörld\n", encoding="utf-8")
    out = _run([str(src), "--stdout"], cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    manifest = json.loads(out.stdout)  # subprocess text= decodes UTF-8; parses cleanly
    assert any("café_résumé.txt" == f["filename"] for f in manifest["files"])


def test_version_surfaces():
    assert tuple(map(int, SCANNER_VERSION.split("."))) >= (1, 28, 0), SCANNER_VERSION  # floor (superseded)
    assert LOGIC_VERSION == "1.14.1"   # unchanged
    assert SCHEMA_VERSION == "1.16"    # unchanged
