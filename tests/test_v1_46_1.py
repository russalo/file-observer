"""v1.46.1 (#156, patch) — emit the missing signal_provenance entry for structural.csv_headers.

Pre-existing gap: csv_headers was extracted with no per-field signal_provenance entry while its
structural siblings (title, document_keys) had one. This adds it (new trigger csv_header_row), which
moves manifest_checksum for CSV-with-headers manifests (a values-move — the v1.25.1 precedent). No new
manifest field, no routing flag flip. Falsify-first vs 1.46.0.
"""
from __future__ import annotations

from pathlib import Path

from file_observer.scanner import (
    LOGIC_VERSION,
    PROVENANCE_TRIGGERS,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
    compute_manifest_checksum,
)


def _scan(tmp_path: Path):
    (tmp_path / "data.csv").write_text("name,age,city\nalice,30,NYC\nbob,25,LA\n", encoding="utf-8")
    (tmp_path / "note.md").write_text("# Title\nbody text here\n", encoding="utf-8")
    return Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan()


def test_csv_headers_provenance_emitted(tmp_path: Path):
    m = _scan(tmp_path)
    csv = next(f for f in m.files if f.path == "data.csv")
    prov = csv.signal_provenance or {}
    assert "structural.csv_headers" in prov, "csv_headers must carry a signal_provenance entry (#156)"
    e = prov["structural.csv_headers"]
    assert e["layer"] == "derived"
    assert e["method"] == "extract_csv_headers"
    assert e["trigger"] == "csv_header_row"


def test_trigger_registered():
    # the --schema completeness guard requires every used trigger to be in the registry
    assert "csv_header_row" in PROVENANCE_TRIGGERS
    assert PROVENANCE_TRIGGERS["csv_header_row"]["method"] == "extract_csv_headers"


def test_gated_to_csv(tmp_path: Path):
    m = _scan(tmp_path)
    md = next(f for f in m.files if f.path == "note.md")
    assert "structural.csv_headers" not in (md.signal_provenance or {})


def test_provenance_entry_is_in_the_checksum(tmp_path: Path):
    # the entry is a real values-move: it feeds manifest_checksum, so removing it changes the checksum
    m = _scan(tmp_path)
    assert m.manifest_checksum == compute_manifest_checksum(m)
    c1 = m.manifest_checksum
    csv = next(f for f in m.files if f.path == "data.csv")
    del csv.signal_provenance["structural.csv_headers"]
    assert compute_manifest_checksum(m) != c1, "csv_headers provenance must be inside manifest_checksum"


def test_version_axes():
    assert tuple(int(p) for p in SCANNER_VERSION.split(".")) >= (1, 46, 1)   # floor (v1.46.2 bumped SCANNER)
    assert tuple(int(p) for p in LOGIC_VERSION.split(".")) >= (1, 24, 1)   # floor (v1.46.2 bumped LOGIC)
    assert SCHEMA_VERSION == "1.23"    # no new manifest field / shape change
