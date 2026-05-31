"""Deprecated compatibility shim for ``scanner.scanner``.

Re-exports the implementation from ``file_observer.scanner``. The package was
renamed in v1.0.1; import from ``file_observer`` instead. See
``scanner.__init__`` for the deprecation notice (emitted once at package import).
"""

from file_observer.scanner import *  # noqa: F401,F403
from file_observer.scanner import main  # noqa: F401  (console-script / explicit import target)
