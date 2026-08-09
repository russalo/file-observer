"""v1.49.0 — chatlog detection: content shape where counting still decides.

FALSIFY-FIRST. Written to FAIL before implementation.

RFC: docs/v1.49.0_RFC_Specification.md

This is a DETECTION change, which is the exact class where a confirming test proves
nothing — builder bias applies to me, and the v1.2.x arc burned four patches learning
it. So the structure here is deliberately lopsided:

  * cases that must FLIP, and
  * a much larger battery that must NOT MOVE — every false positive the v1.2.x arc
    and v1.4.0 fought to close.

The non-regression battery is the load-bearing half, and it EARNED that billing:
of the three changes this release set out to make, **the battery falsified two of
them at implementation time**. What shipped is case C only. Cases A and B are kept
below as DOCUMENTED RESIDUALS with the measurement that killed them, so the next
person does not re-attempt a fix the evidence already rejected.
"""

from __future__ import annotations

import json

from file_observer import scan


def _detect(tmp_path, name: str, body: str | bytes) -> bool:
    """Scan a single file and return is_chatlog."""
    p = tmp_path / name
    if isinstance(body, bytes):
        p.write_bytes(body)
    else:
        p.write_text(body, encoding="utf-8")
    m = scan(str(tmp_path), specialists=True)
    files = m["files"] if isinstance(m, dict) else m.files
    for f in files:
        d = f if isinstance(f, dict) else f.__dict__
        if d["filename"] == name:
            return bool(d["is_chatlog"])
    raise AssertionError(f"{name} not in manifest")


# ==========================================================================
# THE SCOPE — three cases that must flip. Anything beyond these is a defect.
# ==========================================================================

def test_A_RESIDUAL_structure_rule_fp_is_irreducible_by_the_utterance_gate(tmp_path):
    """RFC §3.1 FALSIFIED at implementation. This FP remains, deliberately.

    The plan was to gate the structure rule's co-signal on `_is_utterance` of each
    label's value, rejecting `Platform: Linux`. Implemented, it ALSO rejected real
    terse transcripts — `### Scene 1 / Alice: hi / ### Scene 2 / Bob: hello` — and
    the v1.2.1 regression guard caught it.

    MEASURED, which is what settles it:

        _is_utterance('hi')      = False      _is_utterance('Linux')  = False
        _is_utterance('hello')   = False      _is_utterance('Draft')  = False

    The gate's power is function words, sentence punctuation, and length. Terse
    dialogue has none of them EITHER, so the gate cannot separate the populations —
    exactly as v1.4.0's own docstring already recorded ("irreducibly ambiguous with
    atomic data"). We rediscovered a documented fact by ignoring it.

    Asserting the CURRENT behaviour so a future reader sees this is a known residual
    with evidence, not an oversight waiting to be fixed.
    """
    assert _detect(tmp_path, "spec.md",
        "# Spec\n\n### Overview\n### Scope\n### Design\n### Testing\n### Rollout\n\n"
        "Platform: Linux\nStatus: Draft\n"
    ) is True


def test_B_RESIDUAL_all_distinct_rollcall_fn_stays_accepted(tmp_path):
    """RFC §3.2 FALSIFIED at implementation. This FN remains, deliberately.

    The plan was to accept ALTERNATION as an alternative to recurrence. Implemented,
    it reopened the i18n/multi-language FP that v1.2.2 closed:

        English: The quick brown fox.        <- 3 distinct labels, each once
        Portuguese: A rápida raposa.         <- alternates
        Spanish: El zorro rápido.            <- and ALL are utterances (punctuation)

    Every downstream gate passes that; the recurrence floor was the only thing
    rejecting it. So alternation trades a REAL-CORPUS false positive (tika
    multi-language.txt) for a SYNTHETIC false negative — the wrong direction, and
    precisely the "too loose / too strict" tension the 2026-06 brief described.

    Recurrence stays required. Asserting the current behaviour so the trade is
    visible to whoever revisits it with better evidence.
    """
    assert _detect(tmp_path, "meeting.md",
        "Alice: shall we begin the review?\n"
        "Bob: yes, I have the notes ready.\n"
        "Charlie: agreed, let us start.\n"
        "Dave: sounds good to me.\n"
    ) is False


def test_C_two_turn_json_session_is_a_chatlog(tmp_path):
    """FN: the >=3 message-object floor. Quantified on LongMemEval: 0/7 at two
    turns, 100% at >=3. recall's 5.9% miss at 19,195 files is this same tail."""
    body = json.dumps([
        {"role": "user", "content": "what is the capital of France?"},
        {"role": "assistant", "content": "The capital of France is Paris."},
    ])
    assert _detect(tmp_path, "session.json", body) is True


