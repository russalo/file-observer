"""v1.30.2 — ReDoS / bounded-TIME hardening guard.

file-observer's bounded-observation discipline caps input *size* (`baseline_max_bytes`,
default 64 KB, up to 1 MB in the deep profile). But a bounded-size input can still cost
unbounded *time* if a regex backtracks super-linearly — the class the v1.8.1 red-team
(size/crash/escape) and the capture-metadata hardening (parsers) never pointed at the
content regexes.

Three regexes were catastrophic on 64 KB of pathological (but legal, bounded) content:
  - CHATLOG_WIKI_LINK_RE  `\\[\\[.+?\\]\\]`            ~13 s   on 64 KB of `[[`
  - ASSET_RE              `!?\\[[^\\]]*\\]\\(([^)]+)\\)`  ~1.7 s  on 64 KB of `[`
  - PROVENANCE_VERSION_SUFFIX_RE `\\s+(v(er)?\\.?\\s*)?\\d.*$`  hung on 64 KB whitespace

This guard battery-tests EVERY compiled regex in the module against a pathological
character battery under a hard per-regex timeout — enforced in a child process so a
genuine regression fails loudly (naming the regex) instead of hanging the run. It is a
standing net: add a regex, it is covered automatically. See also the byte-for-byte
determinism/bounded discipline in test_v1_8_1.py and test_capture_metadata_hardening.py.
"""

from __future__ import annotations

import multiprocessing as mp
import re
import time

import pytest

import file_observer.scanner as scanner

# The battery: long runs of single chars and adjacent pairs that classically drive
# catastrophic backtracking (unmatched openers, whitespace-quantifier overlap, escapes).
_UNITS = [
    "[", "]", "(", ")", "{", "}", "<", ">", "#", "*", "-", "=", "\\", '"', "'",
    "[[", "]]", "](", ")(", "][", "\\#", "://", " ", "\t", "a", "a/", "https://a",
]
_SIZE = 65536              # the default baseline_max_bytes bound
_PER_REGEX_LIMIT_S = 5.0   # a linear regex finishes its own battery in << 1 s
_BATCH_LIMIT_S = 60.0      # all ~77 regexes, one child; all-linear runs in a few seconds


def _all_module_regexes() -> list[tuple[str, str, int]]:
    """EVERY compiled pattern reachable from the module's globals — module-level
    constants AND patterns nested in the (label, pattern) tables (TECHNOLOGY_PATTERNS,
    PROVENANCE_TOOLCHAIN_RULES, …). Walks generically (recurses list/tuple/set/dict) and
    dedupes by (pattern, flags), so a regex added to any table or a new table is covered
    automatically — NOT a hardcoded table list (leg-2/OpenAI review: the earlier hardcoded
    names didn't exist, so the tables — ~40 of the 77 regexes — were silently uncovered).
    Returns picklable (name, pattern, flags) triples."""
    seen: dict[tuple[str, int], str] = {}

    def walk(obj, label):
        if isinstance(obj, re.Pattern):
            seen.setdefault((obj.pattern, obj.flags), label)
        elif isinstance(obj, (list, tuple, set, frozenset)):
            for i, item in enumerate(obj):
                walk(item, f"{label}[{i}]")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(k, f"{label}<key>")
                walk(v, f"{label}[{k!r}]")

    for name in dir(scanner):
        if not name.startswith("__"):
            walk(getattr(scanner, name), name)
    return [(label, pattern, flags) for (pattern, flags), label in seen.items()]


