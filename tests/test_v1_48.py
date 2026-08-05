"""v1.48.0 — download-origin observation (xattr / ADS).

Falsify-first. Written to FAIL before the implementation exists.

RFC: docs/v1.48.0_RFC_Specification.md

The load-bearing tests here are not the happy-path parses — they are:
  * §3.1  the allowlist boundary (a non-allowlisted attribute must NOT appear)
  * §3.2  shape: `origin` is always present, `null` when absent, never missing
  * §3.3  the URL is never surfaced, in any form
  * §3.6  `agent` is the only file_derived leaf and it nulls under --trusted-only
  * §3.7  hostile input degrades, never crashes
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from file_observer import scan
from file_observer.scanner import (
    FIELD_TRUST,
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    manifest_to_json,
)

# setfattr/getfattr only exist on Linux, and only on filesystems with xattr support.
_LINUX = sys.platform.startswith("linux")


def _can_set_xattr(tmp_path) -> bool:
    """True when this filesystem actually supports user xattrs (tmpfs often doesn't)."""
    if not _LINUX or not hasattr(os, "setxattr"):
        return False
    probe = tmp_path / ".xattr_probe"
    probe.write_text("x")
    try:
        os.setxattr(str(probe), "user.xdg.origin.url", b"https://example.invalid/probe")
        return True
    except OSError:
        return False
    finally:
        probe.unlink(missing_ok=True)


requires_xattr = pytest.mark.skipif(
    not _LINUX, reason="user-xattr write requires Linux (macOS/Windows covered by the CI matrix)"
)


def _json_rec(manifest, name: str) -> dict:
    """The record as it is actually SERIALISED — the surface a consumer sees.

    Necessary because a raw FileRecord.__dict__ still holds nested dataclasses, so
    json.dumps() on it raises; leak assertions must run against the real output.
    """
    doc = json.loads(manifest_to_json(manifest))
    for f in doc["files"]:
        if f["filename"] == name:
            return f
    raise AssertionError(f"{name} not in manifest")


def _rec(manifest, name: str) -> dict:
    files = manifest["files"] if isinstance(manifest, dict) else manifest.files
    for f in files:
        d = f if isinstance(f, dict) else f.__dict__
        if d["filename"] == name:
            return d
    raise AssertionError(f"{name} not in manifest")


# --------------------------------------------------------------------------
# §3.2 — shape. `origin` is ALWAYS present and `null` when nothing was read.
# --------------------------------------------------------------------------

def test_origin_key_is_always_present_even_with_no_marker(tmp_path):
    """Pillar 4: null means 'not observed'. The key must never be ABSENT.

    This reverses the RFC's first draft (§8 D5) — omitting the key would be fo's
    first conditionally-absent top-level field and would raise KeyError where every
    other field yields None.
    """
    (tmp_path / "plain.txt").write_text("no marker here")
    rec = _rec(scan(str(tmp_path)), "plain.txt")

    assert "origin" in rec, "origin must be present on every record, never omitted"
    assert rec["origin"] is None, "origin must be None when no marker was read"


def test_origin_survives_json_round_trip_as_null(tmp_path):
    (tmp_path / "plain.txt").write_text("x")
    m = scan(str(tmp_path))
    doc = json.loads(manifest_to_json(m if not isinstance(m, dict) else m))
    assert "origin" in doc["files"][0]
    assert doc["files"][0]["origin"] is None


# --------------------------------------------------------------------------
# §3.4 / §3.5 — Linux xdg presence, parsed correctly
# --------------------------------------------------------------------------

@requires_xattr
def test_xdg_origin_url_marks_downloaded_without_surfacing_the_url(tmp_path):
    """§3.3 — presence is surfaced, the URL never is."""
    if not _can_set_xattr(tmp_path):
        pytest.skip("filesystem does not support user xattrs")

    f = tmp_path / "fetched.bin"
    f.write_bytes(b"payload")
    secret = b"https://internal.example.invalid/SECRET-PATH?token=abc123"
    os.setxattr(str(f), "user.xdg.origin.url", secret)

    rec = _json_rec(scan(str(tmp_path)), "fetched.bin")
    origin = rec["origin"]

    assert origin is not None, "a marker was present; origin must not be None"
    assert origin["downloaded"] is True
    assert origin["source"] == "xdg_origin"

    # The URL must appear NOWHERE in the serialised record.
    blob = json.dumps(rec)
    assert b"SECRET-PATH".decode() not in blob, "the origin URL leaked into the manifest"
    assert "token=abc123" not in blob


@requires_xattr
def test_non_allowlisted_xattr_is_never_read(tmp_path):
    """§3.1 — the allowlist is the design. An arbitrary attribute must not appear."""
    if not _can_set_xattr(tmp_path):
        pytest.skip("filesystem does not support user xattrs")

    f = tmp_path / "tagged.txt"
    f.write_text("x")
    os.setxattr(str(f), "user.comment", b"PRIVATE-ANNOTATION-DO-NOT-SURFACE")

    rec = _json_rec(scan(str(tmp_path)), "tagged.txt")
    assert "PRIVATE-ANNOTATION-DO-NOT-SURFACE" not in json.dumps(rec)
    assert rec["origin"] is None, "user.comment is not an origin marker"


# --------------------------------------------------------------------------
# §3.5 — quarantine parsing (pure function; runs on every OS)
# --------------------------------------------------------------------------

def test_quarantine_parse_extracts_flag_agent_and_time():
    from file_observer.scanner import _parse_quarantine

    # flags;hex-epoch;agent;event-uuid  — a real macOS shape
    got = _parse_quarantine("0083;68a1b2c3;Google Chrome;ABCD1234-0000-0000-0000-00000000")
    assert got is not None
    assert got["downloaded"] is True
    assert got["agent"] == "Google Chrome"
    assert got["acquired_at"].startswith("20") and got["acquired_at"].endswith("Z")
    assert "ABCD1234" not in json.dumps(got), "the event UUID is machine-local; drop it"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        ";;;",
        "not-hex;not-hex;agent;uuid",
        "0083",
        "0083;68a1b2c3",
        "\x00\x00\x00",
        "0083;ffffffffffffffffffffff;agent;uuid",  # absurd timestamp
        "x" * 10_000,
    ],
)
def test_quarantine_parse_never_raises_on_malformed(bad):
    """§3.7 — malformed input degrades to None, never an exception."""
    from file_observer.scanner import _parse_quarantine

    assert _parse_quarantine(bad) is None or isinstance(_parse_quarantine(bad), dict)


