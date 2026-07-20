"""v1.8.2 — deterministic error-path timestamp (Gemini maestro-audit finding F2).

The universal stat-failure FileRecord (ERR_UNIVERSAL_STAT_FAILED) stamped
`modified_at=self.now_iso()` — wall-clock, non-deterministic. `modified_at` is a
per-file field that feeds the manifest_checksum, so two scans over the same
consistently-unstat-able file produced DIFFERENT manifests, violating the
determinism contract (identical inputs + ScanContext → identical output). Fix:
`modified_at=""` — deterministic, matching the `checksum_sha256=""` already on this
degraded record, and keeping `modified_at` a non-null `str` so the frozen public
contract (modified_at: string, Stable) is unchanged. Found by the decorrelated Gemini leg;
the v1.8.1 in-house red-team hunted crash/bound/escape, not determinism.
"""

from file_observer.scanner import Scanner, ScannerConfig, ERR_UNIVERSAL_STAT_FAILED


def _record_for_unstattable(tmp_path):
    # a ghost path under the source dir: relative_to() works, .stat() raises
    # FileNotFoundError → the ERR_UNIVERSAL_STAT_FAILED branch fires. (Reaching
    # scan_file via a full scan() can't trigger this deterministically — iter_files
    # filters with is_file(), which already stats; only a TOCTOU race fails later.)
    s = Scanner(source_dir=tmp_path, config=ScannerConfig())
    # scan_file's error path increments per-scan counters that scan() initializes;
    # set them up so the method can be unit-tested in isolation.
    s._filename_patterns_applied_count = 0
    s._filename_patterns_files_with_any = 0
    s._filename_patterns_sums = {}
    return s.scan_file(tmp_path / "vanished.txt")


def test_stat_failure_record_degrades_with_no_walltime(tmp_path):
    rec = _record_for_unstattable(tmp_path)
    # never crash: a stat failure yields a record + an ErrorRecord
    assert any(e.code == ERR_UNIVERSAL_STAT_FAILED for e in rec.errors)
    # deterministic: pre-fix modified_at was a wall-clock ISO string; now "" (unknown),
    # matching checksum_sha256="" on this degraded record — and stays a non-null str so
    # the frozen contract (modified_at: string, Stable) is unchanged.
    assert rec.modified_at == ""
    assert isinstance(rec.modified_at, str)    # contract: still a string, never null
    assert rec.created_at is None              # created_at is the contractually-nullable one


def test_stat_failure_record_is_run_to_run_stable(tmp_path):
    # two independent records for the same failing path must be identical (no wall clock)
    r1 = _record_for_unstattable(tmp_path)
    r2 = _record_for_unstattable(tmp_path)
    assert r1.modified_at == r2.modified_at == ""
