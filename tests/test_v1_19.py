"""v1.19.0 — human-readable surfaces refresh.

(A) The per-scan `summary` (`_build_summary`) is brought current: it names the `provenance`
vector (previously skipped), adds a capture-metadata line (geotagged count + capture
devices), breaks the bare safety-flag count into NAMED flags, surfaces `preservation`, and
COMMENTS on the ambiguous (content-vs-extension MIME mismatches, polyglots) rather than
presenting a falsely-clean count.

(B) A new `--schema --format summary` — a human-readable PROSE rendering of the build's
COMPLETE observable surface, the readable counterpart to `--schema --format json|md`. Walks
the SAME introspection registries (single source of truth → cannot drift).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig, build_schema_document, schema_to_summary,
    SAFETY_FLAGS, ERROR_CODES, PROVENANCE_TRIGGERS, SPECIALIST_NAMESPACE,
    SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
)

GEN = Path(__file__).parent / "fixtures" / "generated"
VID = Path(__file__).parent.parent / "scratch" / "v1_18_corpus" / "video"


def test_release_version_surfaces():
    def _v(x): return tuple(int(p) for p in x.split("."))
    assert _v(SCANNER_VERSION) >= (1, 19, 0), f"SCANNER regressed: {SCANNER_VERSION!r}"
    assert _v(LOGIC_VERSION) >= (1, 9, 0), f"LOGIC regressed: {LOGIC_VERSION!r}"
    assert _v(SCHEMA_VERSION) >= (1, 12), f"SCHEMA regressed: {SCHEMA_VERSION!r}"


# --------------------------------------------------------------- (A) freshened scan summary
class TestScanSummary:
    def _summary(self, tmp_path, files):
        for name, data in files.items():
            (tmp_path / name).write_bytes(data)
        m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        return m.summary

    def test_named_safety_flags_and_capture_line(self, tmp_path):
        # geotagged video → named flag + Capture line with the device
        s = self._summary(tmp_path, {"v.mov": (GEN / "video_qt_gps.mov").read_bytes()})
        assert "safety flags: geotagged ×1" in s   # NAMED, not "1 safety flags"
        assert "Capture:" in s and "geotagged" in s
        assert "captured by" in s and "TestMake TestPhone X" in s

    def test_no_capture_line_without_capture_metadata(self, tmp_path):
        s = self._summary(tmp_path, {"a.txt": b"just some text\n"})
        assert "Capture:" not in s

    def test_mime_mismatch_commented(self, tmp_path):
        # a PNG with a .txt extension → content-vs-extension mismatch, commented honestly
        s = self._summary(tmp_path, {"fake.txt": (GEN / "image_heic.heic").read_bytes()})
        assert "content-vs-extension MIME mismatch" in s

    def test_deterministic(self, tmp_path):
        files = {"v.mov": (GEN / "video_qt_gps.mov").read_bytes(), "a.txt": b"hi\n"}
        (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
        assert self._summary(tmp_path / "a", files) == self._summary(tmp_path / "b", files)

    def test_workers_byte_identical(self, tmp_path):
        (tmp_path / "v.mov").write_bytes((GEN / "video_qt_gps.mov").read_bytes())
        (tmp_path / "n.mov").write_bytes((GEN / "video_qt_nogps.mov").read_bytes())
        m1 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
        m4 = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True, workers=4)).scan()
        assert m1.summary == m4.summary
        assert m1.manifest_checksum == m4.manifest_checksum

    @pytest.mark.skipif(not (VID / "iphone16promax_gps.MOV").exists(),
                        reason="real iPhone corpus is local-gitignored")
    def test_real_corpus_capture_line(self):
        m = Scanner(source_dir=VID, config=ScannerConfig(enable_specialists=True)).scan()
        # the corpus may hold several device models — assert the device(s) + geotagged are
        # surfaced, robust to which/how-many clips are present (don't pin a prefix).
        assert "Capture:" in m.summary
        assert "Apple iPhone 16 Pro Max" in m.summary
        assert "geotagged" in m.summary


# --------------------------------------------------------------- (B) prose schema
class TestProseSchema:
    @pytest.fixture(scope="class")
    def prose(self):
        return schema_to_summary(build_schema_document())

    def test_header_and_voice(self, prose):
        assert prose.startswith(f"File Observer {SCANNER_VERSION} — what it can observe")
        assert "observe-only and deterministic" in prose

    def test_names_every_safety_flag(self, prose):
        for name in SAFETY_FLAGS:
            assert name in prose, f"safety flag {name} missing from prose schema"

    def test_names_every_error_code(self, prose):
        for code in ERROR_CODES:
            assert code in prose, f"error code {code} missing"

    def test_names_every_provenance_trigger(self, prose):
        for trig in PROVENANCE_TRIGGERS:
            assert trig in prose, f"provenance trigger {trig} missing"

    def test_names_every_specialist_namespace(self, prose):
        for ns in set(SPECIALIST_NAMESPACE.values()):
            assert ns in prose, f"namespace {ns} missing"

    def test_names_every_specialist_tool(self, prose):
        # leg-2/Gemini: the structured schema enumerates specialists.tools — the prose must
        # not silently drop them (the completeness claim covers tools too).
        from file_observer.scanner import SPECIALIST_TOOLS
        for tool in set(SPECIALIST_TOOLS.values()):
            assert tool in prose, f"specialist tool {tool} missing from prose schema"

    def test_names_key_capture_fields(self, prose):
        # the v1.16-v1.18 story must be visible
        for f in ("make", "model", "gps_present", "gps_source", "datetime_original"):
            assert f in prose

    def test_completeness_no_registry_dropped(self, prose):
        # the prose must mention every safety_flag, error_code, trigger, namespace, and
        # vector_id — the single-source-of-truth completeness guard (v1.13 discipline).
        doc = build_schema_document()
        for v in doc["vectors"]:
            assert v["vector_id"] in prose
        for sig in doc["format_signatures"]:
            assert sig in prose

    def test_deterministic(self, prose):
        assert schema_to_summary(build_schema_document()) == prose


# --------------------------------------------------------------- (B) via the CLI
class TestProseSchemaCLI:
    def _run(self, *args):
        return subprocess.run([sys.executable, "-m", "file_observer.scanner", *args],
                              capture_output=True, text=True)

    def test_cli_summary_format(self):
        r = self._run("--schema", "--schema-format", "summary")
        assert r.returncode == 0
        assert "what it can observe" in r.stdout
        assert "SAFETY FLAGS" in r.stdout

    def test_cli_summary_does_not_scan(self, tmp_path):
        # --schema is a non-scanning surface (v1.13): a source dir is REJECTED, not scanned.
        (tmp_path / "x.txt").write_bytes(b"hi")
        r = self._run("--schema", "--schema-format", "summary", str(tmp_path))
        assert r.returncode == 2
        assert "does not scan" in r.stderr