# --------------------------------------------------------------------------
# §3.4 — Zone.Identifier parsing (pure function; runs on every OS)
# --------------------------------------------------------------------------

def test_zone_identifier_parse_maps_zone_and_drops_urls():
    from file_observer.scanner import _parse_zone_identifier

    got = _parse_zone_identifier(
        "[ZoneTransfer]\r\nZoneId=3\r\n"
        "ReferrerUrl=https://referrer.example.invalid/SECRET\r\n"
        "HostUrl=https://host.example.invalid/ALSO-SECRET\r\n"
    )
    assert got is not None
    assert got["zone"] == "internet"
    assert got["downloaded"] is True
    blob = json.dumps(got)
    assert "SECRET" not in blob, "§3.3 — Referrer/Host URLs must never be surfaced"


@pytest.mark.parametrize(
    "zid,expected",
    [("0", "local"), ("1", "intranet"), ("2", "trusted"), ("3", "internet"), ("4", "restricted")],
)
def test_zone_identifier_zone_mapping(zid, expected):
    from file_observer.scanner import _parse_zone_identifier

    got = _parse_zone_identifier(f"[ZoneTransfer]\nZoneId={zid}\n")
    assert got is not None and got["zone"] == expected


@pytest.mark.parametrize("bad", ["", "garbage", "[ZoneTransfer]", "[ZoneTransfer]\nZoneId=", "ZoneId=99"])
def test_zone_identifier_parse_never_raises(bad):
    from file_observer.scanner import _parse_zone_identifier

    out = _parse_zone_identifier(bad)
    assert out is None or isinstance(out, dict)


