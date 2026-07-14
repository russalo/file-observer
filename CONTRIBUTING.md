# Contributing to File Observer

We build tools that observe honestly, record deterministically, and never touch your files. If that resonates, you're in the right place.

## The short version

1. Fork, branch, code, test, PR
2. Sign the [CLA](CLA.md) on your first PR (one comment, one time)
3. All tests must pass. No exceptions.
4. Determinism is sacred. Same input = same output. Always.

---

## Before you write code

### Contributor License Agreement

File Observer is dual-licensed (AGPL-3.0 + commercial). The CLA lets us include your contribution in both. You keep full ownership of your code.

**How:** On your first PR, comment: *"I have read and agree to the Contributor License Agreement."* That's it. Once, forever.

[Read the full CLA](CLA.md)

### What belongs here

File Observer is an observation engine. It reads files and emits structured metadata. Contributions that fit:

- New file format support or specialist improvements
- New vectors or vector enhancements
- Detection accuracy improvements (bring evidence)
- Bug fixes with test cases
- Documentation improvements
- Test coverage

### What doesn't belong here

- File mutation, ingestion, transformation, or classification
- NLP, ML, or language model integration
- Features that break determinism
- Dependencies under non-permissive licenses

If you're unsure, open an issue first. We'd rather discuss scope before you invest time.

---

## Development setup

```bash
git clone https://github.com/russalo/file-observer.git
cd file-observer

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

# Verify everything works
python -m pytest tests/ -v
```

---

## Making changes

### Branch from main

```bash
git checkout -b your-feature
```

### Write tests first

Every behavioral change needs a test. No exceptions. The test suite is the contract — if it passes, the change is correct.

```bash
# Run the full suite
python -m pytest tests/ -v

# Run a specific test
python -m pytest tests/test_unit.py::TestClassName::test_name -v
```

### One concern per PR

Bug fix, feature, or refactor — pick one. Mixed PRs are harder to review and harder to revert.

### Keep determinism

The golden rule: **same input + same config = same output.** If your change could produce different output for the same input, it needs a `method_version` bump on the affected vector and a new identity digest.

### Bump the right version

File Observer tracks three versions independently: **`SCANNER_VERSION`** (the release), **`LOGIC_VERSION`** (routing/extraction *behavior* — anything that changes an observed value), **`SCHEMA_VERSION`** (the manifest *contract* — new fields/namespaces/vectors). If your change affects output, the right one(s) must bump. **Distinguish two cases:** a new *field / namespace / vector* is a manifest-shape change → MINOR + a **`SCHEMA_VERSION`** bump; a new *value* of an existing field (a provenance trigger, format signature, safety-flag value, error code) does **NOT** bump `SCHEMA_VERSION` — you still regenerate `docs/SCHEMA.md` (next section) so it reflects the value, but the contract shape is unchanged (e.g. v1.15.1 added `image/heif` to `format_signatures` with `SCHEMA_VERSION` unchanged). See **[CONVENTIONS.md §1](docs/CONVENTIONS.md)** for the which-bumps-when rules (a `test_packaging.py` guard keeps `SCANNER_VERSION` / `pyproject.toml` / the module docstring in sync — they can't silently drift).

### Documentation is part of every PR

Documentation ships **with** the change, not after it — don't make the reviewer chase drift. Every PR sweeps the same angles (the [PR template](.github/PULL_REQUEST_TEMPLATE.md) carries the checklist): **correctness** (no doc statement the change made false; snippets still run); **safety / positioning framing** (no wording that misleads on the safety boundary — fo observes-never-judges, `--trusted-only` is a projection not a sanitizer, the screener is not an AI, fo is not a watcher); **versions & quantitative claims** (every version reference + hardcoded count/benchmark current); **user-facing** (README / `docs/TUTORIAL.md` / `examples/` reflect any new or changed flag, param, or capability — a headline capability earns a runnable example + a tutorial section); **discoverability** (new content is linked from an index/nav, not orphaned); **links & anchors** (internal links and anchors resolve); **human-readable surfaces** (the per-scan `summary` and `--schema --format summary` still name what a scan observes); **contributions** (this guide / the template if the *process* changed); **frozen vs live** (leave RFCs/`archive/` alone; add the `docs/HISTORY.md` row); and **new-doc need** (a deep mechanic may warrant its own guide — link the canonical source, never a drift-prone copy).

**If you add any output surface** — a field, namespace, vector, safety flag, error code, provenance trigger, or format signature — you must (a) register it in the relevant registry, and (b) **regenerate both generated schema artifacts**:

```bash
python -m file_observer.scanner --schema --schema-format md          > docs/SCHEMA.md
python -m file_observer.scanner --schema --schema-format json-schema > docs/manifest.schema.json
```

Drift-guard tests (`test_committed_schema_md_matches_generated`, `test_committed_schema_matches_generated`) fail the build otherwise. Both are code-derived — never hand-edit them.

---

## PR checklist

Before submitting:

- [ ] All tests pass
- [ ] New tests added for new behavior
- [ ] No regressions in existing tests
- [ ] Determinism preserved
- [ ] Correct version(s) bumped (`SCANNER` / `LOGIC` / `SCHEMA` — see CONVENTIONS §1)
- [ ] `docs/SCHEMA.md` regenerated if you added an output surface
- [ ] Documentation swept — all angles above (correctness, safety/positioning framing, versions & quantitative claims, user-facing, discoverability, links & anchors, human-readable surfaces, contributions, frozen-vs-live, new-doc need)
- [ ] CLA signed (first-time contributors)

### Commit messages

```
Brief summary in imperative form (<70 chars)

Why this change is needed. What it does. Reference issue numbers.
```

---

## What happens after you submit

1. Automated checks verify tests pass
2. Bot review catches common issues
3. Maintainer reviews for scope, correctness, and alignment
4. You address feedback
5. Merge

We review promptly. If you don't hear back within a few days, ping us.

---

## Code conventions

- **Single module** — all logic in `src/file_observer/scanner.py`
- **Dataclasses** for all structured data
- **Signal provenance** on every derived field
- **Bounded observation** — specialists declare deviations explicitly
- **Errors are captured, never raised** — one bad file never halts a scan
- **Module-level constants** for regexes, extension sets, vector identity

---

## Reporting bugs

Open an issue with:
- File Observer version (check `SCANNER_VERSION` in `src/file_observer/scanner.py`)
- Python version and platform
- Steps to reproduce
- Expected vs actual behavior
- A minimal test file if possible

## Proposing features

Open an issue describing:
- What the feature does
- Why it belongs in File Observer (not in a downstream consumer)
- How it preserves determinism
- Schema impact (new fields? type changes?)

We'll discuss approach before implementation starts. **A new minor** (a new field / namespace / vector / specialist) gets a short design RFC in `docs/` (`docs/vX.Y.0_RFC_Specification.md`) agreed before code; **patches** (bug fixes, hardening) ship with a `HISTORY.md` entry only. New parsers carry the **bounded-observation / never-crash** mandate — cap every attacker-controlled length/count, degrade to an honest null, never raise out of a per-file scan.

---

## Questions?

Open an issue or email russalo@russalo.com.

We're glad you're here.
