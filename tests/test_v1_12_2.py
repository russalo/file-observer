"""v1.12.2 — error-code centralization (hygiene patch, falsify-first).

Pure refactor: the two error codes that were emitted as inline string literals
(`xml_parse_failed`, `toml_parse_failed`) are now ERR_* module constants
alongside the others. Byte-identical manifest output — LOGIC + SCHEMA frozen.

Why it matters beyond hygiene: this is the de-risk patch ahead of the v1.13
`--schema` self-description minor. `--schema` introspects the code to enumerate
every error code; that introspection reads the ERR_* constants. Two codes
living as inline literals would be invisible to a constants-based read (a
careful agent source-read MISSED them exactly this way while building the
training-fixtures corpus 2026-06-08). Centralizing them — and guarding against
regression — makes the surface enumerable from one place.

The guard test (`test_no_inline_error_code_literals`) is the falsifiable
contract: it fails if anyone reintroduces an inline error-code literal.
"""
from __future__ import annotations

import ast
from pathlib import Path

from file_observer.scanner import (
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    ERR_XML_PARSE_FAILED,
    ERR_TOML_PARSE_FAILED,
)

SCANNER_PY = Path(__file__).resolve().parent.parent / "src" / "file_observer" / "scanner.py"


def test_new_error_code_constants_exist_with_expected_values():
    """The two centralized codes keep their on-the-wire string values (so the
    refactor is byte-identical — no manifest change)."""
    assert ERR_XML_PARSE_FAILED == "xml_parse_failed"
    assert ERR_TOML_PARSE_FAILED == "toml_parse_failed"


def test_no_inline_error_code_literals():
    """Guard (the v1.12.2 contract + a v1.13 --schema precondition): every
    ErrorRecord code MUST come from an ERR_* constant, never an inline string
    literal. This is what makes the error-code surface enumerable from one
    place. Fails if anyone writes `code="..."` or `ErrorRecord("...", ...)`
    with a literal instead of a constant.

    Uses AST inspection (not regex): only actual `ErrorRecord(...)` call nodes
    are examined, so the check is immune to false positives from comments /
    docstrings / unrelated calls and to formatting variation (PR #58 leg-4
    Gemini finding). The same AST pattern is reused for the v1.13
    provenance-trigger guard.
    """
    tree = ast.parse(SCANNER_PY.read_text(encoding="utf-8"), filename=str(SCANNER_PY))

    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ErrorRecord"):
            continue
        # Positional form: ErrorRecord("literal", ...) — code is the first arg
        if node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                offenders.append(f"positional code={first.value!r} (line {first.lineno})")
        # Keyword form: ErrorRecord(code="literal", ...)
        for kw in node.keywords:
            if kw.arg == "code" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                offenders.append(f"keyword code={kw.value.value!r} (line {kw.value.lineno})")

    assert offenders == [], (
        f"inline error-code string literal(s) found in scanner.py: {offenders!r} — "
        "every ErrorRecord code must use an ERR_* module constant (v1.12.2 contract; "
        "the v1.13 --schema work enumerates error codes from the constants)"
    )


def test_version_is_1_12_2():
    assert SCANNER_VERSION == "1.12.2", f"got {SCANNER_VERSION!r}"


def test_logic_and_schema_frozen():
    """Pure refactor — no observation-logic or schema change."""
    assert LOGIC_VERSION == "1.4.3", f"LOGIC drifted: {LOGIC_VERSION!r}"
    assert SCHEMA_VERSION == "1.8", f"SCHEMA drifted: {SCHEMA_VERSION!r}"
