"""File Observer — deterministic file observation engine.

Canonical import package (``scanner`` -> ``file_observer`` in v1.0.1; the deprecated
``scanner`` shim was removed in v1.50.0).
"""

from .scanner import (
    Scanner,
    ScanManifest,
    ScannerConfig,
    FileRecord,
    StructuralRecord,
    scan,
    scan_to_json,
    manifest_to_json,
    manifest_to_receipt,
    manifest_to_jsonl,
    manifest_to_markdown,
)
from .scanner import SCANNER_VERSION as __version__

__all__ = [
    "Scanner",
    "ScanManifest",
    "ScannerConfig",
    "FileRecord",
    "StructuralRecord",
    "scan",
    "scan_to_json",
    "manifest_to_json",
    "manifest_to_receipt",
    "manifest_to_jsonl",
    "manifest_to_markdown",
    "__version__",
]
