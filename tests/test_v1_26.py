"""v1.26.0 — one-call public API (`scan` / `scan_to_json`).

Falsify-first: fails against v1.25.1 (the convenience functions don't exist yet),
passes once v1.26.0 lands.

The whole point is ergonomics with ZERO behavior change: `scan(p)` must produce a
byte-identical manifest to the explicit `Scanner(Path(p), ScannerConfig()).scan()`
path. The byte-identical assertion IS the contract (no LOGIC/SCHEMA change).
"""
from pathlib import Path

import file_observer
from file_observer import (
    Scanner, ScannerConfig, manifest_to_json, scan, scan_to_json,
)
from file_observer.scanner import SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION


def _corpus(tmp_path: Path) -> Path:
    (tmp_path / "a.md").write_text("# Title\n\nbody\n")
    (tmp_path / "b.txt").write_text("plain text\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.json").write_text('{"k": 1}\n')
    return tmp_path


def test_scan_byte_identical_to_explicit(tmp_path):
    d = _corpus(tmp_path)
    via_scan = scan(d)
    via_explicit = Scanner(source_dir=Path(d), config=ScannerConfig()).scan()
    # the manifest_checksum excludes scan_id/generated_at, so equal checksum = same manifest
    assert via_scan.manifest_checksum == via_explicit.manifest_checksum


def test_scan_accepts_str_or_path(tmp_path):
    d = _corpus(tmp_path)
    assert scan(str(d)).manifest_checksum == scan(Path(d)).manifest_checksum


def test_scan_specialists_alias_maps(tmp_path):
    d = _corpus(tmp_path)
    via_scan = scan(d, specialists=True)
    via_explicit = Scanner(source_dir=Path(d),
                           config=ScannerConfig(enable_specialists=True)).scan()
    assert via_scan.manifest_checksum == via_explicit.manifest_checksum


def test_scan_workers_alias_maps(tmp_path):
    d = _corpus(tmp_path)
    # byte-identical across workers is the v1.9 contract; scan(workers=) just forwards it
    assert scan(d, workers=2).manifest_checksum == scan(d, workers=1).manifest_checksum


def test_scan_passthrough_kwarg_reaches_config(tmp_path):
    d = _corpus(tmp_path)
    # a ScannerConfig field passed through **config_kwargs (exclude_hidden) takes effect
    (d / ".hidden.txt").write_text("secret\n")
    shown = scan(d, exclude_hidden=False)
    hidden = scan(d, exclude_hidden=True)
    shown_names = {f.filename for f in shown.files}
    hidden_names = {f.filename for f in hidden.files}
    assert ".hidden.txt" in shown_names
    assert ".hidden.txt" not in hidden_names
    # ergonomics-only across the passthrough surface too: byte-identical to the explicit path
    explicit = Scanner(source_dir=Path(d), config=ScannerConfig(exclude_hidden=True)).scan()
    assert hidden.manifest_checksum == explicit.manifest_checksum


def test_scan_to_json_is_manifest_to_json_of_a_scan(tmp_path):
    import json
    d = _corpus(tmp_path)
    # scan_to_json re-scans, so scan_id/generated_at (volatile) differ from a separate
    # scan() — compare on the deterministic content (manifest_checksum excludes those).
    parsed = json.loads(scan_to_json(d))
    assert parsed["manifest_checksum"] == scan(d).manifest_checksum
    # and it IS exactly manifest_to_json of its own manifest shape (valid, indented JSON)
    m = scan(d)
    assert scan_to_json.__doc__ and json.loads(manifest_to_json(m))["manifest_checksum"] == m.manifest_checksum


def test_public_api_exports():
    assert "scan" in file_observer.__all__
    assert "scan_to_json" in file_observer.__all__
    # legacy shim re-exports too
    from scanner import scan as legacy_scan  # noqa: F401


def test_version_surfaces():
    assert SCANNER_VERSION == "1.26.0"
    assert LOGIC_VERSION == "1.14.1"   # unchanged — no routing change
    assert SCHEMA_VERSION == "1.16"    # unchanged — manifest byte-identical
