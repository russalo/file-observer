"""v1.11.0 — opt-in `--watch` continuous trigger loop.

The hard bar (RFC §1 / §2): each emitted scan in the --watch stream is
BYTE-IDENTICAL to a one-shot `file-observer` invocation against the same FS state.
LOGIC_VERSION and SCHEMA_VERSION stay frozen — --watch only controls *when*
observation triggers, not *what*. Same lesson as --workers N in v1.9.
"""
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from file_observer.scanner import Scanner, ScannerConfig


def _has_watchfiles() -> bool:
    try:
        import watchfiles  # noqa: F401
        return True
    except ImportError:
        return False


skip_no_watchfiles = pytest.mark.skipif(
    not _has_watchfiles(), reason="--watch requires the [watch] extra")

# --watch is a POSIX-oriented feature: graceful shutdown is SIGTERM/SIGINT-based and
# the test harness reads the subprocess's stdout with a blocking readline + sends
# SIGTERM. On Windows send_signal(SIGTERM) maps to an ungraceful TerminateProcess and
# the blocking read can't honor the wall-clock deadline (no POSIX select on pipes) —
# so these would hang/misbehave. --watch is validated on POSIX (see docs/LIMITATIONS).
skip_watch_on_windows = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="--watch lifecycle (SIGTERM shutdown + blocking stdout read) is POSIX-only; "
    "validated on POSIX (docs/LIMITATIONS.md)")


def _spawn_watch(src: Path, debounce_ms: int = 100, include_files: bool = False,
                  specialists: bool = False) -> subprocess.Popen:
    """Spawn `file-observer --watch …` as a subprocess and return its Popen."""
    cmd = [sys.executable, "-m", "file_observer.scanner", str(src),
           "--watch", "--watch-debounce-ms", str(debounce_ms)]
    if specialists:
        cmd.append("--specialists")
    if include_files:
        cmd.append("--watch-include-files")
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)


def _read_n_emits(proc: subprocess.Popen, n: int, timeout: float = 6.0) -> list[dict]:
    """Read up to N JSONL emit-lines from proc.stdout, with a wall-clock timeout."""
    emits: list[dict] = []
    deadline = time.monotonic() + timeout
    while len(emits) < n and time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        emits.append(json.loads(line))
    return emits


def _stop(proc: subprocess.Popen, sig=signal.SIGTERM) -> int:
    proc.send_signal(sig)
    try:
        return proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)
        return -1


# --- the contract: stream emit ≡ one-shot scan -----------------------------------
@skip_no_watchfiles
@skip_watch_on_windows
def test_watch_initial_emit_matches_oneshot_checksum(tmp_path):
    # seed a fixture tree (deterministic content; no live writers)
    (tmp_path / "a.txt").write_text("hello\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("# header\n")

    one_shot = Scanner(source_dir=tmp_path,
                       config=ScannerConfig(enable_specialists=True, workers=1)).scan()

    proc = _spawn_watch(tmp_path, specialists=True)   # match the one-shot config
    try:
        emits = _read_n_emits(proc, 1)
        assert emits, f"watch produced no initial emit; stderr={proc.stderr.read() if proc.stderr else ''!r}"
        # The hard contract: the --watch emit's manifest_checksum equals a one-shot scan.
        assert emits[0]["manifest_checksum"] == one_shot.manifest_checksum
    finally:
        _stop(proc)


# --- runtime-only flags don't leak into meta.config -------------------------------
@skip_no_watchfiles
@skip_watch_on_windows
def test_watch_flags_excluded_from_meta_config(tmp_path):
    (tmp_path / "x.txt").write_text("x")
    proc = _spawn_watch(tmp_path, debounce_ms=80, include_files=True)
    try:
        emits = _read_n_emits(proc, 1)
        assert emits
        cfg_keys = set((emits[0].get("meta") or {}).get("config", {}).keys())
        assert "watch" not in cfg_keys
        assert "watch_debounce_ms" not in cfg_keys
        assert "watch_include_files" not in cfg_keys
    finally:
        _stop(proc)


# --- --watch-include-files opts files[] back in ----------------------------------
@skip_no_watchfiles
@skip_watch_on_windows
def test_watch_include_files_opts_in(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    # Default: files[] is INCLUDED on the initial emit (anchors the stream so
    # consumers see pre-existing state — codex PR #51); excluded on subsequent
    # rescans triggered by FS events, where the `delta` block carries the change.
    proc = _spawn_watch(tmp_path)
    try:
        emits = _read_n_emits(proc, 1)
        assert emits and len(emits[0]["files"]) == 2   # anchor includes files
    finally:
        _stop(proc)
    # With flag: files[] included on every emit
    proc = _spawn_watch(tmp_path, include_files=True)
    try:
        emits = _read_n_emits(proc, 1)
        assert emits and len(emits[0]["files"]) == 2
    finally:
        _stop(proc)


@skip_no_watchfiles
@skip_watch_on_windows
def test_watch_initial_emit_anchors_with_files(tmp_path):
    """Codex PR #51 — without files[] AND without delta.added on the first emit,
    consumers can't see pre-existing files. The fix: anchor the initial emit with
    files[] even when --watch-include-files is off."""
    (tmp_path / "x.txt").write_text("x")
    (tmp_path / "y.txt").write_text("y")
    proc = _spawn_watch(tmp_path)   # NOTE: --watch-include-files NOT passed
    try:
        emits = _read_n_emits(proc, 1)
        assert emits, "no initial emit"
        # The contract: consumers see pre-existing files via files[] OR delta.added
        first = emits[0]
        has_files = len(first.get("files", [])) >= 2
        delta = first.get("delta") or {}
        has_added = len(delta.get("added", [])) >= 2 if delta else False
        assert has_files or has_added, (
            f"initial emit anchors NOTHING: files={len(first.get('files', []))} "
            f"delta={delta}"
        )
    finally:
        _stop(proc)


# --- SIGTERM terminates cleanly with exit 0 --------------------------------------
@skip_no_watchfiles
@skip_watch_on_windows
def test_watch_sigterm_clean_exit(tmp_path):
    (tmp_path / "f.txt").write_text("f")
    proc = _spawn_watch(tmp_path)
    _ = _read_n_emits(proc, 1)   # drain the initial emit
    rc = _stop(proc, sig=signal.SIGTERM)
    assert rc == 0


# --- --watch + --output are mutually exclusive (CLI gate) -------------------------
def test_watch_with_output_exits_2(tmp_path):
    cmd = [sys.executable, "-m", "file_observer.scanner", str(tmp_path),
           "--watch", "--output", str(tmp_path / "manifests")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert r.returncode == 2
    assert "--watch is incompatible with --output" in r.stderr


# --- without the [watch] extra, a clear actionable error message -----------------
def test_watch_without_extra_exits_2_with_message(tmp_path, monkeypatch):
    # Simulate watchfiles missing by hiding it from import paths
    code = (
        "import sys, builtins\n"
        "_orig=builtins.__import__\n"
        "def _fail(name,*a,**k):\n"
        "    if name=='watchfiles' or name.startswith('watchfiles.'):\n"
        "        raise ImportError('simulated missing')\n"
        "    return _orig(name,*a,**k)\n"
        "builtins.__import__=_fail\n"
        "from file_observer.scanner import run_watch, ScannerConfig\n"
        "from pathlib import Path\n"
        f"sys.exit(run_watch(Path({str(tmp_path)!r}), ScannerConfig(watch=True)))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
    assert r.returncode == 2
    assert "--watch requires the [watch] extra" in r.stderr
