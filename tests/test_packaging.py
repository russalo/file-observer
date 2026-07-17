"""Packaging / import-surface tests (v1.0.1).

The package was renamed ``scanner`` -> ``file_observer`` in v1.0.1. The canonical
import path must work; the legacy ``scanner`` path must keep working but emit a
DeprecationWarning. The rename does not touch the manifest schema.
"""

import importlib
import re
import tomllib
import warnings
from pathlib import Path

import pytest


def test_version_surfaces_stay_in_sync():
    """Every place the version is written must equal SCANNER_VERSION — guards the
    drift that let pyproject / the module docstring lag the constant. (file_observer
    .__version__ is derived, so it's safe by construction; pyproject and the
    docstring are hand-maintained duplicates that need this check.)"""
    from file_observer.scanner import SCANNER_VERSION, SCHEMA_VERSION
    import file_observer.scanner as s

    root = Path(__file__).resolve().parent.parent
    pyproj = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert pyproj == SCANNER_VERSION, f"pyproject {pyproj} != SCANNER_VERSION {SCANNER_VERSION}"

    m = re.search(r"Version:\s*([0-9]+\.[0-9]+\.[0-9]+)", s.__doc__ or "")
    assert m, "scanner.py module docstring has no `Version:` line"
    assert m.group(1) == SCANNER_VERSION, f"docstring {m.group(1)} != SCANNER_VERSION {SCANNER_VERSION}"

    # v1.24: the docstring Schema + Spec lines drifted unguarded — pin them too.
    ms = re.search(r"Schema:\s*([0-9]+\.[0-9]+)", s.__doc__ or "")
    assert ms and ms.group(1) == SCHEMA_VERSION, f"docstring Schema {ms and ms.group(1)} != {SCHEMA_VERSION}"
    _maj, _min, _p = SCANNER_VERSION.split(".")
    assert f"docs/v{_maj}.{_min}.0_RFC_Specification.md (current)" in (s.__doc__ or ""), \
        "docstring Spec line must point at the current minor's RFC"


def test_readme_version_references_current():
    """README hand-maintains the current version in three spots and has drifted three
    minors running (caught reactively in #75/#78/#79). Guard them so a stale README
    fails CI instead of a bot. The historical RFC rows for PRIOR versions stay — this
    only pins the CURRENT-release claims to the constants."""
    from file_observer.scanner import SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION

    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text(encoding="utf-8")

    # (1) the example manifest shows the current scanner + logic versions
    assert f'"scanner_version": "{SCANNER_VERSION}"' in readme, \
        f"README example manifest scanner_version is stale (want {SCANNER_VERSION})"
    assert f'"logic_version": "{LOGIC_VERSION}"' in readme, \
        f"README example manifest logic_version is stale (want {LOGIC_VERSION})"
    # (2) the at-a-glance Version cell is current
    assert f"| **Version** | `{SCANNER_VERSION}` |" in readme, \
        f"README Version table cell is stale (want {SCANNER_VERSION})"
    # (3) the Documentation table links the current MINOR's RFC. RFCs are per-minor —
    # patches are HISTORY-only and reuse the minor's RFC (e.g. v1.15.1/.2 have no own RFC)
    # — so derive the link from major.minor.0, not the full version (leg-4 Codex P2).
    major, minor, _patch = SCANNER_VERSION.split(".")
    rfc_doc = f"docs/v{major}.{minor}.0_RFC_Specification.md"
    assert rfc_doc in readme, \
        f"README does not reference the current minor's RFC ({rfc_doc})"
    # (4) schema_version (example manifest) + the Schema quick-facts cell — drifted unguarded (v1.24)
    assert f'"schema_version": "{SCHEMA_VERSION}"' in readme, \
        f"README example manifest schema_version is stale (want {SCHEMA_VERSION})"
    assert f"| **Schema** | `{SCHEMA_VERSION}` |" in readme, \
        f"README Schema cell is stale (want {SCHEMA_VERSION})"


