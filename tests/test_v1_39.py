"""v1.39 — MCP front-door: lexicon + delta. Falsify-first.

The MCP server (v1.37) shipped before the bring-your-own-lexicon observer (v1.38); v1.39 threads
BOTH the lexicon (server-startup `--lexicon` flag — terms never cross the wire) and delta scanning
(`previous_manifest_path` param) through the existing 4 tools. A front-door: the manifest is
byte-identical to a CLI scan with the same settings → LOGIC + SCHEMA UNCHANGED.

Benign placeholder lexicon only — the sensitive lexicon is never in code/tests (the v1.38 line).

Version axes: SCANNER 1.38.1→1.39.0 · LOGIC unchanged (1.21.0) · SCHEMA unchanged (1.22).
"""
from __future__ import annotations

import json

import pytest

from file_observer.scanner import (
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
    Scanner, ScannerConfig, manifest_to_json,
)

mcp_server = pytest.importorskip("file_observer.mcp_server", reason="mcp SDK not installed ([mcp] extra)")

BENIGN_LEXICON = {
    "lexicon_id": "benign-mcp-v1",
    "categories": {"fruit": ["apple", "banana"], "animal": ["cat"]},
}
DISTINCTIVE = {"lexicon_id": "d1", "categories": {"critters": ["quokka", "narwhal"]}}


@pytest.fixture
def lexicon_server(monkeypatch):
    """Server with a benign lexicon configured at startup (the --lexicon flag path)."""
    from file_observer.scanner import parse_lexicon
    monkeypatch.setattr(mcp_server, "_LEXICON", parse_lexicon(BENIGN_LEXICON))
    yield mcp_server


class TestLexicon:
    def test_scan_file_carries_lexicon_match(self, lexicon_server, tmp_path):
        (tmp_path / "f.txt").write_text("apple banana cat cat")
        rec = json.loads(lexicon_server.scan_file(str(tmp_path / "f.txt")))
        blk = rec["specialist_metadata"]["lexicon_match"]
        assert blk["categories"]["fruit"]["count"] == 2
        assert blk["categories"]["animal"]["count"] == 2
        assert "lexicon_match" in rec["safety_flags"]

    def test_scan_summary_surfaces_per_category_hits(self, lexicon_server, tmp_path):
        (tmp_path / "a.txt").write_text("apple cat")
        (tmp_path / "b.txt").write_text("banana")
        d = json.loads(lexicon_server.scan_summary(str(tmp_path)))
        lex = d["notable"]["lexicon"]
        assert lex["lexicon_id"] == "benign-mcp-v1"
        assert lex["category_hits"]["fruit"] == 2 and lex["category_hits"]["animal"] == 1
        assert lex["files_matched"] == 2

    def test_no_lexicon_no_lexicon_block(self, tmp_path):
        # dormant when the server has no lexicon configured (_LEXICON is None by default)
        (tmp_path / "a.txt").write_text("apple cat")
        d = json.loads(mcp_server.scan_summary(str(tmp_path)))
        assert "lexicon" not in d["notable"]

    def test_terms_never_in_lexicon_structures(self, monkeypatch, tmp_path):
        # The lexicon MATCH block + the lexicon vector summary must be term-free (only counts + category
        # names + the hash). (File CONTENT — content_preview — legitimately shows the file's own text; the
        # guarantee is about the lexicon structures fo emits, not about hiding the scanned bytes.)
        from file_observer.scanner import parse_lexicon
        monkeypatch.setattr(mcp_server, "_LEXICON", parse_lexicon(DISTINCTIVE))
        (tmp_path / "f.txt").write_text("a quokka met a narwhal")
        blk = json.loads(mcp_server.scan_file(str(tmp_path / "f.txt")))["specialist_metadata"]["lexicon_match"]
        lex = json.loads(mcp_server.scan_summary(str(tmp_path)))["notable"]["lexicon"]
        assert blk["categories"]["critters"]["count"] == 2   # matched
        for struct in (blk, lex):
            assert "quokka" not in json.dumps(struct) and "narwhal" not in json.dumps(struct)

    def test_front_door_checksum_identical_to_scan_with_lexicon(self, lexicon_server, tmp_path):
        from file_observer.scanner import parse_lexicon
        for i in range(4):
            (tmp_path / f"f{i}.txt").write_text("apple cat banana " * (i + 1))
        via_mcp = json.loads(lexicon_server.scan_directory(str(tmp_path), max_files=1000))
        oracle = json.loads(manifest_to_json(
            Scanner(source_dir=tmp_path,
                    config=ScannerConfig(lexicon=parse_lexicon(BENIGN_LEXICON))).scan()))
        assert via_mcp["manifest_checksum"] == oracle["manifest_checksum"]


class TestDelta:
    def test_scan_directory_delta_block(self, tmp_path):
        (tmp_path / "keep.txt").write_text("hello")
        (tmp_path / "gone.txt").write_text("bye")
        prev = json.loads(mcp_server.scan_directory(str(tmp_path), max_files=1000))
        prev_path = tmp_path / "prev.json"
        prev_path.write_text(json.dumps(prev))
        # mutate: remove gone.txt, add new.txt
        (tmp_path / "gone.txt").unlink()
        (tmp_path / "new.txt").write_text("fresh")
        m = json.loads(mcp_server.scan_directory(str(tmp_path), max_files=1000,
                                                 previous_manifest_path=str(prev_path)))
        assert m["delta"] is not None
        assert "new.txt" in m["delta"]["added"]
        assert "gone.txt" in m["delta"]["removed"]

    def test_scan_summary_surfaces_delta_counts(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        prev = json.loads(mcp_server.scan_directory(str(tmp_path), max_files=1000))
        prev_path = tmp_path / "p.json"; prev_path.write_text(json.dumps(prev))
        (tmp_path / "b.txt").write_text("y")
        d = json.loads(mcp_server.scan_summary(str(tmp_path), previous_manifest_path=str(prev_path)))
        assert d["notable"]["delta"]["added"] >= 1

    def test_bad_previous_manifest_degrades(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "notamanifest.json").write_text("{}")   # valid JSON, not a manifest
        # must not crash — returns a manifest (delta may be null/empty)
        out = mcp_server.scan_directory(str(tmp_path), max_files=1000,
                                        previous_manifest_path=str(tmp_path / "notamanifest.json"))
        assert json.loads(out)["manifest_checksum"]   # produced a valid manifest, didn't crash

    def test_missing_previous_manifest_path_errors(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        with pytest.raises(ValueError):
            mcp_server.scan_directory(str(tmp_path), previous_manifest_path=str(tmp_path / "nope.json"))


class TestStartup:
    def test_bad_lexicon_fails_at_startup(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"; bad.write_text('{"lexicon_id":"x","categories":{}}')
        monkeypatch.setattr("sys.argv", ["file-observer-mcp", "--lexicon", str(bad)])
        with pytest.raises(SystemExit):   # argparse ap.error → SystemExit(2)
            mcp_server.main()


class TestVersioning:
    def test_axes(self):
        def _v(s): return tuple(int(p) for p in s.split("."))
        assert _v(SCANNER_VERSION) >= (1, 39, 0)
        assert _v(LOGIC_VERSION) >= (1, 21, 0)   # front-door froze it at 1.21.0; v1.41 bumped past (floor)
        assert _v(SCHEMA_VERSION) >= (1, 22)      # floor (v1.41 → 1.23)