# --------------------------------------------------------------------------
# §3.7 — bounded & never-crash
# --------------------------------------------------------------------------

@requires_xattr
def test_huge_xattr_value_is_bounded_not_fatal(tmp_path):
    if not _can_set_xattr(tmp_path):
        pytest.skip("filesystem does not support user xattrs")
    f = tmp_path / "big.bin"
    f.write_bytes(b"x")
    try:
        os.setxattr(str(f), "user.xdg.origin.url", b"h" * 200_000)
    except OSError:
        pytest.skip("filesystem rejected an oversized xattr before fo could see it")

    rec = _json_rec(scan(str(tmp_path)), "big.bin")  # must not raise
    assert len(json.dumps(rec)) < 100_000, "an oversized attribute must be capped, not echoed"


def test_scan_of_tree_without_xattr_support_produces_no_error_records(tmp_path):
    """§3.7 — ENOTSUP/ENODATA is the NORMAL case and must be silent, not error spray."""
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x")
    m = scan(str(tmp_path))
    files = m["files"] if isinstance(m, dict) else m.files
    for f in files:
        d = f if isinstance(f, dict) else f.__dict__
        codes = [e.get("code") if isinstance(e, dict) else e.code for e in (d.get("errors") or [])]
        assert not any("origin" in str(c) or "xattr" in str(c) for c in codes), (
            f"absence of xattr support must be silent, got {codes}"
        )


# --------------------------------------------------------------------------
# §3.6 — trust classification and --trusted-only
# --------------------------------------------------------------------------

def test_origin_fields_are_trust_classified():
    """The v1.40 completeness guard should already force this, but assert intent."""
    keys = {k for k in FIELD_TRUST if "origin" in str(k)}
    assert keys, "origin must appear in FIELD_TRUST"


@requires_xattr
def test_trusted_only_nulls_agent_but_keeps_the_flag(tmp_path):
    """§3.6 — safe mode still learns the file came from outside, without the string."""
    if not _can_set_xattr(tmp_path):
        pytest.skip("filesystem does not support user xattrs")
    f = tmp_path / "dl.bin"
    f.write_bytes(b"x")
    os.setxattr(str(f), "user.xdg.origin.url", b"https://example.invalid/x")

    m = scan(str(tmp_path))
    safe = json.loads(manifest_to_json(m, trusted_only=True))
    # No `if origin is not None` guard: _can_set_xattr already succeeded, so the marker
    # IS present and origin MUST be populated. A guard here would let both assertions
    # skip silently on a regression — a test that cannot fail (leg-4).
    origin = safe["files"][0]["origin"]
    assert origin is not None, "the marker was set; safe mode must still carry the block"
    assert origin.get("agent") is None, "agent is file_derived; it must null in safe mode"
    assert origin.get("downloaded") is True, "downloaded is fo_derived; it must survive"
    assert origin.get("source") == "xdg_origin", "source is a closed enum; it must survive"


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------

@requires_xattr
def test_origin_is_deterministic_across_runs_and_workers(tmp_path):
    if not _can_set_xattr(tmp_path):
        pytest.skip("filesystem does not support user xattrs")
    for i in range(6):
        p = tmp_path / f"f{i}.bin"
        p.write_bytes(b"x" * (i + 1))
        if i % 2 == 0:
            os.setxattr(str(p), "user.xdg.origin.url", b"https://example.invalid/a")

    a = manifest_to_json(scan(str(tmp_path)))
    b = manifest_to_json(scan(str(tmp_path)))
    c = manifest_to_json(scan(str(tmp_path), workers=4))

    ja, jb, jc = (json.loads(x) for x in (a, b, c))
    for j in (ja, jb, jc):
        j["meta"]["scan_id"] = ""
        j["meta"]["generated_at"] = ""
    assert ja == jb, "two scans of identical state must agree"
    assert ja == jc, "workers=4 must be byte-identical to serial (the standing Layer-A gate)"


# --------------------------------------------------------------------------
# Version axes
# --------------------------------------------------------------------------