def test_all_extra_covers_every_runtime_extra():
    """v1.28.1: `[all]` is the one-line full-coverage install — the union of every RUNTIME
    extra. It self-references the others so it can't drift, but a NEW runtime extra added
    without wiring it into `[all]` would silently leave `[all]` incomplete. Guard it: every
    optional-dependency group except the meta-extras (`all`, `dev`) must be referenced by
    `[all]` (and, transitively, by `[dev]`, which references `[all]`)."""
    root = Path(__file__).resolve().parent.parent
    with open(root / "pyproject.toml", "rb") as f:
        extras = tomllib.load(f)["project"]["optional-dependencies"]
    runtime_extras = set(extras) - {"all", "dev"}
    # Parse the EXACT extra names referenced in the self-reference(s) `file-observer[a,b,c]`
    # — not a substring check (leg-4/gemini: a future name could be a substring of another).
    referenced = set()
    for spec in extras["all"]:
        for m in re.finditer(r"\[([^\]]+)\]", spec):
            referenced.update(ex.strip() for ex in m.group(1).split(","))
    missing = sorted(runtime_extras - referenced)
    assert not missing, f"[all] is missing runtime extras {missing} (add them to the all = [...] spec)"
    # dev = all runtime extras + test tooling — confirm it reaches `[all]`
    assert any("[all]" in d for d in extras["dev"]), "[dev] should reference [all] (DRY)"


def test_readme_lists_every_specialist_format():
    """The README's 'Supported specialist formats' list is hand-maintained and NOT
    version-stamped, so the version drift-guards above can't catch it — it silently
    froze at ~v1.0 until the post-v1.25 audit (missing HEIC/TIFF/JP2 images, video,
    audio, office/ODF, presentations). Guard it: every extension that routes to a
    specialist (`SPECIALIST_TOOLS`) MUST appear, backtick-wrapped, in the list — so a
    new specialist format that isn't documented fails CI instead of a reviewer/bot.
    (Prose specialist lists are an unguarded drift surface; this pins the README one.)"""
    from file_observer.scanner import SPECIALIST_TOOLS

    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text(encoding="utf-8")
    start = readme.index("Supported specialist formats:")
    # Bound the list at the NEXT markdown heading of any level (leg-4/gemini) — a
    # hardcoded "###" would silently over-capture if that heading became `##`/`####`,
    # masking real drift by pulling in backtick-formats from later sections.
    end_match = re.search(r"\n#{1,6} ", readme[start:])
    end = start + end_match.start() if end_match else len(readme)
    section = readme[start:end]
    # Match backtick-wrapped so `.ppt` is NOT satisfied by `.pptx` (nor `.doc` by `.docx`,
    # `.xls` by `.xlsx`, `.tif` by `.tiff`).
    missing = sorted(ext for ext in SPECIALIST_TOOLS if f"`{ext}`" not in section)
    assert not missing, (
        f"README 'Supported specialist formats' list is missing {missing} — add them "
        "when introducing a specialist (this list is not version-guarded)."
    )


