"""Packaging / import-surface tests (v1.0.1).

The package was renamed ``scanner`` -> ``file_observer`` in v1.0.1. The canonical
import path must work; the legacy ``scanner`` path must keep working but emit a
DeprecationWarning. The rename does not touch the manifest schema.
"""

import importlib
import re
import tomllib
import warnings
from pathlib import Path

import pytest


def test_version_surfaces_stay_in_sync():
    """Every place the version is written must equal SCANNER_VERSION — guards the
    drift that let pyproject / the module docstring lag the constant. (file_observer
    .__version__ is derived, so it's safe by construction; pyproject and the
    docstring are hand-maintained duplicates that need this check.)"""
    from file_observer.scanner import SCANNER_VERSION
    import file_observer.scanner as s

    root = Path(__file__).resolve().parent.parent
    pyproj = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert pyproj == SCANNER_VERSION, f"pyproject {pyproj} != SCANNER_VERSION {SCANNER_VERSION}"

    m = re.search(r"Version:\s*([0-9]+\.[0-9]+\.[0-9]+)", s.__doc__ or "")
    assert m, "scanner.py module docstring has no `Version:` line"
    assert m.group(1) == SCANNER_VERSION, f"docstring {m.group(1)} != SCANNER_VERSION {SCANNER_VERSION}"


def test_canonical_top_level_api():
    """The documented public API imports from file_observer."""
    from file_observer import Scanner, ScannerConfig, manifest_to_json  # noqa: F401

    import file_observer

    assert file_observer.__version__ == "1.15.1"
    assert "Scanner" in file_observer.__all__


def test_documented_serializers_are_exported():
    """README documents jsonl/markdown serializers as public API (PR #21 review)."""
    from file_observer import manifest_to_jsonl, manifest_to_markdown  # noqa: F401
    import file_observer

    assert "manifest_to_jsonl" in file_observer.__all__
    assert "manifest_to_markdown" in file_observer.__all__


@pytest.mark.parametrize("module", ["file_observer.scanner", "scanner.scanner"])
def test_module_cli_entrypoint(module):
    """`python -m <module>` runs the CLI (guards the legacy shim regression)."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_canonical_submodule_constants_unchanged():
    """Constants and the manifest field they feed stay stable across the 1.0.x → 1.1 line (the 1.0.1 import-package rename left them intact)."""
    from file_observer.scanner import SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION

    assert SCANNER_VERSION == "1.15.1"
    assert SCHEMA_VERSION == "1.9"  # unchanged in v1.15 — HEIC fix is LOGIC, not a contract change
    assert LOGIC_VERSION == "1.5.1"  # v1.15.1: HEIC/HEIF/AVIF MIME detection (v1.3 precedent: MIME tier = LOGIC)


def test_legacy_scanner_import_warns():
    """Importing the legacy 'scanner' package works but is deprecated."""
    import sys

    # Force a fresh import so the module-level warning fires.
    sys.modules.pop("scanner", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        scanner = importlib.import_module("scanner")
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    # Shim re-exports the same public API object.
    from file_observer import Scanner

    assert scanner.Scanner is Scanner


def test_legacy_submodule_path_still_resolves():
    """`from scanner.scanner import Scanner` (old docs/tests) still works."""
    from scanner.scanner import Scanner as LegacyScanner
    from file_observer.scanner import Scanner as CanonicalScanner

    assert LegacyScanner is CanonicalScanner
