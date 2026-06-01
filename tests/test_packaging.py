"""Packaging / import-surface tests (v1.0.1).

The package was renamed ``scanner`` -> ``file_observer`` in v1.0.1. The canonical
import path must work; the legacy ``scanner`` path must keep working but emit a
DeprecationWarning. The manifest schema is unaffected (SCHEMA_VERSION stays 1.0).
"""

import importlib
import warnings

import pytest


def test_canonical_top_level_api():
    """The documented public API imports from file_observer."""
    from file_observer import Scanner, ScannerConfig, manifest_to_json  # noqa: F401

    import file_observer

    assert file_observer.__version__ == "1.2.1"
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

    assert SCANNER_VERSION == "1.2.1"
    assert SCHEMA_VERSION == "1.2"  # additive minor bump (v1.1 corpus-intelligence fields)
    assert LOGIC_VERSION == "1.1.1"  # no routing change


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