def test_contract_docs_version_references_current():
    """The binding contract docs hand-maintain the current version and have drifted
    behind the build (PUBLIC_CONTRACT §3 history lagged 6 minors; surfaced by a
    consumer). Guard them so a stale contract doc fails CI instead of a consumer.
    Same disease/cure as test_readme_version_references_current."""
    from file_observer.scanner import SCANNER_VERSION

    root = Path(__file__).resolve().parent.parent
    contract = (root / "docs" / "PUBLIC_CONTRACT.md").read_text(encoding="utf-8")
    conventions = (root / "docs" / "CONVENTIONS.md").read_text(encoding="utf-8")

    # PUBLIC_CONTRACT §3 Schema Version History must carry a row for the current build
    assert f"| {SCANNER_VERSION} |" in contract, \
        f"PUBLIC_CONTRACT §3 history has no row for current SCANNER_VERSION {SCANNER_VERSION}"
    # CONVENTIONS §1.1 current-version stamp must match the constant
    assert f"**Current:** `{SCANNER_VERSION}`" in conventions, \
        f"CONVENTIONS §1.1 SCANNER current stamp is stale (want {SCANNER_VERSION})"
    # CONVENTIONS §1.6 Quick Reference table row must ALSO carry the current version
    # (leg-4/CodeRabbit v1.40: §1.6 drifted to 1.39.0 while §1.1 was current — this row
    # was unguarded; guard it so the two can't diverge again).
    assert f"`SCANNER_VERSION` | `MAJOR.MINOR.PATCH` | {SCANNER_VERSION} |" in conventions, \
        f"CONVENTIONS §1.6 Quick Reference SCANNER row is stale (want {SCANNER_VERSION})"


def test_canonical_top_level_api():
    """The documented public API imports from file_observer."""
    from file_observer import Scanner, ScannerConfig, manifest_to_json  # noqa: F401

    import file_observer
    from file_observer.scanner import SCANNER_VERSION

    assert file_observer.__version__ == SCANNER_VERSION
    assert "Scanner" in file_observer.__all__


def test_documented_serializers_are_exported():
    """README documents jsonl/markdown serializers as public API (PR #21 review)."""
    from file_observer import manifest_to_jsonl, manifest_to_markdown  # noqa: F401
    import file_observer

    assert "manifest_to_jsonl" in file_observer.__all__
    assert "manifest_to_markdown" in file_observer.__all__


def test_cli_version_flag():
    """v1.38.1 (#126): `--version`/`-V` prints `file-observer X.Y.Z` to stdout and exits 0 —
    un-breaks downstream version probing (recall's doctor read the usage banner)."""
    import subprocess
    import sys
    from file_observer.scanner import SCANNER_VERSION

    for flag in ("--version", "-V"):
        result = subprocess.run([sys.executable, "-m", "file_observer.scanner", flag],
                                capture_output=True, text=True)
        assert result.returncode == 0, f"{flag} exit {result.returncode}"
        assert result.stdout.strip() == f"file-observer {SCANNER_VERSION}", f"{flag} → {result.stdout!r}"


@pytest.mark.parametrize("module", ["file_observer.scanner", "scanner.scanner"])
def test_module_cli_entrypoint(module):
    """`python -m <module>` runs the CLI (guards the legacy shim regression)."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_canonical_submodule_constants_unchanged():
    """Constants and the manifest field they feed stay stable across the 1.0.x → 1.1 line (the 1.0.1 import-package rename left them intact)."""
    from file_observer.scanner import SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION

    assert SCANNER_VERSION == "1.46.6"
    assert SCHEMA_VERSION == "1.23"  # v1.46.6 — FROZEN (lexicon-index confinement; loader hardening, no manifest change). Prior 1.23 = v1.41.0 additive lexicon_match.metadata
    assert LOGIC_VERSION == "1.24.4"  # v1.46.6 — UNCHANGED (lexicon-index member confinement is a loader hardening; valid bundles byte-identical, the v1.43 loader-frozen precedent)


def test_legacy_scanner_import_warns():
    """Importing the legacy 'scanner' package works but is deprecated."""
    import sys

    # Force a fresh import so the module-level warning fires.
    sys.modules.pop("scanner", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        scanner = importlib.import_module("scanner")
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    # Shim re-exports the same public API object.
    from file_observer import Scanner

    assert scanner.Scanner is Scanner


def test_legacy_submodule_path_still_resolves():
    """`from scanner.scanner import Scanner` (old docs/tests) still works."""
    from scanner.scanner import Scanner as LegacyScanner
    from file_observer.scanner import Scanner as CanonicalScanner

    assert LegacyScanner is CanonicalScanner
