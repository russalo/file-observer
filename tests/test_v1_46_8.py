"""v1.46.8 (patch) — Windows reparse-prune gates on the NAME-SURROGATE tag bit, not the
bare reparse BIT (#169, validated on native NTFS by Tailnet).

`_should_prune_dir` pruned any directory whose `st_file_attributes` had
FILE_ATTRIBUTE_REPARSE_POINT set. That bit is a SUPERSET of junctions/dir-symlinks — it is
also set on OneDrive Files-On-Demand, Data-Dedup, and AppExecLink dirs, whose in-tree
subtree was then SILENTLY DROPPED from files[] with no ErrorRecord. The fix prunes only
NAME SURROGATES (junction / dir symlink — `st_reparse_tag & 0x20000000`, IsReparseTag-
NameSurrogate), so non-surrogate reparse dirs are descended (the file-level resolve()-
containment still catches any real escape).

These tests are PORTABLE: they monkeypatch `os.lstat` to return synthetic stat results, so
the Windows-only gate LOGIC is exercised on the Linux/macOS CI matrix too (the v1.46.0
lesson — a POSIX box lacks `st_file_attributes`/`st_reparse_tag`, so the real attribute must
be faked, never read from a real `os.lstat`). The end-to-end prune on real NTFS reparse
points is validated separately on the native-NTFS box (Tailnet).
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import file_observer.scanner as fo
from file_observer.scanner import (
    LOGIC_VERSION,
    SCANNER_VERSION,
    SCHEMA_VERSION,
    _NAME_SURROGATE_BIT,
    _REPARSE_ATTR,
    _should_prune_dir,
)

# Real tag values (from Tailnet's native-NTFS discrimination table).
TAG_MOUNT_POINT = 0xA0000003   # junction — name surrogate (0x20000000 set)
TAG_SYMLINK = 0xA000000C       # dir symlink — name surrogate
TAG_CLOUD = 0x9000001A         # OneDrive Files-On-Demand — NOT a surrogate
TAG_APPEXECLINK = 0x8000001B   # AppExecLink — NOT a surrogate (real on the box)
TAG_DEDUP = 0x80000013         # Data-Dedup — NOT a surrogate


def _fake_lstat(*, reparse: bool, tag: int = 0):
    attrs = _REPARSE_ATTR if reparse else 0
    return SimpleNamespace(st_file_attributes=attrs, st_reparse_tag=tag)


def _patch_lstat(monkeypatch, target, result_or_exc):
    """Intercept os.lstat ONLY for ``target`` (returning the synthetic result / raising the
    exception); delegate every other path to the real os.lstat so that ``path.resolve()``
    in the fallback (which lstat's ancestors) keeps working."""
    real = os.lstat
    tp = os.fspath(target)

    def fake(p, *a, **k):
        if os.fspath(p) == tp:
            if isinstance(result_or_exc, BaseException):
                raise result_or_exc
            return result_or_exc
        return real(p, *a, **k)

    monkeypatch.setattr(fo.os, "lstat", fake)


@pytest.mark.parametrize(
    "reparse,tag,expect_prune,label",
    [
        (False, 0, False, "normal dir → descend"),
        (True, TAG_MOUNT_POINT, True, "junction → prune (contained)"),
        (True, TAG_SYMLINK, True, "dir symlink → prune (contained)"),
        (True, TAG_CLOUD, False, "OneDrive Files-On-Demand → DESCEND (was wrongly pruned)"),
        (True, TAG_APPEXECLINK, False, "AppExecLink → DESCEND (was wrongly pruned)"),
        (True, TAG_DEDUP, False, "Data-Dedup → DESCEND (was wrongly pruned)"),
    ],
)
def test_prune_gates_on_name_surrogate(monkeypatch, tmp_path, reparse, tag, expect_prune, label):
    target = tmp_path / "d"
    _patch_lstat(monkeypatch, target, _fake_lstat(reparse=reparse, tag=tag))
    assert _should_prune_dir(target, tmp_path) is expect_prune, label


def test_bare_reparse_bit_would_have_over_pruned():
    """Falsify against the OLD behavior: the shipped bit-gate would prune the cloud dir; the
    surrogate gate must NOT. Proves the fix actually changes the non-surrogate outcome."""
    old_bit_gate = bool(_REPARSE_ATTR & _REPARSE_ATTR)   # a reparse dir always trips the old bit test
    assert old_bit_gate is True
    # new predicate on the same non-surrogate cloud tag:
    assert bool(TAG_CLOUD & _NAME_SURROGATE_BIT) is False
    # and the surrogate tags still trip it:
    assert bool(TAG_MOUNT_POINT & _NAME_SURROGATE_BIT) is True
    assert bool(TAG_SYMLINK & _NAME_SURROGATE_BIT) is True


def test_inconclusive_lstat_fails_closed_via_containment(monkeypatch, tmp_path):
    """If lstat raises (access-denied / TOCTOU), fall back to resolve()-containment and
    FAIL CLOSED — an out-of-tree resolution prunes, an in-tree one descends; the v1.46.0
    fallback is retained. (The `except (OSError, AttributeError)` branch is shared, so the
    OSError case exercises the same fallback a missing st_reparse_tag would hit.)"""
    # A dir that resolves OUTSIDE the root → prune (contained).
    outside = tmp_path.parent / "outside_the_tree"
    _patch_lstat(monkeypatch, outside, OSError("denied"))
    assert _should_prune_dir(outside, tmp_path) is True
    # A real in-tree dir → resolves inside → descend.
    inside = tmp_path / "sub"
    inside.mkdir()
    _patch_lstat(monkeypatch, inside, OSError("denied"))
    assert _should_prune_dir(inside, tmp_path) is False


def test_name_surrogate_bit_value():
    assert _NAME_SURROGATE_BIT == 0x20000000


def test_version_axes():
    assert SCANNER_VERSION == "1.47.0"
    assert LOGIC_VERSION == "1.24.6"   # Windows file-set change; Linux byte-identical (cross-platform-LOGIC)
    assert SCHEMA_VERSION == "1.24"    # FROZEN
