"""Deprecated compatibility shim.

The package was renamed ``scanner`` -> ``file_observer`` in v1.0.1. Importing
from ``scanner`` still works but is deprecated and will be removed in a future
release. Import from ``file_observer`` instead::

    from file_observer import Scanner, ScannerConfig, manifest_to_json

The manifest schema (the public contract) is unaffected by this rename.
"""

import warnings

warnings.warn(
    "The 'scanner' import package is deprecated; import from 'file_observer' "
    "instead. 'scanner' will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from file_observer import *  # noqa: F401,F403  (re-export public API)
from file_observer import __all__, __version__  # noqa: F401
