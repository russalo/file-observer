"""v1.4.0 — content-shape chatlog detection gate (falsify-first).

The count-based prose rule could not tell a recurring *data* label (Item:/Price:)
from a *speaker*. v1.4.0 adds a content-shape gate over the (retained, load-bearing)
stop-list + count floor: a turn must read like an *utterance* — it has a function
word, ends in sentence punctuation, is multi-word, or is long. This rejects cyclic
data tables / FAQs / changelogs / release-notes while admitting terse-but-real
dialogue (incl. RPG) via the function-word and punctuation arms.

These cases were written BEFORE/ALONGSIDE the implementation and validated against
the reference detector in scratch/review/v1_4_corpus.py. Synthetic/inline → CI-safe.
Two accepted FNs are asserted as FNs on purpose (ultra-terse contentless dialogue,
Q:/A:-labeled interview) so a future boundary move is deliberate, not accidental.
"""
import json
from pathlib import Path


from file_observer.scanner import (
    Scanner, ScannerConfig, SCHEMA_VERSION,
    CHATLOG_METHOD_VERSION,
)


def _detect(text: str) -> bool:
    return Scanner(Path("."), ScannerConfig())._detect_chatlog_pattern(text)


def _scan(tmp_path, name, content):
    (tmp_path / name).write_text(content)
    cfg = ScannerConfig(enable_specialists=True)
    return Scanner(source_dir=tmp_path, config=cfg).scan().files[0]


def _turns(seq):
    return "\n".join(f"{s}: {t}" for s, t in seq) + "\n"


class TestVersionSurfaces:
    def test_chatlog_method_version(self):
        # method_version moves when the chatlog producing-logic changes: 9 = v1.4
        # content-shape gate; 10 = v1.29.0 agentic turn recognition (tool turns
        # count in detection + signals); 11 = v1.34.0 session axes (first/last_timestamp
        # + cwd — new signals + recognized-key set/normalization feed the rules_hash).
        # (Global SCANNER/LOGIC/SCHEMA move each release; pinned in test_packaging.)
        assert CHATLOG_METHOD_VERSION == 11
        # content_shape present from schema 1.3 on (tuple compare — string ">=" breaks at 1.10)
        assert tuple(int(x) for x in SCHEMA_VERSION.split(".")) >= (1, 3)


class TestRejectsAtomicValueFP:
    """Content-shape rejects atomic-value blocks (utterance_ratio 0.0)."""

    def test_email_headers(self):
        assert _detect("From: a@x.com\nTo: b@x.com\nDate: Mon\nSubject: hi\nCc: t@x.com") is False

    def test_allcaps_headers(self):
        assert _detect("FROM: ALICE\nTO: BOB\nSUBJECT: URGENT\nDATE: TODAY\nCC: ALL") is False

    def test_cyclic_data_table(self):
        # The motivating FP: Item/Price recur (passes count floor) but values are
        # atomic — v1.2.4 false-positived, v1.4.0 rejects on content-shape.
        assert _detect(_turns([("Item", "Apple"), ("Price", "1.00"), ("Item", "Banana"),
                               ("Price", "2.00"), ("Item", "Cherry"), ("Price", "3.00")])) is False

    def test_cyclic_record(self):
        assert _detect(_turns([("Name", "John Smith"), ("Role", "admin"),
                               ("Name", "Jane Doe"), ("Role", "user")])) is False

    def test_cyclic_config(self):
        assert _detect(_turns([("Host", "localhost"), ("Port", "8080"),
                               ("Host", "example.com"), ("Port", "443")])) is False


class TestRejectsProseLabelFP:
    def test_changelog_lexicon_dominated(self):
        c = ("## [1.2.0] - 2026-01-01\n"
             "Added: support for the new export format across all backends\n"
             "Fixed: a crash when the cache was cold on the first request\n"
             "Changed: the default timeout is now thirty seconds\n")
        assert _detect(c) is False

    def test_release_notes_multi_version_structure_vote(self):
        # Non-lexicon labels (Feature/Bugfix) recur with sentence content; the
        # version-header structure vote-against is what rejects it.
        c = ("## [2.0.0] - 2026-03-01\n"
             "Feature: added a brand new export pipeline for all backends\n"
             "Bugfix: fixed a crash when the cache was cold on first request\n"
             "## [1.0.0] - 2026-01-01\n"
             "Feature: introduced the very first incremental scan for large trees\n"
             "Bugfix: corrected an off by one error in the page counter logic\n")
        assert _detect(c) is False

    # NOTE: recurring NON-lexicon labels sprinkled in prose (Aside:/Sidebar:) are
    # an ACCEPTED FP residual — the same recurring-prose-taxonomy family as
    # release-notes-without-headers and meeting-minutes (see
    # TestDocumentedResidualFPs). A density floor was prototyped to catch them but
    # review falsified it (it FN'd multi-line-turn dialogue at lower density than
    # the sprinkled prose it targeted), so it was dropped.