def _hammer(pattern: str, flags: int) -> None:
    """Run the pattern over every pathological input at the size bound (child process)."""
    rx = re.compile(pattern, flags)
    for unit in _UNITS:
        text = (unit * (_SIZE // len(unit) + 1))[:_SIZE]
        rx.findall(text)


def _hammer_all(triples: list[tuple[str, str, int]]) -> None:
    """Run the whole battery over EVERY regex (child process)."""
    for _label, pattern, flags in triples:
        _hammer(pattern, flags)


def _completes_within(target, args, limit_s: float) -> bool:
    """True iff `target(*args)` finishes CLEANLY within `limit_s`. Runs in a child
    process so a hung (catastrophic) regex can be TERMINATED — the guard fails cleanly
    instead of hanging the suite (cross-platform; no SIGALRM dependency). A non-zero child
    exit (a raised exception, not a hang) also counts as a failure (leg-2/OpenAI review: a
    crashing regex must not read as 'fast enough')."""
    ctx = mp.get_context("spawn")  # spawn = identical on Linux/macOS/Windows
    proc = ctx.Process(target=target, args=args)
    proc.start()
    proc.join(limit_s)
    if proc.is_alive():
        proc.terminate()
        proc.join()
        return False
    return proc.exitcode == 0


def test_every_compiled_regex_is_linear_on_pathological_input():
    """No compiled regex may backtrack super-linearly on 64 KB of pathological content.

    Fast path: run the ENTIRE battery (all ~77 regexes) in ONE child — all-linear finishes
    in a few seconds (one interpreter spawn, not one per regex). Only if that child hangs
    or crashes do we re-run per-regex to NAME the offender(s), so the common (green) case
    stays cheap while a regression still fails with a precise culprit."""
    regexes = _all_module_regexes()
    if _completes_within(_hammer_all, (regexes,), _BATCH_LIMIT_S):
        return
    offenders = [
        label
        for (label, pattern, flags) in regexes
        if not _completes_within(_hammer, (pattern, flags), _PER_REGEX_LIMIT_S)
    ]
    assert not offenders, (
        f"regex(es) exceeded {_PER_REGEX_LIMIT_S}s on 64 KB of pathological input "
        f"(ReDoS / catastrophic backtracking): {offenders}"
    )


@pytest.mark.parametrize(
    "name, hostile_unit",
    [
        ("CHATLOG_WIKI_LINK_RE", "[["),
        ("ASSET_RE", "["),
        ("PROVENANCE_VERSION_SUFFIX_RE", " "),
    ],
)
def test_known_offenders_are_fast_in_process(name, hostile_unit):
    """Regression pins for the three v1.30.2 fixes: each must clear its own known-hostile
    64 KB input near-instantly in-process (they were seconds-to-minutes before)."""
    rx = getattr(scanner, name)
    text = (hostile_unit * (_SIZE // len(hostile_unit) + 1))[:_SIZE]
    start = time.perf_counter()
    rx.findall(text)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"{name} took {elapsed*1000:.0f} ms on 64 KB of {hostile_unit!r}"


def test_fixes_preserve_behavior_on_real_content():
    """The hardening must not change what fo observes on REAL content — only pathological
    (bracket-bearing / over-long / whitespace-flood) inputs may differ."""
    # Wiki links: real double-bracket links still counted.
    wiki = "see [[Page Name]] and [[Another_Page]] plus [[Third]]"
    assert len(scanner.CHATLOG_WIKI_LINK_RE.findall(wiki)) == 3

    # Markdown assets: image + relative-path links still extracted (http(s) skipped by
    # extract_assets, as before).
    md = "![alt](img/pic.png) and [t](https://x.com/y) and [rel](../a/b.md)"
    assert scanner.ASSET_RE.findall(md) == ["img/pic.png", "https://x.com/y", "../a/b.md"]

    # Producer version-suffix stripping: real strings normalize identically to pre-fix.
    for raw, expected in [
        ("doPDF Ver 7.2 Build 367 (Windows)", "doPDF"),
        ("Adobe PDF Library 15.0", "Adobe PDF Library"),
        ("Microsoft Word 2016", "Microsoft Word"),
        ("GPL Ghostscript 9.06", "GPL Ghostscript"),
        ("Acrobat Distiller 10.1.1 (Windows)", "Acrobat Distiller"),
        ("Word", "Word"),  # no version -> untouched
        ("   Adobe 3.0", "Adobe"),  # leading whitespace -> still stripped
    ]:
        assert scanner.PROVENANCE_VERSION_SUFFIX_RE.sub("", raw).strip() == expected
