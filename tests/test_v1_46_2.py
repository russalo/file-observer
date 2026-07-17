"""v1.46.2 (patch) — pin .vx → text/plain (Windows shakedown MIME-sweep finding).

.vx is unknown to mimetypes.guess_type on every OS (returns None). On Linux libmagic reads it as
text/plain (is_binary False); on the no-libmagic Windows path a None extension_mime falls back to
application/octet-stream (BINARY) → is_binary flipped True — the same class as the v1.46 .csv pin.
Pinning text/plain aligns every OS.

Falsify-first vs 1.46.1. NOTE: the is_binary flip is only observable on Windows (Linux already reads
.vx as text via libmagic), so the end-to-end falsifier is the Windows shakedown MIME sweep (which
reported .vx flipping at 1.46.1). The Linux-observable falsifier is the extension_mime pin below
(None → text/plain), which moves the .vx manifest on every OS.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from file_observer.scanner import (
    BINARY_MIME_TYPES,
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    Scanner,
    ScannerConfig,
)


def test_vx_pinned_to_text_plain():
    # the pin holds on every OS; on Windows this overrides the None → octet-stream fallback
    assert mimetypes.guess_type("x.vx") == ("text/plain", None)


def test_octet_stream_is_binary_but_text_plain_is_not():
    # the causal chain the pin defeats: a None extension_mime on Windows resolved to octet-stream
    # (a BINARY type) → is_binary True; text/plain is not binary
    assert "application/octet-stream" in BINARY_MIME_TYPES
    assert "text/plain" not in BINARY_MIME_TYPES
    sc = Scanner(Path("."), ScannerConfig())
    sample = b"<root><a>x</a></root>\n"
    assert sc.detect_binary(sample, "application/octet-stream")[0] is True
    assert sc.detect_binary(sample, "text/plain")[0] is False


def test_vx_scans_as_text(tmp_path: Path):
    (tmp_path / "t.vx").write_bytes(b"<root><item>x</item></root>\n")
    f = Scanner(tmp_path, ScannerConfig(enable_specialists=True)).scan().files[0]
    assert f.extension == ".vx"
    assert f.is_binary is False
    assert f.mime_type == "text/plain"
    ma = getattr(f, "mime_analysis", None)
    assert getattr(ma, "extension_mime", None) == "text/plain"   # the pin (was None at 1.46.1)


def test_version_axes():
    assert tuple(int(p) for p in SCANNER_VERSION.split(".")) >= (1, 46, 2)   # floor (v1.46.3 bumped SCANNER)
    assert tuple(int(p) for p in LOGIC_VERSION.split(".")) >= (1, 24, 2)   # LOGIC floor (unchanged at v1.46.3)
    assert SCHEMA_VERSION == "1.24"