def test_this_release_moved_the_right_axes():
    """BEHAVIOUR, not net-current pins.

    The first cut of this asserted the literal "1.48.0"/"1.25.0"/"1.25" — the exact
    anti-pattern v1.47.1 removed 16 instances of, and which I ALSO fixed in test_v1_47
    during this same release before reintroducing it here. Caught by leg-4.

    A per-release file should assert what THIS release changed about the world, not
    what the current version numbers happen to be; the single net-current gate lives
    in test_packaging. So: assert the AXES MOVED relative to the release before, which
    stays true forever and needs no edit at the next bump.
    """
    def _t(v):  # "1.25.0" -> (1, 25, 0)
        return tuple(int(x) for x in v.split("."))

    # v1.48 is a new OBSERVATION: LOGIC must have moved past v1.47.1's 1.24.6 ...
    assert _t(LOGIC_VERSION) > _t("1.24.6"), "a new observation must move LOGIC"
    # ... and it adds a provisional FIELD, so SCHEMA must have moved past 1.24.
    assert _t(SCHEMA_VERSION) > _t("1.24"), "a new field is an additive contract change"
    assert _t(SCANNER_VERSION) > _t("1.47.1")


def test_cli_still_reports_version():
    out = subprocess.run(
        [sys.executable, "-m", "file_observer.scanner", "--version"],
        capture_output=True, text=True, timeout=60,
    )
    assert SCANNER_VERSION in (out.stdout + out.stderr)


# --------------------------------------------------------------------------
# leg-2 regressions (cross-model review, 2026-08-05) — two Major findings.
# Both fixes get a guard so the class cannot recur silently.
# --------------------------------------------------------------------------

@requires_xattr
def test_empty_attribute_counts_as_PRESENT_not_absent(tmp_path):
    """leg-2 #1: `if raw:` conflated b"" with absent → a false negative.

    The Linux path's entire semantic is PRESENCE, so a zero-length attribute is a
    marker: the file was annotated. Reproduced before fixing — an empty attr read as
    b'' and `bool(b'')` is False, so it was silently dropped.
    """
    if not _can_set_xattr(tmp_path):
        pytest.skip("filesystem does not support user xattrs")
    f = tmp_path / "empty_marker.bin"
    f.write_bytes(b"x")
    os.setxattr(str(f), "user.xdg.origin.url", b"")

    origin = _json_rec(scan(str(tmp_path)), "empty_marker.bin")["origin"]
    assert origin is not None, "an EMPTY attribute is still a PRESENT attribute"
    assert origin["downloaded"] is True
    assert origin["source"] == "xdg_origin"


def test_origin_read_never_uses_the_unbounded_xattr_api():
    """leg-2 #2: `os.getxattr(...)[:CAP]` allocates the WHOLE attribute first.

    The cap was cosmetic — a 64 KiB attribute on XFS/btrfs would be fully
    materialised before the slice could refuse it. The read now goes through libc
    with a bounded buffer on BOTH posix paths, and an oversized attribute returns
    ERANGE and is declined rather than truncated to a misleading prefix.

    Structural guard (the fo AST-guard pattern): assert the unbounded API does not
    appear in the origin read path, so a future edit can't quietly reintroduce it.
    """
    import inspect

    from file_observer import scanner as s

    full = inspect.getsource(s._read_origin_attr)
    # Strip the docstring: it deliberately NAMES os.getxattr to explain why the code
    # avoids it, and a naive text search trips on that explanation. Check the CODE.
    doc = s._read_origin_attr.__doc__ or ""
    src = full.replace(doc, "")
    assert "os.getxattr(" not in src, (
        "the origin read must not use os.getxattr — it allocates the entire attribute "
        "before any slice, making _ORIGIN_ATTR_MAX_BYTES cosmetic"
    )
    assert "create_string_buffer" in src, "the read must use a bounded ctypes buffer"
    # NOFOLLOW on both platforms — must not become a way around v1.8.1 containment.
    assert "lgetxattr" in src and "XATTR_NOFOLLOW" in src