class TestFAQExclusion:
    def test_faq_question_answer_rejected(self):
        c = ("Question: How do I install this package on my system?\n"
             "Answer: Run pip install file-observer and you are done.\n"
             "Question: Where do the documentation files live?\n"
             "Answer: They are under the docs directory in the repo.\n")
        assert _detect(c) is False

    def test_faq_q_a_rejected(self):
        c = ("Q: How do I install this package on my own system?\n"
             "A: Run pip install file-observer and you are done.\n"
             "Q: Where do the documentation files live?\n"
             "A: They are under the docs directory at the top.\n")
        assert _detect(c) is False

    def test_a_b_anonymized_dialogue_survives(self):
        # {A, B}: B is not in the FAQ set, so the complete-set test does NOT fire.
        assert _detect(_turns([("A", "i think we should ship behind a flag first"),
                               ("B", "agreed that lowers the risk a lot"),
                               ("A", "exactly, we can ramp it slowly")])) is True


class TestAdmitsDialogue:
    def test_human_assistant(self):
        assert _detect(_turns([("Human", "what is the weather like today in seattle"),
                               ("Assistant", "it is rainy and about 55 degrees now"),
                               ("Human", "should i bring an umbrella with me")])) is True

    def test_terse_rpg_punctuation(self):
        # Sentinel use case: short turns, but sentence punctuation marks them as
        # utterances. The bias-fix case the first corpus missed.
        assert _detect("DM: The dragon roars.\nPlayer_2: I attack!\n"
                       "DM: Roll for it.\nPlayer_2: Natural twenty!\nDM: It hits.") is True

    def test_terse_function_words(self):
        # Short turns with function words ("there", "back", "now", "how are you").
        assert _detect("Alice: hi there friend\nBob: hello back\nAlice: goodbye now") is True

    def test_multiparty_recurring(self):
        assert _detect(_turns([("Alice", "welcome everyone to the project kickoff"),
                               ("Bob", "glad to be here and ready to start"),
                               ("Carol", "same here, lots of ground to cover"),
                               ("Alice", "lets begin with the timeline then")])) is True

    def test_json_embedded_dialogue_parity(self, tmp_path):
        c = json.dumps({"chosen": "\n\nHuman: how do i reverse a list in python\n\n"
                                  "Assistant: use the reversed builtin or a slice\n\n"
                                  "Human: which one is faster for large lists"})
        assert _scan(tmp_path, "hh.jsonl", c).is_chatlog is True

    def test_multiline_turn_dialogue(self):
        # Review regression guard: turns that wrap across multiple lines must still
        # detect (an earlier density floor wrongly rejected these as low-density).
        c = ("Alice: this is the opening line of a real conversational turn\n"
             "that wraps onto a second line and even a third line of content\n"
             "Bob: a reply that also spans more than one line because the\n"
             "speaker had quite a lot to say in response to the question\n"
             "Alice: and a final long turn that likewise spans several\n"
             "lines as people often do when they write at length\n")
        assert _detect(c) is True

    def test_dated_journal_dialogue(self):
        # Review regression guard: a dated journal of dialogue is a legitimate
        # chatlog — ISO-dated headers must NOT vote against it (only version tags do).
        c = ("## 2024-01-01 morning session\n"
             "Alice: how is the project going so far this week\n"
             "Bob: it is going really well thanks for asking\n"
             "## 2024-01-02 evening session\n"
             "Alice: any blockers i should know about today\n"
             "Bob: nothing major just some test flakiness\n")
        assert _detect(c) is True


class TestDocumentedFalseNegatives:
    """Accepted FNs — asserted so a boundary move is deliberate, not accidental."""

    def test_all_distinct_rollcall_missed(self):
        # Recurrence retained (Q3): 4 speakers each once → count floor rejects.
        assert _detect(_turns([("Alice", "welcome everyone to the kickoff today"),
                               ("Bob", "glad to be here and ready to help"),
                               ("Carol", "same here, lots to cover so lets go"),
                               ("Dave", "lets get started, i have a hard stop")])) is False

    def test_q_a_published_interview_missed(self):
        # The cost of FAQ exclusion (decision Q2): Q:/A:-labeled interview → FN.
        c = ("Q: How did you first get started in your career?\n"
             "A: I began by tinkering with computers as a teenager.\n"
             "Q: What advice would you give to someone starting today?\n"
             "A: Stay curious and never stop building real things.\n")
        assert _detect(c) is False

    def test_ultra_terse_contentless_missed(self):
        # Irreducibly ambiguous with atomic data (no function word / punctuation /
        # length). Real chat is substantive; this degenerate exchange is the FN.
        assert _detect("Human: hi\nAssistant: hello\nHuman: bye") is False

    def test_screenplay_label_on_own_line_no_markdown_missed(self):
        # Codex review: content-shape needs same-line content, so a label-on-own-
        # line prose transcript WITHOUT markdown structure is an accepted FN.
        # (With markdown headers, the structure rule still catches it — see
        # TestReviewRegressionGuards.test_label_on_own_line_keeps_structure_cosignal.)
        c = ("Alice:\nI think we should head north into the mountains today.\n"
             "Bob:\nThat sounds dangerous but I am willing to try it with you.\n"
             "Alice:\nGood, then let us prepare our gear before nightfall.\n")
        assert _detect(c) is False


