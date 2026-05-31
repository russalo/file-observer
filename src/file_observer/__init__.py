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
    manifest_to_json,
)
from .scanner import SCANNER_VERSION as __version__

__all__ = [
    "Scanner",
    "ScanManifest",
    "ScannerConfig",
    "FileRecord",
    "StructuralRecord",
    "manifest_to_json",
    "__version__",
]