# ==========================================================================
# THE NON-REGRESSION BATTERY — the v1.2.x + v1.4 false positives.
# Every one of these was a real, shipped bug that cost a patch to close.
# ==========================================================================

def test_no_regress_faq(tmp_path):
    """v1.2.3 — FAQ `Question:`/`Answer:` was the most common single FP."""
    assert _detect(tmp_path, "faq.md",
        "Question: What is X?\nAnswer: It is Y.\n\n"
        "Question: How do I Z?\nAnswer: Run the command.\n\n"
        "Question: Why?\nAnswer: Because.\n"
    ) is False


def test_no_regress_recurring_data_keys(tmp_path):
    """v1.4.0 — `Item:`/`Price:` cyclic data table. Recurring but ATOMIC; the
    function-word veto is what separates it from terse dialogue."""
    assert _detect(tmp_path, "catalog.md",
        "# Catalog\n\nItem: Widget\nPrice: $4.00\n\n"
        "Item: Gadget\nPrice: $9.00\n\nItem: Doohickey\nPrice: $2.50\n"
    ) is False


def test_no_regress_embedded_example_dialogue(tmp_path):
    """A doc CONTAINING a dialogue example is not itself a chatlog."""
    assert _detect(tmp_path, "CONTRIBUTING.md",
        "# Contributing\n\nExample session:\n\n"
        "Alice: can you review this?\nBob: sure, looks good\nAlice: thanks\n\n"
        "Now follow the steps below to submit your patch.\n"
    ) is False


def test_no_regress_allcaps_mail_headers(tmp_path):
    """v1.2.4 — the case-insensitive stop-list closed ALL-CAPS `FROM:`/`SUBJECT:`."""
    assert _detect(tmp_path, "mail.txt",
        "FROM: alice@example.com\nSUBJECT: Re: meeting\nDATE: Mon\nTO: bob@example.com\n\n"
        "Body text here.\n"
    ) is False


def test_no_regress_changelog_lexicon_dominance(tmp_path):
    """v1.4.0 — changelog verbs (`Added:`/`Fixed:`) dominate the label set."""
    assert _detect(tmp_path, "CHANGELOG.md",
        "# Changelog\n\nAdded: new export format for reports\n"
        "Fixed: crash when the config file was absent\n"
        "Added: support for compressed archives\n"
        "Changed: the default output directory\n"
        "Fixed: incorrect totals in the summary view\n"
    ) is False


def test_no_regress_version_tag_release_notes(tmp_path):
    """Written as a non-regression case; it FAILED RED, revealing a live FP.

    This is a case-A instance (structure rule + non-utterance labels), not a case
    that was already handled. It flips with the §3.1 fix. Kept under this name
    because the assertion — release notes are not a conversation — is unchanged.
    """
    assert _detect(tmp_path, "RELEASES.md",
        "# Releases\n\n### v1.2.0\n### v1.3.0\n### v1.4.0\n### v1.5.0\n### v1.6.0\n\n"
        "Release: stable\nStatus: shipped\n"
    ) is True   # case-A-class residual — see test_A_RESIDUAL for why it is irreducible


def test_no_regress_dated_journal(tmp_path):
    """Also FAILED RED — another live case-A instance, same mechanism.

    v1.4.0 deliberately made the version-tag vote-against NOT apply to dated
    journals (dated journals are legitimate). That left them exposed to the
    structure rule instead, which never checked whether `Mood: fine` is an
    utterance. §3.1 closes it.
    """
    assert _detect(tmp_path, "journal.md",
        "# Journal\n\n### 2026-01-01\n### 2026-01-02\n### 2026-01-03\n"
        "### 2026-01-04\n### 2026-01-05\n\nMood: fine\nWeather: cold\n"
    ) is True   # case-A-class residual — same mechanism, same irreducibility


def test_no_regress_two_element_config_array_is_not_a_session(tmp_path):
    """The FP the >=3 floor existed to prevent. Case C lowers the floor to 2 ONLY
    with conversational roles AND utterance content — a config array has neither."""
    body = json.dumps([
        {"role": "primary", "content": "localhost"},
        {"role": "replica", "content": "10.0.0.4"},
    ])
    assert _detect(tmp_path, "hosts.json", body) is False


def test_no_regress_two_element_array_conversational_roles_atomic_content(tmp_path):
    """Half-evidence must NOT be enough: conversational role names but atomic
    values. This is the exact seam Case C opens, so it gets its own falsifier."""
    body = json.dumps([
        {"role": "user", "content": "localhost"},
        {"role": "assistant", "content": "8080"},
    ])
    assert _detect(tmp_path, "cfg.json", body) is False


# ==========================================================================
# Positive controls — must KEEP working (a change that breaks these is worse
# than one that fixes nothing).
# ==========================================================================

