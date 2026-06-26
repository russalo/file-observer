"""File Observer — deterministic file observation engine.

Canonical import package. (The legacy ``scanner`` package re-exports these
names with a DeprecationWarning for backward compatibility.)
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
    "manifest_to_jsonl",
    "manifest_to_markdown",
    "__version__",
]
