"""Packaging / import-surface tests (v1.0.1).

The package was renamed ``scanner`` -> ``file_observer`` in v1.0.1. The canonical
import path must work; the legacy ``scanner`` shim was REMOVED in v1.50.0 and must not
reappear. The rename does not touch the manifest schema.
"""

import importlib
import re
import tomllib
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
    from file_observer.scanner import SCANNER_VERSION, LOGIC_VERSION

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
    # §1.6 Quick Reference LOGIC_VERSION row — was unguarded, so a v1.46.7 bump left it
    # stale at 1.24.4 (caught by leg-4/CodeRabbit, not CI). Guard it so the LOGIC row can't
    # silently lag the constant either (the §1.2 "Current" prose carries a history
    # parenthetical that isn't cleanly machine-checkable; the quick-ref row is).
    assert f"`LOGIC_VERSION` | `MAJOR.MINOR.PATCH` | {LOGIC_VERSION} |" in conventions, \
        f"CONVENTIONS §1.6 Quick Reference LOGIC_VERSION row is stale (want {LOGIC_VERSION})"
    # §1.6 SCHEMA_VERSION quick-ref row — same class (was unguarded; a SCHEMA bump could leave it stale).
    from file_observer.scanner import SCHEMA_VERSION
    assert f"`SCHEMA_VERSION` | `MAJOR.MINOR` | {SCHEMA_VERSION} |" in conventions, \
        f"CONVENTIONS §1.6 Quick Reference SCHEMA_VERSION row is stale (want {SCHEMA_VERSION})"


def test_public_contract_stability_matches_registry():
    """OPERATIONALIZED GUARD for the error class that slipped at v1.47.0: PUBLIC_CONTRACT §2.4's
    provisional/stable PROSE drifted from the code registry — the promotion updated
    `PROVISIONAL_SPECIALIST_FIELDS` but §2.4 still called `presentation`/`audio` provisional (§2.4
    prose was unguarded; caught only by a hand polish pass). Guard both directions so it can't recur:
    a namespace that is FULLY STABLE in code must NOT sit in §2.4's provisional section, and a
    namespace WITH provisional fields MUST be documented there."""
    from file_observer.scanner import SPECIALIST_FIELDS, PROVISIONAL_SPECIALIST_FIELDS

    root = Path(__file__).resolve().parent.parent
    contract = (root / "docs" / "PUBLIC_CONTRACT.md").read_text(encoding="utf-8")
    # §2.4's provisional region = from the "subject to change" marker to the first promotion paragraph.
    start = contract.index("subject to change in MINOR releases without notice")
    end = contract.index("**Promoted to stable", start)
    prov_region = contract[start:end]
    for ns, fields in sorted(SPECIALIST_FIELDS.items()):
        has_provisional = any((ns, f) in PROVISIONAL_SPECIALIST_FIELDS for f in fields)
        in_prov_region = f"specialist_metadata.{ns}." in prov_region
        if not has_provisional:
            assert not in_prov_region, (
                f"PUBLIC_CONTRACT §2.4 lists `{ns}` as provisional, but EVERY field of `{ns}` is stable in "
                f"PROVISIONAL_SPECIALIST_FIELDS — a promotion updated the registry but not §2.4 (the v1.47.0 "
                f"presentation/audio class). Move `{ns}` to a 'Promoted to stable' paragraph.")
        else:
            assert in_prov_region, (
                f"`{ns}` has provisional fields in code but is not documented in PUBLIC_CONTRACT §2.4's "
                f"provisional section — a new provisional namespace must be listed there.")


def test_every_specialist_namespace_documented():
    """COMPLETENESS guard (hunt for what's MISSING): every namespace the scanner can EMIT must be
    documented in the CONTRACT BODY (§1–§2) — NOT merely mentioned in a §3 Schema-Version-History
    row (leg-4/CodeRabbit: a history-row mention is a changelog entry, not a durable contract
    statement, so it must not satisfy "documented")."""
    from file_observer.scanner import SPECIALIST_NAMESPACE, SPECIALIST_FIELDS

    root = Path(__file__).resolve().parent.parent
    contract = (root / "docs" / "PUBLIC_CONTRACT.md").read_text(encoding="utf-8")
    body = contract[: contract.index("## 3. Schema Version History")]   # exclude the §3 history rows
    namespaces = set(SPECIALIST_NAMESPACE.values()) | set(SPECIALIST_FIELDS)
    missing = sorted(ns for ns in namespaces
                     if f"specialist_metadata.{ns}" not in body and f"`{ns}`" not in body)
    assert not missing, f"specialist namespaces emitted but NOT documented in the PUBLIC_CONTRACT body (§1–§2): {missing}"


def test_security_supported_versions_current():
    """SECURITY.md's Supported Versions table is hand-maintained and was unguarded — it lagged to
    1.46.x while the build shipped 1.47.0 (caught by the polish pass). Guard it: the 'Yes (current)'
    row must name the current MAJOR.MINOR."""
    from file_observer.scanner import SCANNER_VERSION

    root = Path(__file__).resolve().parent.parent
    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    major_minor = ".".join(SCANNER_VERSION.split(".")[:2])
    assert f"| {major_minor}.x | Yes (current) |" in security, \
        f"SECURITY.md 'Yes (current)' row is stale (want {major_minor}.x)"


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


