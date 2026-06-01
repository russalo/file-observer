"""v1.2.1 — false-positive corpus + determinism property test.

Written FIRST (falsify-before-fix). On v1.2.0 the two FP tests FAIL — they
reproduce the shipped regression (CHANGELOG.md and structured JSONL logs
mis-detected as chatlogs). The fix makes them pass. See scratch/critical_review.md
and [[feedback_falsify_dont_confirm]].
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from file_observer.scanner import Scanner, ScannerConfig, manifest_to_json


def _is_chatlog(tmp_path, name, content):
    (tmp_path / name).write_text(content)
    return Scanner(source_dir=tmp_path, config=ScannerConfig()).scan().files[0].is_chatlog


class TestFalsePositiveCorpus:
    """Common-but-not-conversational files MUST NOT be flagged as chatlogs."""

    def test_changelog_not_flagged(self, tmp_path):
        # Dated headers + dividers, no speakers — a changelog/release-notes.
        c = "\n".join(f"## 2026-0{i}-15\n- fixed bug {i}\n- added feature {i}\n---"
                      for i in range(1, 6))
        assert _is_chatlog(tmp_path, "CHANGELOG.md", c) is False

    def test_dated_journal_without_speakers_not_flagged(self, tmp_path):
        c = ("# 2026-01-01\nWorked on the parser.\n---\n"
             "# 2026-01-02\nFixed the bug.\n---\n# 2026-01-03\nShipped.\n---\n")
        assert _is_chatlog(tmp_path, "journal.md", c) is False

    def test_structured_jsonl_log_not_flagged(self, tmp_path):
        # type + message per line — the output of most logging libraries.
        c = "\n".join(json.dumps({"timestamp": f"t{i}", "type": "info",
                                  "message": f"request {i} ok"}) for i in range(6))
        assert _is_chatlog(tmp_path, "app.jsonl", c) is False

    def test_single_role_jsonl_not_flagged(self, tmp_path):
        # All same role value → not a conversation (no alternation).
        c = "\n".join(json.dumps({"role": "system", "content": f"event {i}"})
                      for i in range(6))
        assert _is_chatlog(tmp_path, "events.jsonl", c) is False

    def test_mixed_level_log_not_flagged(self, tmp_path):
        # type=info/error/warn are LOG LEVELS, not speakers — must not pass the
        # distinct-speaker gate just because the level varies (PR #28 review).
        levels = ["info", "error", "warn", "info", "error", "debug"]
        c = "\n".join(json.dumps({"timestamp": f"t{i}", "type": lv, "message": f"event {i}"})
                      for i, lv in enumerate(levels))
        assert _is_chatlog(tmp_path, "app.jsonl", c) is False

    def test_config_json_not_flagged(self, tmp_path):
        c = json.dumps({"name": "pkg", "version": "1.0",
                        "scripts": {"build": "tsc", "test": "pytest"}})
        assert _is_chatlog(tmp_path, "package.json", c) is False


class TestStillDetectsRealConversations:
    """The FP fix must not regress genuine conversational content."""

    def test_two_speaker_jsonl(self, tmp_path):
        c = ('{"speaker": "u0", "text": "hi"}\n{"speaker": "u1", "text": "yo"}\n'
             '{"speaker": "u0", "text": "bye"}\n')
        assert _is_chatlog(tmp_path, "conv.jsonl", c) is True

    def test_user_assistant_jsonl(self, tmp_path):
        c = ('{"role": "user", "content": "hi"}\n{"role": "assistant", "content": "hello"}\n'
             '{"role": "user", "content": "bye"}\n')
        assert _is_chatlog(tmp_path, "chat.jsonl", c) is True

    def test_markdown_transcript_with_speakers(self, tmp_path):
        c = "### Scene 1\nAlice: hi\n### Scene 2\nBob: hello\n### Scene 3\nmore\n### S4\n### S5\n"
        assert _is_chatlog(tmp_path, "t.md", c) is True

    def test_type_message_envelope_with_role(self, tmp_path):
        # {type:"message", role:user/assistant} — `type` is a constant wrapper;
        # the real speaker is `role`. Must detect (PR #28 review regression).
        c = ('{"type": "message", "role": "user", "content": "hi"}\n'
             '{"type": "message", "role": "assistant", "content": "hello"}\n'
             '{"type": "message", "role": "user", "content": "bye"}\n')
        assert _is_chatlog(tmp_path, "chat.jsonl", c) is True


class TestDeterminism:
    """Flagship property: same bytes -> same manifest, across hash seeds."""

    def test_manifest_checksum_stable_across_hash_seeds(self, tmp_path):
        d = str(tmp_path)
        # multi-role-key objects — the case the set-iteration bug broke
        Path(d, "c.jsonl").write_text(
            '{"role": "user", "content": "a"}\n'
            '{"role": "assistant", "content": "b"}\n'
            '{"speaker": "u", "text": "c"}\n')
        code = (
            "from file_observer.scanner import Scanner, ScannerConfig, manifest_to_json;"
            "import json; from pathlib import Path;"
            f"m = Scanner(source_dir=Path({d!r}), config=ScannerConfig(enable_specialists=True)).scan();"
            "print(json.loads(manifest_to_json(m))['manifest_checksum'])"
        )
        checksums = set()
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                 text=True, env=env)
            assert out.returncode == 0, out.stderr
            checksums.add(out.stdout.strip())
        assert len(checksums) == 1 and "" not in checksums
