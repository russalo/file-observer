"""v1.25.1 — OLE2 specialists declare a full-file deviation in signal_provenance.

Falsify-first: fails against v1.25.0 (which reported `bounded_sample`), passes once the patch lands.

The OLE2 path-reading specialists (`.doc`/`.xls`/`.msg`/`.ppt`) hand `olefile` the
filesystem path and read property streams from anywhere in the compound file — NOT
the 8 KB sample. Pre-v1.25.1 they reported `trigger="bounded_sample"` +
`detail.sample_size`, which is false. This patch declares them a deviation
(`trigger="bounded_deviation"`, `detail.reason="ole2_full_file_required"`).
Surfaced as a leg-4/Codex P2 on PR #98 (v1.25.0); pre-existing + OLE2-family-wide,
so fixed for all four at once rather than diverging `.ppt` alone.

Provenance-accuracy only — no extracted VALUE changes; but it moves
`signal_provenance` bytes → `manifest_checksum` shifts for manifests with OLE2 files
(LOGIC 1.14.0→1.14.1, the v1.8.2 manifest-checksum-surface precedent).
"""
from pathlib import Path

import pytest

from file_observer.scanner import Scanner, ScannerConfig, olefile

GEN = Path(__file__).parent / "fixtures" / "generated"


def _provenance_for(rec, ns):
    """The signal_provenance entries for a given specialist namespace's fields."""
    pref = f"specialist_metadata.{ns}."
    return {k: v for k, v in (rec.signal_provenance or {}).items() if k.startswith(pref)}


@pytest.mark.skipif(olefile is None, reason="olefile not installed")
@pytest.mark.parametrize("fixture,ns", [
    ("generated.doc", "document"),
    ("generated.xls", "spreadsheet"),
    ("generated.ppt", "presentation"),
])
def test_ole2_specialist_declares_full_file_deviation(tmp_path, fixture, ns):
    src = GEN / fixture
    assert src.exists(), "run tests/fixtures/generated/generate.py"
    (tmp_path / fixture).write_bytes(src.read_bytes())
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    rec = next(f for f in m.files if f.filename == fixture)
    prov = _provenance_for(rec, ns)
    assert prov, f"no {ns} specialist provenance on {fixture}"
    for key, entry in prov.items():
        # a populated field declares the OLE2 full-file deviation; an absent field
        # (null) keeps `missing_from_bounds` — only assert on the deviation arm.
        if entry["trigger"] == "bounded_deviation":
            assert entry["detail"].get("reason") == "ole2_full_file_required", key
            assert "sample_size" not in entry["detail"], f"{key} still reports a sample_size"
        else:
            assert entry["trigger"] in {"bounded_deviation", "missing_from_bounds"}, \
                f"{key}: OLE2 field must not report bounded_sample (got {entry['trigger']})"


@pytest.mark.skipif(olefile is None, reason="olefile not installed")
def test_ole2_extracted_values_unchanged(tmp_path):
    # provenance-accuracy only — the extracted values must be byte-identical to v1.25.0.
    (tmp_path / "generated.ppt").write_bytes((GEN / "generated.ppt").read_bytes())
    m = Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()
    p = m.files[0].specialist_metadata["presentation"]
    assert p == {"slide_count": 7, "title": "File Observer Test Deck",
                 "author": "File Observer Test", "application": "Microsoft PowerPoint"}
