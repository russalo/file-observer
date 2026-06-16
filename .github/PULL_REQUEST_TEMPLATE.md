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
- [ ] `docs/SCHEMA.md` regenerated if an output surface was added (`--schema --schema-format md`)
- [ ] Documentation updated if behavior changed
- [ ] CLA: First-time contributors must comment on this PR: "I have read and agree to the Contributor License Agreement" (see [CLA.md](CLA.md))

## Schema impact

- [ ] No schema change
- [ ] Additive (new fields — MINOR version bump; `docs/SCHEMA.md` regenerated)
- [ ] Vector identity changed (method_version or tuning hash)

## Test evidence

How did you verify this works? Paste test output, scan results, or describe manual testing.