class TestContentShapeSurfaced:
    """v1.4.0 (provisional): utterance_ratio + density in chatlog metadata."""

    def test_content_shape_present_in_prose_mode(self, tmp_path):
        c = _turns([("Human", "what is the weather like today in seattle"),
                    ("Assistant", "it is rainy and about 55 degrees now"),
                    ("Human", "should i bring an umbrella with me")])
        chat = _scan(tmp_path, "chat.txt", c).specialist_metadata["chatlog"]
        assert "content_shape" in chat
        assert chat["content_shape"]["utterance_ratio"] >= 0.6
        assert 0.0 <= chat["content_shape"]["density"] <= 1.0

    def test_content_shape_null_in_jsonl_mode(self, tmp_path):
        c = ('{"role": "user", "content": "how do I reverse a list in python"}\n'
             '{"role": "assistant", "content": "use the reversed builtin or a slice"}\n'
             '{"role": "user", "content": "which one is faster for large lists"}\n')
        chat = _scan(tmp_path, "chat.jsonl", c).specialist_metadata["chatlog"]
        # prose-label measures don't apply to JSON — the JSON path decides.
        assert chat["content_shape"] is None


class TestDocumentedResidualFPs:
    """Recurring non-lexicon prose taxonomies — structurally identical to dialogue.
    Accepted FP residual (the irreducible Key:value↔dialogue ambiguity). Pinned so
    a future boundary move is deliberate."""

    def test_release_notes_no_header(self):
        c = ("Feature: added a brand new export pipeline for all the backends\n"
             "Bugfix: fixed a crash when the cache was cold on the first request\n"
             "Feature: introduced a faster incremental scan for very large trees\n"
             "Enhancement: improved the throughput of the parser by a good margin\n")
        assert _detect(c) is True  # known residual FP

    def test_labels_sprinkled_in_prose(self):
        c = ("ordinary running prose paragraph one with several words here\n"
             "Aside: a fairly long parenthetical remark that recurs in the piece\n"
             "ordinary running prose paragraph two with several words here\n"
             "Sidebar: another reasonably long labelled aside that also recurs\n"
             "ordinary running prose paragraph three with several words here\n"
             "Aside: a second instance of the recurring aside label with content\n")
        assert _detect(c) is True  # known residual FP (density gate dropped, see scanner)


class TestReviewRegressionGuards:
    """Guards for the in-house multi-agent review findings (2026-06-02)."""

    def test_empty_label_does_not_swallow_next_line(self):
        # F1: the label regex must use horizontal whitespace [ \t]+, not \s+, so an
        # empty-content label ("A: \n") does NOT consume the next label line.
        ns = Scanner(Path("."), ScannerConfig())
        pairs = ns._label_content_pairs("A: \nB: \nA: \nB: ", drop_nonspeaker=True)
        assert pairs == [("A", ""), ("B", ""), ("A", ""), ("B", "")]

    def test_version_regex_ignores_bare_numbered_headings(self):
        # F3: bare 2-part numbered section headings (## 2.1) are NOT version tags
        # and must not trigger the structure vote-against.
        import file_observer.scanner as s
        assert s.CHATLOG_VERSION_HEADER_RE.findall("## 2.1\n## 2.2\n") == []
        assert len(s.CHATLOG_VERSION_HEADER_RE.findall("## [1.2.0]\n## v2.0\n## 1.2.3\n")) == 3

    def test_label_on_own_line_keeps_structure_cosignal(self):
        # Gemini + in-house: the markdown structure co-signal (Rule 2/3) must count
        # speaker labels even when the label is on its own line (`Alice:\nutterance`,
        # screenplay style) — it's a STRUCTURE rule, not a content-shape rule. The
        # content-requiring regex would lose the co-signal v1.3.0 had (FN regression).
        c = ("### Scene 1\nAlice:\nI think we should head north into the mountains.\n"
             "### Scene 2\nBob:\nThat sounds dangerous but I am willing to try it.\n"
             "### Scene 3\nAlice:\nGood, then let us prepare our gear tonight.\n"
             "### Scene 4\nBob:\nAgreed, I will gather the supplies we need.\n"
             "### Scene 5\nAlice:\nPerfect, we leave at first light tomorrow.\n")
        assert _detect(c) is True


class TestStaticTuningGuard:
    def test_static_tuning_matches_constants(self):
        # F10: the hand-maintained CHATLOG_STATIC_TUNING literals feed the vector
        # static_tuning_hash; they MUST equal the live constants the gate reads, or
        # a logic change could ship without changing the vector identity.
        import file_observer.scanner as s
        t = s.CHATLOG_STATIC_TUNING
        assert t["utterance_min_ratio"] == s.CHATLOG_UTTERANCE_MIN_RATIO
        assert t["utterance_min_words"] == s.CHATLOG_UTTERANCE_MIN_WORDS
        assert t["utterance_min_chars"] == s.CHATLOG_UTTERANCE_MIN_CHARS
        assert t["fp_lexicon_dominance"] == s.CHATLOG_FP_LEXICON_DOMINANCE
        assert t["structure_header_threshold"] == s.CHATLOG_STRUCTURE_HEADER_MIN