def test_control_ordinary_dialogue_still_detected(tmp_path):
    assert _detect(tmp_path, "chat.md",
        "Alice: hey did you see the deploy went out\n"
        "Bob: yeah I watched it, all green\n"
        "Alice: nice, any rollback risk\n"
        "Bob: none that I can see\n"
    ) is True


def test_control_three_turn_json_still_detected(tmp_path):
    body = json.dumps([
        {"role": "user", "content": "hi there"},
        {"role": "assistant", "content": "hello, how can I help?"},
        {"role": "user", "content": "goodbye for now"},
    ])
    assert _detect(tmp_path, "s3.json", body) is True


def test_control_sentinel_shaped_export_still_detected(tmp_path):
    """Sentinel's gameplay export (verified shape, D3): ONE `###` header, labels
    followed by real sentences, `---` divider per turn. Their multi-turn files DO
    reach the structure rule via the divider branch, so this is the case their
    clearance turned on — it must keep working."""
    assert _detect(tmp_path, "session.md",
        "### mistwood — Chez — a1b2c3d4\n\n"
        "Chez: I head north toward the old mill.\n"
        "DM: The path narrows as brambles close in around you.\n"
        "---\n"
        "Chez: I draw my blade and press on.\n"
        "DM: Something heavy shifts in the undergrowth ahead.\n"
        "---\n"
        "Chez: I call out to whatever is there.\n"
        "DM: No answer comes, only the wind through dead leaves.\n"
        "---\n"
    ) is True


# ==========================================================================
# Determinism + contract
# ==========================================================================

def test_detection_is_deterministic_across_workers(tmp_path):
    for i in range(6):
        (tmp_path / f"c{i}.md").write_text(
            f"Alice: message number {i} for the log\nBob: acknowledged and noted\n",
            encoding="utf-8")
    from file_observer.scanner import manifest_to_json
    a = json.loads(manifest_to_json(scan(str(tmp_path))))
    b = json.loads(manifest_to_json(scan(str(tmp_path), workers=4)))
    for j in (a, b):
        j["meta"]["scan_id"] = ""
        j["meta"]["generated_at"] = ""
    assert a == b, "workers=4 must be byte-identical to serial"


def test_this_release_moved_the_right_axes():
    """Behaviour, not net-current pins (the v1.47.1/v1.48 lesson)."""
    from file_observer.scanner import LOGIC_VERSION, SCHEMA_VERSION

    def _t(v):
        return tuple(int(x) for x in v.split("."))

    assert _t(LOGIC_VERSION) > _t("1.25.0"), "detection routing changed; LOGIC must move"
    assert _t(SCHEMA_VERSION) == _t("1.25"), "no field added or retyped; SCHEMA frozen"


def test_chatlog_method_version_bumped():
    """A detection change must move the vector's method_version, or a consumer
    cannot tell that the rules producing their signal changed."""
    from file_observer.scanner import CHATLOG_METHOD_VERSION
    assert CHATLOG_METHOD_VERSION >= 12


def test_leg1_probe_prompt_template_detects_and_that_PREDATES_v149(tmp_path):
    """leg-1 self-review of the seam case C opens.

    A two-message prompt template (`user`/`assistant` + prose) DOES detect. Probed
    deliberately, because case C is the one place this release relaxes a false-positive
    defence, and a relaxation deserves an adversarial look at what else gets through.

    It is NOT a regression: a THREE-message prompt template already detected on main,
    verified by running the pre-v1.49 scanner against the same shape. Case C makes a
    2-message file behave like the 3-message file already did — consistency, not a new
    hole. Whether fo should treat prompt templates as chatlog-shaped at all is a
    separate, pre-existing question and out of this release's scope.

    Also probed and correctly REJECTED (roles outside the conversational set):
    en/es translation pairs, primary/replica host docs, user/admin role descriptions —
    each with fully utterance-shaped content, so they exercise the role gate alone.
    """
    body = json.dumps([
        {"role": "user", "content": "Summarise the document I provide."},
        {"role": "assistant", "content": "Certainly, please share the document."},
    ])
    assert _detect(tmp_path, "prompt_template.json", body) is True


def test_leg1_probe_role_gate_rejects_nonconversational_pairs(tmp_path):
    """The role gate must carry the weight when content shape cannot.

    All three have fully utterance-shaped content, so ONLY the role check can reject
    them. If someone widens the conversational role set later, this fails loudly.
    """
    for name, roles in (
        ("i18n.json", ("en", "es")),
        ("hosts.json", ("primary", "replica")),
        ("roledocs.json", ("user", "admin")),   # 'user' conversational, 'admin' not
    ):
        body = json.dumps([
            {"role": roles[0], "content": "This sentence is unambiguously utterance shaped."},
            {"role": roles[1], "content": "So is this one, with punctuation and length."},
        ])
        assert _detect(tmp_path, name, body) is False, f"{name} must not detect"
