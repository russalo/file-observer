# Contributing to File Observer

Thank you for your interest in contributing to File Observer. This document covers the process, expectations, and legal requirements for contributions.

## Before you contribute

### Contributor License Agreement (CLA)

File Observer is dual-licensed under AGPL-3.0 and a commercial license. To maintain the ability to offer both licenses, **all contributors must sign a CLA before their first contribution can be merged.**

The CLA grants Russalo LLC a non-exclusive, perpetual, worldwide license to use your contributions under any license — including the commercial license. You retain full copyright ownership of your contributions.

**What this means:**
- You still own your code
- Your contribution will always be available under AGPL-3.0
- Russalo LLC can also include it in the commercially-licensed version
- Without the CLA, we cannot merge your contribution

**How to sign:**
1. Read the CLA at [`CLA.md`](CLA.md)
2. On your first PR, add a comment: "I have read and agree to the Contributor License Agreement"
3. That's it — one-time, applies to all future contributions

### Scope

File Observer is an observation-only file metadata engine. Contributions should align with this scope:
- New file format support or specialist improvements
- Vector enhancements or new vectors
- Detection accuracy improvements (with evidence)
- Bug fixes
- Documentation improvements
- Test coverage

Out of scope:
- File mutation, ingestion, or transformation
- NLP, ML, or language model integration
- Features that break determinism
- Dependencies that are not permissively licensed (MIT, BSD, Apache, PSFL)

---

## Development setup

```bash
git clone https://github.com/russalo/file-observer.git
cd file-observer

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

## Running tests

```bash
# Full suite
python -m pytest tests/ -v

# Single test
python -m pytest tests/test_unit.py::TestClassName::test_name -v
```

All tests must pass before a PR will be reviewed.

---

## How to contribute

### Bug reports

Open an issue with:
- File Observer version (check `SCANNER_VERSION` in `src/scanner/scanner.py`)
- Python version
- Platform
- Steps to reproduce
- Expected vs actual behavior
- If possible, a minimal test file that triggers the bug

### Feature proposals

Open an issue describing:
- What the feature does
- Why it belongs in File Observer (not in a downstream consumer)
- How it preserves determinism
- Whether it's a new vector, a new specialist, or a modification to existing behavior

We'll discuss scope and approach before you write code.

### Pull requests

1. Fork the repository
2. Create a branch from `main` (`git checkout -b your-feature`)
3. Make your changes
4. Add tests for any new behavior
5. Run the full test suite
6. Commit with clear messages
7. Open a PR against `main`

### PR expectations

- **Tests required.** No behavioral change without tests.
- **One concern per PR.** Bug fix, feature, or refactor — not all three.
- **Spec alignment.** If your change affects the manifest schema, reference the relevant RFC section or propose a spec update.
- **No regressions.** All existing tests must pass.
- **Determinism preserved.** Same input + same config = same output. Always.

### Commit messages

```
Brief summary (imperative, <70 chars)

Why this change is needed. What it does. Reference issue numbers
if applicable.
```

---

## Code conventions

- Single module: all scanner logic in `src/scanner/scanner.py`
- Module-level constants for regexes, extension sets, vector identity
- Dataclasses for all structured data
- Signal provenance on every derived field
- Bounded observation: specialists declare deviations explicitly
- No global state, no side effects in scan methods
- Errors are captured, never raised — one bad file never halts a scan

## Documentation conventions

- RFC specs in `docs/v{X}.0_RFC_Specification.md`
- Compliance reports in `docs/COMPLIANCE-v{X}.md`
- Version history in `docs/HISTORY.md`
- Consumer contract in `docs/PUBLIC_CONTRACT.md`
- Internal conventions in `docs/CONVENTIONS.md`

When your change affects documented behavior, update the relevant docs in the same PR.

---

## Review process

1. PR is submitted with CLA acknowledgment
2. Automated checks: tests pass, no merge conflicts
3. Bot review (Copilot/Codex) for common issues
4. Maintainer review for scope, correctness, and alignment
5. Feedback addressed
6. Merge

Typical turnaround: days, not weeks. We review promptly.

---

## Questions?

Open an issue or email russalo@russalo.com.
