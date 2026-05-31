"""v1.1 Corpus Intelligence — duplicate clustering + per-specialist stats.

Both are provisional ScanQuality fields, pure observation over already-collected
data. SCHEMA_VERSION 1.0 -> 1.1 (additive); LOGIC_VERSION unchanged.
"""

import shutil
from pathlib import Path

from file_observer.scanner import Scanner, ScannerConfig

FIXTURES = Path(__file__).parent / "fixtures"


def _scan(tmp_path, specialists=False):
    cfg = ScannerConfig(enable_specialists=specialists)
    return Scanner(source_dir=tmp_path, config=cfg).scan()


def _names(cluster):
    return {Path(p).name for p in cluster["paths"]}


class TestDuplicateClusters:
    def test_identical_files_cluster(self, tmp_path):
        (tmp_path / "a.txt").write_text("same content")
        (tmp_path / "b.txt").write_text("same content")
        (tmp_path / "unique.txt").write_text("different")
        q = _scan(tmp_path).quality
        assert q.duplicate_cluster_count == 1
        assert q.redundant_file_count == 1
        cluster = q.duplicate_clusters[0]
        assert cluster["count"] == 2
        assert _names(cluster) == {"a.txt", "b.txt"}
        all_clustered = {n for c in q.duplicate_clusters for n in _names(c)}
        assert "unique.txt" not in all_clustered

    def test_no_duplicates(self, tmp_path):
        (tmp_path / "a.txt").write_text("one")
        (tmp_path / "b.txt").write_text("two")
        q = _scan(tmp_path).quality
        assert q.duplicate_clusters == []
        assert q.duplicate_cluster_count == 0
        assert q.redundant_file_count == 0

    def test_empty_files_cluster_together(self, tmp_path):
        (tmp_path / "e1.txt").write_text("")
        (tmp_path / "e2.txt").write_text("")
        q = _scan(tmp_path).quality
        assert q.duplicate_cluster_count == 1
        assert q.duplicate_clusters[0]["count"] == 2
        assert q.duplicate_clusters[0]["size_bytes"] == 0

    def test_redundant_count_for_three_copies(self, tmp_path):
        for n in ("a", "b", "c"):
            (tmp_path / f"{n}.txt").write_text("dup")
        q = _scan(tmp_path).quality
        assert q.duplicate_clusters[0]["count"] == 3
        assert q.redundant_file_count == 2  # sum(count - 1)

    def test_cluster_shape_and_paths_sorted(self, tmp_path):
        (tmp_path / "z.txt").write_text("k")
        (tmp_path / "a.txt").write_text("k")
        c = _scan(tmp_path).quality.duplicate_clusters[0]
        assert set(c.keys()) == {"checksum_sha256", "size_bytes", "count", "paths"}
        assert c["paths"] == sorted(c["paths"])  # deterministic within cluster

    def test_deterministic_across_runs(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "b.txt").write_text("x")
        (tmp_path / "c.txt").write_text("y")
        (tmp_path / "d.txt").write_text("y")
        r1 = _scan(tmp_path).quality.duplicate_clusters
        r2 = _scan(tmp_path).quality.duplicate_clusters
        assert r1 == r2


class TestSpecialistStats:
    def test_empty_when_specialists_disabled(self, tmp_path):
        shutil.copy(FIXTURES / "sample_logo.png", tmp_path / "img.png")
        q = _scan(tmp_path, specialists=False).quality
        assert q.specialist_stats == {}

    def test_populated_when_enabled(self, tmp_path):
        shutil.copy(FIXTURES / "sample_logo.png", tmp_path / "img.png")
        q = _scan(tmp_path, specialists=True).quality
        assert "image_structure" in q.specialist_stats
        s = q.specialist_stats["image_structure"]
        assert s["attempted"] >= 1
        assert s["attempted"] == s["succeeded"] + s["failed"]

    def test_aggregate_reconciles_with_per_tool(self, tmp_path):
        shutil.copy(FIXTURES / "sample_logo.png", tmp_path / "img.png")
        q = _scan(tmp_path, specialists=True).quality
        per_tool_failed = sum(s["failed"] for s in q.specialist_stats.values())
        assert per_tool_failed == q.specialist_failures
