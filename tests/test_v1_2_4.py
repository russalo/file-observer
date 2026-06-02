"""v1.2.4 — two clean wins from the in-house multi-agent recall review (PR #31).

The Claude multi-agent /code-review pass found two real issues the cross-model
(Gemini) reviews missed, both verified live:

  F9: the stop-list is case-sensitive, but the case-sensitivity fix was applied
      only to FAQ (Question/QUESTION) — ALL-CAPS email/usenet headers (FROM:/
      SUBJECT:) still false-positived. Fix: match the stop-list case-insensitively
      (also kills the dual-casing maintenance burden).
  F4: `_string_has_speaker_dialogue` (the embedded-JSON-string path) was never
      hardened — still `len(labels) >= 3` with no distinct/recurrence — so the same
      dialogue detected inside a JSON string was rejected as prose. Fix: apply the
      prose Rule 1 predicate (>=2 distinct, >=3 total, >=1 recurring).

Falsify-first: the two FP/asymmetry tests FAIL on v1.2.3, pass after the fix; the
guard tests must stay green throughout. See scratch/review/v1_2_2_fp_findings.md.
"""

import json
from file_observer.scanner import Scanner, ScannerConfig


def _is_chatlog(tmp_path, name, content):
    (tmp_path / name).write_text(content)
    return Scanner(source_dir=tmp_path, config=ScannerConfig()).scan().files[0].is_chatlog


class TestF9CaseInsensitiveStopList:
    def test_allcaps_email_headers_not_flagged(self, tmp_path):
        # ALL-CAPS recurring RFC822/usenet header dump — the FP class v1.2.2 targeted,
        # but only title-case From/Subject were stop-listed.
        c = "FROM: alice\nSUBJECT: re hi\nFROM: bob\nSUBJECT: re re hi\n"
        assert _is_chatlog(tmp_path, "thread.txt", c) is False

    def test_allcaps_faq_still_not_flagged(self, tmp_path):
        c = "QUESTION: how?\nANSWER: like so.\nQUESTION: and then?\nANSWER: done.\n"
        assert _is_chatlog(tmp_path, "FAQ.md", c) is False

    def test_user_still_a_legit_speaker(self, tmp_path):
        # `User` is intentionally NOT stop-listed; case-insensitive matching must
        # not start suppressing it.
        c = "User: hi there\nBob: hey\nUser: how are you\n"
        assert _is_chatlog(tmp_path, "chat.txt", c) is True


class TestF4EmbeddedDialogueParity:
    def test_embedded_json_dialogue_requires_recurrence(self, tmp_path):
        # 3 distinct one-shot speakers in a JSON string value: rejected as prose
        # (Rule 1), so must also be rejected here — no container-format asymmetry.
        c = json.dumps({"chosen": "Alice: hi\n\nBob: hello\n\nCarol: hey there friend"})
        assert _is_chatlog(tmp_path, "e.jsonl", c) is False

    def test_hh_rlhf_embedded_still_detected(self, tmp_path):
        # 2 distinct, recurring (Human x2) — a real embedded conversation, must stay.
        c = json.dumps({"chosen": "\n\nHuman: hi\n\nAssistant: hello\n\nHuman: bye"})
        assert _is_chatlog(tmp_path, "hh.jsonl", c) is True
