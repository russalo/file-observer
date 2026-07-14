## Summary

What does this PR do? One to three bullet points.

-
-

## Type

- [ ] Bug fix
- [ ] New feature / enhancement
- [ ] Vector tuning (method_version bump)
- [ ] Documentation
- [ ] Refactor (no behavioral change)

## Checklist

- [ ] All tests pass (`python -m pytest tests/`)
- [ ] New tests added for new behavior
- [ ] No regressions in existing tests
- [ ] Determinism preserved (same input = same output)
- [ ] Correct version(s) bumped — `SCANNER` / `LOGIC` / `SCHEMA` (see CONVENTIONS §1)
- [ ] `docs/SCHEMA.md` + `docs/manifest.schema.json` regenerated if an output surface was added
- [ ] CLA: First-time contributors must comment on this PR: "I have read and agree to the Contributor License Agreement" (see [CLA.md](../CLA.md))

## Documentation sweep (every PR — not just feature PRs)

Documentation is part of the change, not an afterthought. Sweep every angle; check the ones that apply and note N/A for the rest:

- [ ] **Correctness** — every doc statement still matches the code (no claim the change made false; examples/CLI snippets still run).
- [ ] **Versions** — all version references current: README cells + example manifest, `docs/PUBLIC_CONTRACT.md` §3, `docs/CONVENTIONS.md` §1, `SECURITY.md` Supported Versions, the scanner docstring, GitHub Action pin. (`test_packaging.py` drift-guards catch some, not all.)
- [ ] **User-facing** — README, `docs/TUTORIAL.md`, and `examples/` reflect any new/changed CLI flag, tool param, or capability. A headline capability gets a runnable `examples/` entry + a tutorial section (+ its index rows).
- [ ] **Human-readable surfaces** — the per-scan `summary` (`_build_summary`) and `--schema --format summary` still name what a scan now observes (note: changing `_build_summary` moves `manifest_checksum` → LOGIC bump).
- [ ] **Contributions** — `CONTRIBUTING.md` / this template updated if the build, review, or release *process* changed.
- [ ] **Frozen vs live** — historical docs (RFCs, `COMPLIANCE-*`, `archive/`) left untouched; only live docs updated. `docs/HISTORY.md` gets the new row.
- [ ] **New-doc need** — does this introduce a mechanic deep enough to warrant its own doc (a dedicated guide / deep-dive), rather than a paragraph bolted onto an existing one? If yes, link it; if no, say why not.

## Schema impact

- [ ] No schema change
- [ ] Additive (new fields — MINOR version bump; `docs/SCHEMA.md` regenerated)
- [ ] Vector identity changed (method_version or tuning hash)

## Test evidence

How did you verify this works? Paste test output, scan results, or describe manual testing.
