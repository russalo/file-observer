"""v1.2.3 — FAQ false-positive stopgap.

Pro + flash both flagged that recurring `Question:`/`Answer:` labels (a FAQ doc)
satisfy the v1.2.2 prose rule (≥2 distinct, ≥3 total, ≥1 recurring) and
false-positive as a chatlog. v1.2.3 adds `Question`/`Answer` to the stop-list.

This is a STOPGAP for the most common single case — NOT the real fix. The root
issue (prose `Key:value` is ambiguous with dialogue) needs a non-count signal;
see scratch/review/v1_2_2_fp_findings.md. We deliberately do NOT stop-list single
letters like `Q`/`A` — `A:`/`B:` is a legitimate anonymized-dialogue pattern.

Falsify-first: the FAQ test FAILS on v1.2.2, passes after the stop-list add.
"""

from file_observer.scanner import Scanner, ScannerConfig


def _is_chatlog(tmp_path, name, content):
    (tmp_path / name).write_text(content)
    return Scanner(source_dir=tmp_path, config=ScannerConfig()).scan().files[0].is_chatlog


def test_faq_question_answer_not_flagged(tmp_path):
    c = ("Question: How do I install?\nAnswer: Use pip.\n"
         "Question: Where are the docs?\nAnswer: In docs/.\n")
    assert _is_chatlog(tmp_path, "FAQ.md", c) is False


def test_faq_allcaps_not_flagged(tmp_path):
    # case-sensitive stop-list + the label regex matches all-caps → ALL-CAPS FAQ
    # style needs explicit coverage (PR #30 review: flash/codex/copilot flagged it).
    c = ("QUESTION: How do I install?\nANSWER: Use pip.\n"
         "QUESTION: Where are the docs?\nANSWER: In docs/.\n")
    assert _is_chatlog(tmp_path, "FAQ.md", c) is False


def test_anonymized_ab_dialogue_still_detected(tmp_path):
    # `A:`/`B:` anonymized speakers are a LEGIT conversation — must stay detected
    # (guards against over-stop-listing single letters while fixing FAQ).
    c = "A: hey did you see this\nB: yeah just now\nA: what do you think\n"
    assert _is_chatlog(tmp_path, "dialogue.txt", c) is True
