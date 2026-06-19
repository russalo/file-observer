"""v1.22.1 — `.eml` MIME-guard relaxation for libmagic-text typing (falsify-first).

Real `.eml` files whose body dominates (HTML mail, quirky leading headers) are typed by
libmagic as `text/plain` / `text/html`, NOT `message/rfc822`. The `email` MIME guard
(OLE2-shaped, for `.msg`) rejected those text MIMEs → the email specialist was SKIPPED
(`specialist_probe_failed`) on ~38% of real `.eml` in the corpus (8/9; subject/from/to/date
lost). This patch accepts `text/plain`/`text/html` for `.eml` SPECIFICALLY — `.msg` stays
OLE2-only, so a lying text-typed `.msg` remains distrusted. Same bug class + extension-gated
discipline as v1.15.2 (which fixed the no-libmagic/extension-fallback variant).

LOGIC 1.12.0→1.12.1 (extraction-dispatch change); SCANNER 1.22.0→1.22.1; SCHEMA unchanged.
"""
from __future__ import annotations

from pathlib import Path

from file_observer.scanner import (
    Scanner,
    ScannerConfig,
    SCANNER_VERSION,
    LOGIC_VERSION,
    SCHEMA_VERSION,
    SPECIALIST_MIME_GUARD,
    EXTENSION_EXTRA_GUARD_MIMES,
    ERR_SPECIALIST_PROBE_FAILED,
)

# an email whose leading X-/Delivered-To headers make libmagic type it text/plain
# (not message/rfc822) — the exact shape that was wrongly skipped pre-1.22.1.
QUIRKY_EML = (
    "X-Mailer: Custom 1.0\nDelivered-To: bob@example.com\nSubject: Quirky\n"
    "From: Alice <alice@example.com>\nTo: Bob <bob@example.com>\n"
    "Date: Mon, 06 Sep 2010 05:25:34 -0400\nMessage-ID: <q@example.com>\n\nbody text here\n"
)


def _scan_one(path: Path):
    m = Scanner(source_dir=path.parent, config=ScannerConfig(enable_specialists=True)).scan()
    return next(r for r in m.files if r.filename == path.name)


def _probe_failed(rec) -> bool:
    return any(e.code == ERR_SPECIALIST_PROBE_FAILED for e in (rec.errors or []))


def test_version_surfaces():
    assert SCANNER_VERSION == "1.22.1", f"got {SCANNER_VERSION!r}"
    assert LOGIC_VERSION == "1.12.1", f"LOGIC: {LOGIC_VERSION!r}"   # extraction-dispatch change
    assert SCHEMA_VERSION == "1.13", f"SCHEMA: {SCHEMA_VERSION!r}"  # unchanged


def test_body_dominated_eml_extracts(tmp_path):
    # An .eml with quirky leading headers + a plain body. However the LOCAL libmagic types it —
    # text/plain on Linux (the v1.22.1 fix path), message/rfc822 on another platform's magic DB, or
    # extension-fallback message/rfc822 with no libmagic (the v1.15.2 path) — the envelope MUST
    # extract. Assert the OUTCOME, not the platform-variant MIME (libmagic's DB differs across OSes,
    # the v1.22.0 lesson). The deterministic mechanism proof is test_guard_is_extension_specific.
    f = tmp_path / "quirky.eml"
    f.write_text(QUIRKY_EML)
    rec = _scan_one(f)
    em = (rec.specialist_metadata or {}).get("email", {})
    assert em.get("subject") == "Quirky", "a body-dominated .eml must extract its envelope"
    assert "alice@example.com" in (em.get("from") or "")
    assert not _probe_failed(rec), "the email specialist must not be skipped on a body-dominated .eml"


def test_msg_non_ole2_stays_distrusted(tmp_path):
    # a real .msg is OLE2; a text/misnamed .msg must NOT extract — the .eml relaxation must not leak
    # to .msg (the leg-2/Gemini lying-.msg HIGH). Holds on every path: libmagic-text → OLE2-guard
    # reject; no-libmagic → extension-fallback vnd.ms-outlook, unsigned, not in EXTENSION_TRUSTED_MIMES.
    f = tmp_path / "fake.msg"
    f.write_text("Subject: not a real msg\nFrom: x@y.com\n\njust text\n")
    rec = _scan_one(f)
    assert not (rec.specialist_metadata or {}).get("email"), "a non-OLE2 .msg must NOT extract"
    assert _probe_failed(rec), "a non-OLE2 .msg must stay distrusted (OLE2-only guard)"


def test_guard_is_extension_specific():
    """The fix mechanism, deterministic: the effective .eml guard accepts text; .msg does not."""
    base = SPECIALIST_MIME_GUARD["email"]
    eml_guard = base | EXTENSION_EXTRA_GUARD_MIMES.get(".eml", set())
    msg_guard = base | EXTENSION_EXTRA_GUARD_MIMES.get(".msg", set())
    assert {"text/plain", "text/html"} <= eml_guard, "the .eml guard must accept text MIMEs"
    assert not ({"text/plain", "text/html"} & msg_guard), "the .msg guard must NOT accept text MIMEs"


def test_message_rfc822_eml_still_works(tmp_path):
    # a tidy-header email libmagic types message/rfc822 — must still extract (no regression)
    f = tmp_path / "clean.eml"
    f.write_text(
        "From: Alice <alice@example.com>\nTo: Bob <bob@example.com>\nSubject: Lunch?\n"
        "Date: Fri, 11 Jul 2003 21:00:37 -0700\nMessage-ID: <c@example.com>\n\nbody\n"
    )
    rec = _scan_one(f)
    em = (rec.specialist_metadata or {}).get("email", {})
    assert em.get("subject") == "Lunch?" and not _probe_failed(rec)
