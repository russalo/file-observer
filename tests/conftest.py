"""Shared test configuration.

`requires_libmagic` marker — for tests that assert libmagic-grade MIME detection.
On the pure-Python fallback path (no libmagic — the v1.3 fallback, exercised by the
v1.15 `test-no-libmagic` CI job and Windows runners) these assertions don't hold by
design, NOT by bug:

  - signatureless text files (.txt/.toml/.eml…) fall to the extension-fallback MIME
    tier, which records the `mime_type_fallback` diagnostic → the file is "degraded"
    (still fully observed, never an abort — bounded observation);
  - the `.eml` email specialist is skipped because the MIME safety guard distrusts
    extension-derived `message/rfc822` with no corroborating magic-byte signature
    (a text format has none). See docs/LIMITATIONS.md.

These are documented fallback limitations, so the tests skip rather than fail when
libmagic is absent. The no-libmagic job still exercises the bulk of the suite (the
HEIC/binary-format sniff, never-crash, determinism, path handling).
"""
from __future__ import annotations

import sys

import pytest

import file_observer.scanner as _fo

WINDOWS = sys.platform.startswith("win")


def _libmagic_available() -> bool:
    # Mirror exactly what Scanner.__init__ gates on (magic imported AND a usable
    # libmagic the C lib can construct) — without building a Scanner against a real
    # path (which would leak an empty temp dir at import).
    if _fo.magic is None:
        return False
    try:
        _fo.magic.Magic(mime=True)
        return True
    except Exception:
        return False


LIBMAGIC_AVAILABLE = _libmagic_available()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_libmagic: asserts libmagic-grade MIME detection; skipped on the "
        "pure-Python fallback path (see docs/LIMITATIONS.md)",
    )
    config.addinivalue_line(
        "markers",
        "posix_fs: depends on POSIX filesystem semantics the scanner handles but "
        "Windows can't set up in-test (>MAX_PATH names, chmod-deny, symlinks); "
        "skipped on Windows. The scanner's never-crash handling is exercised "
        "cross-platform by TestPathEdges in test_v1_15.",
    )


def pytest_collection_modifyitems(config, items):
    if not LIBMAGIC_AVAILABLE:
        skip_magic = pytest.mark.skip(
            reason="requires libmagic — documented pure-Python-fallback limitation "
            "(docs/LIMITATIONS.md): extension-fallback MIME marks signatureless text as "
            "degraded; .eml email specialist skipped by the MIME safety guard"
        )
        for item in items:
            if "requires_libmagic" in item.keywords:
                item.add_marker(skip_magic)
    if WINDOWS:
        skip_posix = pytest.mark.skip(
            reason="POSIX filesystem semantics not reproducible on Windows "
            "(>MAX_PATH name / chmod-deny / symlink); cross-platform never-crash "
            "is covered by test_v1_15.TestPathEdges"
        )
        for item in items:
            if "posix_fs" in item.keywords:
                item.add_marker(skip_posix)
