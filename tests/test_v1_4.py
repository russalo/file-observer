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

import pytest

from file_observer.scanner import (
    Scanner, ScannerConfig, SCANNER_VERSION, LOGIC_VERSION, SCHEMA_VERSION,
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
    def test_versions(self):
        assert SCANNER_VERSION == "1.4.0"
        assert LOGIC_VERSION == "1.3.0"
        assert SCHEMA_VERSION == "1.3"
        assert CHATLOG_METHOD_VERSION == 9


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

    def test_labels_sprinkled_in_prose_density(self):
        c = ("This is an ordinary article with several paragraphs of running prose that\n"
             "explains a topic in some depth before getting to any labelled asides.\n"
             "Aside: this is a fairly long parenthetical remark that recurs here.\n"
             "More ordinary running prose continues here for a sentence or two.\n"
             "Sidebar: another reasonably long labelled aside that also recurs.\n"
             "Yet more ordinary prose fills the space between the labelled asides.\n"
             "Aside: a second instance of the recurring aside label with content.\n"
             "And the article closes with one final paragraph of ordinary prose.\n")
        assert _detect(c) is False


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