@pytest.mark.parametrize("module", ["file_observer.scanner"])
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
    """THE single net-current version gate — the ONLY test that pins SCANNER/LOGIC/SCHEMA to exact
    values, so a version bump updates exactly ONE place. (v1.47.1 removed the per-release
    `test_v1_XX::test_version_axes` duplication — 16 files that each pinned net-current and had to be
    sed'd every release. Do NOT reintroduce net-current exact pins in per-release test files; assert
    a release's BEHAVIOR there, not the live version constant.)"""
    from file_observer.scanner import SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION

    assert SCANNER_VERSION == "1.50.0"
    assert SCHEMA_VERSION == "1.25"   # 1.24->1.25 at v1.48.0 — the additive provisional `origin` field
    assert LOGIC_VERSION == "1.26.0"  # 1.25.0->1.26.0 at v1.49.0 — chatlog detection routing (the conditional JSON floor)


def test_legacy_scanner_shim_is_gone():
    """v1.50.0 REMOVED the deprecated `scanner` import shim (v1.0.1). The generic top-level
    name must no longer be installed by this package: an `import scanner` that resolves to
    fo would mean the shim crept back (or a stray `src/scanner/` reappeared)."""
    import sys
    sys.modules.pop("scanner", None)
    sys.modules.pop("scanner.scanner", None)
    try:
        mod = importlib.import_module("scanner")
    except ModuleNotFoundError:
        return  # the expected outcome
    # Some OTHER package named `scanner` may exist in the env; that's fine — but it must not be ours.
    assert "file_observer" not in (getattr(mod, "__file__", "") or ""), \
        "the deprecated `scanner` shim is being shipped again (removed in v1.50.0)"
    assert getattr(mod, "Scanner", None) is not importlib.import_module("file_observer").Scanner


# ---------------------------------------------------------------------------
# v1.50.0 — public-face guards. Each pins one thing a PyPI / GitHub reader meets
# BEFORE the first scan, so the classes found by the 2026-08-18 outsider audit can't
# silently recur.
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_RELATIVE_LINK = re.compile(r"\]\((?!https?://|mailto:|#)[^)\s]+\)")


def test_readme_has_no_relative_links():
    """PyPI renders the README verbatim — a relative link (`docs/TUTORIAL.md`) 404s on the
    project page. 48 of them did. Every link must be absolute (or an in-page anchor)."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    bad = _RELATIVE_LINK.findall(readme)
    assert not bad, f"README relative links (break on PyPI): {bad[:5]}"


def test_py_typed_marker_shipped():
    """`Typing :: Typed` is claimed in the classifiers → the PEP 561 marker must exist in the
    package AND be declared as package-data so it lands in the wheel (a bare file in src/
    is not enough for a non-editable install)."""
    import file_observer
    pkg_dir = Path(file_observer.__file__).resolve().parent
    assert (pkg_dir / "py.typed").exists(), "py.typed missing from the file_observer package"
    pyproj = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "Typing :: Typed" in pyproj["project"]["classifiers"]
    pkg_data = pyproj.get("tool", {}).get("setuptools", {}).get("package-data", {})
    assert "py.typed" in pkg_data.get("file_observer", []), \
        "py.typed must be listed under [tool.setuptools.package-data] to reach the wheel"


def test_license_metadata_is_spdx_and_license_file_is_verbatim_agpl():
    """GitHub's license detector + every license scanner keys on the LICENSE file being a
    recognised text. Ours is the verbatim AGPL-3.0 (sha256 of gnu.org's agpl-3.0.txt); the
    dual-licensing terms live in LICENSING.md. pyproject uses the PEP 639 SPDX expression,
    NOT the deprecated `License ::` classifier (setuptools>=77 rejects mixing them)."""
    import hashlib
    lic = (_ROOT / "LICENSE").read_bytes()
    assert hashlib.sha256(lic).hexdigest() == "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0", \
        "LICENSE is no longer the verbatim GNU AGPL-3.0 text (GitHub/scanners will stop detecting it)"
    assert lic.lstrip().startswith(b"GNU AFFERO GENERAL PUBLIC LICENSE")
    assert (_ROOT / "LICENSING.md").exists(), "the dual-licensing terms doc moved/vanished"
    pyproj = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert pyproj["license"] == "AGPL-3.0-or-later"
    assert "LICENSE" in pyproj["license-files"] and "LICENSING.md" in pyproj["license-files"]
    assert not any(c.startswith("License ::") for c in pyproj["classifiers"]), \
        "deprecated License:: classifier alongside an SPDX expression"


def test_ci_matrix_covers_every_claimed_python_version():
    """A `Programming Language :: Python :: 3.X` classifier is a promise; the CI matrix is
    the evidence. Every claimed minor must be tested somewhere in tests.yml."""
    pyproj = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    claimed = {c.rsplit("::", 1)[1].strip() for c in pyproj["classifiers"]
               if c.startswith("Programming Language :: Python :: 3.")}
    wf = (_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    tested = set(re.findall(r'"(3\.\d+)"', wf))
    missing = claimed - tested
    assert not missing, f"classifiers claim Python {sorted(missing)} but tests.yml never runs it"


def test_sdist_excludes_tests_tree():
    """setuptools' default sdist finder shipped tests/test_*.py WITHOUT tests/fixtures/ (18 MB)
    → an unrunnable test tree for downstream packagers. MANIFEST.in must prune it."""
    manifest_in = (_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert re.search(r"^prune tests\s*$", manifest_in, re.M), "MANIFEST.in must `prune tests`"


def test_python_dash_m_entry_point():
    """`python -m file_observer` must behave like the `file-observer` console script."""
    import subprocess, sys
    from file_observer.scanner import SCANNER_VERSION
    out = subprocess.run([sys.executable, "-m", "file_observer", "--version"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == f"file-observer {SCANNER_VERSION}"
