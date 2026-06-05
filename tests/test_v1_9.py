"""v1.9.0 — parallel scan (`--workers N`) determinism contract.

The hard bar (RFC §1, §6): the manifest is **byte-identical regardless of worker
count**. Parallelism changes how fast, never what. This is the falsifiable claim
that keeps `LOGIC_VERSION`/`SCHEMA_VERSION` frozen — if any output differed across
worker counts, the feature would not be shippable.

Pre-refactor this would FAIL: each worker process accumulated the corpus counters
in its own memory, so the parent's vector `applied_to_count`s came back wrong and
the manifest diverged from serial. The §4.1 purity refactor (scan_file is pure;
counters derived from the records afterward) is what makes it hold.
"""
from pathlib import Path

from file_observer.scanner import Scanner, ScannerConfig

FIXTURES = Path(__file__).parent / "fixtures"


def _scan(workers: int):
    cfg = ScannerConfig(enable_specialists=True, workers=workers)
    return Scanner(source_dir=FIXTURES, config=cfg).scan()


def test_manifest_byte_identical_across_worker_counts():
    m1 = _scan(1)
    m2 = _scan(2)
    m4 = _scan(4)
    # the whole contract in one line: same checksum (excludes only scan_id/generated_at)
    assert m1.manifest_checksum == m2.manifest_checksum == m4.manifest_checksum
    # and structurally: identical file list, in identical order
    assert [f.path for f in m1.files] == [f.path for f in m2.files] == [f.path for f in m4.files]


def test_vector_counts_identical_across_worker_counts():
    # the counters that the purity refactor moved out of scan_file must aggregate the
    # same regardless of how the per-file pass was distributed
    m1 = _scan(1)
    m4 = _scan(4)
    v1 = {v["vector_id"]: v["applied_to_count"] for v in m1.vectors_collected}
    v4 = {v["vector_id"]: v["applied_to_count"] for v in m4.vectors_collected}
    assert v1 == v4 and v1, "vector applied_to_count must be worker-count invariant"


def test_workers_not_recorded_in_manifest():
    # --workers has no causal link to output → it must not appear in meta.config
    m = _scan(4)
    assert "workers" not in m.meta.config


def test_default_workers_is_one():
    assert ScannerConfig().workers == 1


def test_pool_failure_falls_back_to_serial_byte_identical(monkeypatch):
    # never-crash: if the process pool can't run (sandbox forbids fork, BrokenProcessPool,
    # unimportable entry point), the scan must complete with a byte-identical manifest.
    import concurrent.futures
    base = Scanner(source_dir=FIXTURES,
                   config=ScannerConfig(enable_specialists=True, workers=1)).scan()

    def _boom(*a, **k):
        raise OSError("pool unavailable")
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", _boom)

    m = Scanner(source_dir=FIXTURES,
                config=ScannerConfig(enable_specialists=True, workers=4)).scan()
    assert m.manifest_checksum == base.manifest_checksum
    assert [f.path for f in m.files] == [f.path for f in base.files]
