"""v1.8.1 — red-team hardening (regression guards for 6 confirmed findings).

A multi-agent red-team (construct + run real attacks against the live scanner, each
independently verified) found 6 ways to break the "never crash / stay bounded / be
deterministic / don't escape the tree" contract on UNTRUSTED input. This file guards
every fix. The DoS guards (#1–#3) assert the bounded/rejected post-fix behavior — the
pre-fix breaks (multi-GB RSS, multi-minute hangs) were reproduced + timed by the
red-team and can't be run safely in-process. The crash/escape guards (#4–#6) fail
against pre-fix code (verified).
"""
import os
import time
import zlib
from pathlib import Path

import pytest

from file_observer.scanner import Scanner, ScannerConfig


def _sc():
    return Scanner(source_dir=Path("."), config=ScannerConfig(enable_specialists=True))


def _scan(tmp_path):
    return Scanner(source_dir=tmp_path, config=ScannerConfig(enable_specialists=True)).scan()


def _xref_stream_pdf(*, w=(1, 2, 1), index=None, size=6, predictor=None, columns=None,
                     body=b"\x01\x00\x00\x00") -> bytes:
    """A minimal PDF whose startxref points at an xref STREAM with attacker-controlled
    /W, /Index, /Predictor, /Columns — the v1.8 tier-2 stdlib decoder's input."""
    comp = zlib.compress(body)
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    out += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    xoff = len(out)
    d = b"<< /Type /XRef /Size %d /Root 1 0 R /W [%d %d %d]" % (size, *w)
    if index is not None:
        d += b" /Index [" + b" ".join(b"%d" % n for n in index) + b"]"
    d += b" /Filter /FlateDecode"
    if predictor is not None:
        d += b" /DecodeParms << /Predictor %d /Columns %d >>" % (predictor, columns or 1)
    d += b" /Length %d >>" % len(comp)
    out += b"5 0 obj\n" + d + b"\nstream\n" + comp + b"\nendstream\nendobj\n"
    out += b"startxref\n%d\n%%%%EOF" % xoff
    return bytes(out)


class TestPdfDecoderDoS:
    """#1/#2/#3 — the v1.8 stdlib decoder must reject malformed xref streams that
    drove unbounded memory/CPU, returning None (bounded), never allocating/looping."""

    def test_columns_memory_bomb_rejected(self):
        # #1: /Columns far larger than the inflated stream → reject (a row can't be
        # wider than the stream). Pre-fix: bytearray(8e9) → ~7.85 GB RSS.
        assert _sc()._png_predictor_undo(b"\x00" * 16, columns=8_000_000_000, predictor=12) is None
        pdf = _xref_stream_pdf(predictor=12, columns=8_000_000_000)
        t = time.monotonic()
        assert _sc()._pdf_via_stdlib(Path("/nonexistent"), pdf) is None
        assert time.monotonic() - t < 5            # bounded, no giant alloc

    def test_columns_zero_rejected(self):
        # #3: /Columns 0 → stride 1, a per-byte loop over the whole 64 MB stream.
        assert _sc()._png_predictor_undo(b"\x00" * 1024, columns=0, predictor=12) is None

    def test_zero_width_xref_no_hang(self):
        # #2: /W [0 0 0] → ew=0 → the entry loop never advances and runs the full
        # attacker /Index count. Pre-fix: minutes-to-hours hang. Must return fast.
        pdf = _xref_stream_pdf(w=(0, 0, 0), index=[0, 100_000_000])
        t = time.monotonic()
        assert _sc()._pdf_via_stdlib(Path("/nonexistent"), pdf) is None
        assert time.monotonic() - t < 5            # no unbounded loop


@pytest.mark.posix_fs  # >MAX_PATH names + chmod-000 can't be set up on Windows; never-crash covered cross-platform by test_v1_15.TestPathEdges
class TestNeverCrashesScan:
    """#4/#5 — a single pathological file must NOT abort the whole scan; it degrades
    to a FileRecord (with an ErrorRecord) and the manifest still emits."""

    def test_max_length_filename_does_not_crash(self, tmp_path):
        # #4: a 251-byte name + extension → sidecar candidate exceeds 255 → OSError.
        (tmp_path / ("a" * 251 + ".txt")).write_text("hi")
        (tmp_path / "sibling.txt").write_text("ok")
        m = _scan(tmp_path)                          # must NOT raise
        assert len(m.files) >= 2                     # the long-named file + its sibling

    def test_unreadable_file_does_not_crash(self, tmp_path):
        # #5: a chmod-000 file → bare open() raised PermissionError out of scan().
        p = tmp_path / "locked.txt"
        p.write_text("secret")
        os.chmod(p, 0o000)
        try:
            m = _scan(tmp_path)                       # must NOT raise
            assert any(f.path.endswith("locked.txt") for f in m.files)
            rec = [f for f in m.files if f.path.endswith("locked.txt")][0]
            assert rec.errors                         # degraded to an ErrorRecord
        finally:
            os.chmod(p, 0o644)                        # let tmp cleanup remove it


@pytest.mark.posix_fs  # 250-255-byte filenames exceed Windows MAX_PATH at creation
class TestSidecarPerCandidate:
    """PR review (#4 refinement) — guarding each sidecar candidate independently
    must not let one over-long candidate hide a valid shorter sidecar that exists."""

    def test_overlong_first_candidate_does_not_hide_real_sidecar(self, tmp_path):
        # base name chosen so candidate[0] (base + ".json", +5 bytes) overruns the
        # 255-byte limit (→ OSError) while candidate[2] (stem + ".json") fits + exists.
        base = "a" * 250 + ".x"            # 252 bytes
        (tmp_path / base).write_text("doc")
        sidecar = tmp_path / ("a" * 250 + ".json")   # 255 bytes — the stem-based candidate
        sidecar.write_text("{}")
        assert _sc().detect_sidecar(tmp_path / base) is True   # pre-fix: OSError on cand[0] → False


@pytest.mark.posix_fs  # symlink creation needs privilege/developer-mode on Windows
class TestNoTreeEscape:
    """#6 — a symlink pointing OUTSIDE the scan tree must not be read into the
    manifest (and an in-tree file is still scanned)."""

    def test_symlink_out_of_tree_not_followed(self, tmp_path):
        outside = tmp_path.parent / f"rt_outside_{tmp_path.name}.txt"
        outside.write_text("SECRET-OUTSIDE-THE-TREE")
        try:
            try:
                (tmp_path / "escape.txt").symlink_to(outside)
            except (OSError, NotImplementedError):
                pytest.skip("symlinks unsupported here (Windows w/o privilege)")
            (tmp_path / "real.txt").write_text("in-tree")
            m = _scan(tmp_path)
            paths = {f.path for f in m.files}
            assert "real.txt" in paths                # in-tree file still scanned
            # the escaping symlink must not surface the outside file's content/size
            esc = [f for f in m.files if f.path.endswith("escape.txt")]
            assert all(f.size_bytes != len("SECRET-OUTSIDE-THE-TREE") for f in esc), \
                "out-of-tree symlink target was read into the manifest"
        finally:
            outside.unlink(missing_ok=True)
