"""v1.9.1 — stat-failure record preserves the subdirectory path (Gemini F2).

The universal stat-failure FileRecord flattened a subdir file's `path` to just the
filename: `rel_path = path.relative_to(source_dir)` was computed, then `path.stat()`
raised, and the except blindly reassigned `rel_path = Path(path.name)` — discarding
the correct relative path. So a file at `sub/ghost.txt` that fails stat() (TOCTOU
race / mid-scan deletion / permission flip) reported `path = "ghost.txt"`,
inconsistent with every normal record. RFC §1.18 does not mandate flattening — it
only requires that a record is emitted, no fatal raise, and structured errors.

Fix: compute rel_path defensively (only flatten if `relative_to` itself fails),
separate from the stat I/O — so a stat failure keeps the correct source-relative path.
"""
from pathlib import Path

from file_observer.scanner import Scanner, ScannerConfig, ERR_UNIVERSAL_STAT_FAILED


def test_stat_failure_preserves_subdirectory_path(tmp_path):
    (tmp_path / "sub").mkdir()
    s = Scanner(source_dir=tmp_path, config=ScannerConfig())
    # a ghost path under sub/: relative_to() succeeds, .stat() raises → the error path
    rec = s.scan_file(tmp_path / "sub" / "ghost.txt")
    assert any(e.code == ERR_UNIVERSAL_STAT_FAILED for e in rec.errors)
    # pre-fix this was "ghost.txt" (flattened); must be the full source-relative path
    assert rec.path == "sub/ghost.txt"
    assert rec.filename == "ghost.txt"


def test_stat_failure_top_level_path_unchanged(tmp_path):
    # a top-level file's degraded path is unchanged (no subdir to preserve)
    s = Scanner(source_dir=tmp_path, config=ScannerConfig())
    rec = s.scan_file(tmp_path / "ghost.txt")
    assert rec.path == "ghost.txt"


def test_path_not_under_root_still_degrades_to_filename(tmp_path):
    # defensive fallback: if relative_to() itself fails (path not under source_dir),
    # degrade to the filename rather than crash
    s = Scanner(source_dir=tmp_path / "root", config=ScannerConfig())
    (tmp_path / "root").mkdir()
    rec = s.scan_file(tmp_path / "elsewhere.txt")   # not under source_dir/root
    assert rec.path == "elsewhere.txt"
    assert any(e.code == ERR_UNIVERSAL_STAT_FAILED for e in rec.errors)
