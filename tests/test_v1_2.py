"""v1.2 — generalized conversational detection + per-speaker structure.

Covers the schema families the v0.10.1 detector missed (ConvoKit speaker/text,
ShareGPT from/value array, role/content, oasst nested tree, hh-rlhf embedded
dialogue), the .json candidate gate, per-speaker fields, and error detail.
All fixtures are synthetic/inline so the suite is CI-safe (no external corpora).
"""

import json
from pathlib import Path

from file_observer.scanner import Scanner, ScannerConfig, ErrorRecord


def _scan_text(tmp_path, name, content, specialists=True):
    (tmp_path / name).write_text(content)
    cfg = ScannerConfig(enable_specialists=specialists)
    return Scanner(source_dir=tmp_path, config=cfg).scan().files[0]


class TestGeneralizedDetection:
    def test_convokit_speaker_text_jsonl(self, tmp_path):
        c = ('{"speaker": "u0", "text": "hello"}\n'
             '{"speaker": "u1", "text": "hi there"}\n'
             '{"speaker": "u0", "text": "how are you"}\n')
        assert _scan_text(tmp_path, "utterances.jsonl", c).is_chatlog is True

    def test_role_content_jsonl(self, tmp_path):
        c = ('{"role": "user", "content": "hi"}\n'
             '{"role": "assistant", "content": "hello"}\n'
             '{"role": "user", "content": "bye"}\n')
        assert _scan_text(tmp_path, "chat.jsonl", c).is_chatlog is True

    def test_sharegpt_from_value_json_array(self, tmp_path):
        c = json.dumps({"conversations": [
            {"from": "human", "value": "hi"},
            {"from": "gpt", "value": "hello"},
            {"from": "human", "value": "bye"},
        ]})
        assert _scan_text(tmp_path, "share.json", c).is_chatlog is True

    def test_oasst_nested_tree_jsonl(self, tmp_path):
        c = json.dumps({"prompt": {"role": "prompter", "text": "hi", "replies": [
            {"role": "assistant", "text": "hello", "replies": [
                {"role": "prompter", "text": "bye", "replies": []}]}]}})
        assert _scan_text(tmp_path, "trees.jsonl", c).is_chatlog is True

    def test_hh_rlhf_embedded_dialogue(self, tmp_path):
        c = json.dumps({"chosen": "\n\nHuman: hi\n\nAssistant: hello\n\nHuman: bye",
                        "rejected": "\n\nHuman: hi\n\nAssistant: no"})
        assert _scan_text(tmp_path, "hh.jsonl", c).is_chatlog is True

    def test_user_assistant_still_detected(self, tmp_path):
        # legacy v0.10.1 schema must not regress
        c = ('{"type": "user", "message": {"content": "hi"}}\n'
             '{"type": "assistant", "message": {"content": "hello"}}\n'
             '{"type": "user", "message": {"content": "bye"}}\n')
        assert _scan_text(tmp_path, "claude.jsonl", c).is_chatlog is True


class TestJsonGateAndFalsePositives:
    def test_json_extension_is_a_candidate(self, tmp_path):
        c = json.dumps([{"speaker": "a", "text": "x"}, {"speaker": "b", "text": "y"},
                        {"speaker": "a", "text": "z"}])
        rec = _scan_text(tmp_path, "conv.json", c)
        assert rec.is_chatlog is True
        # detection ran → provenance recorded
        assert "is_chatlog" in rec.signal_provenance

    def test_plain_config_json_not_flagged(self, tmp_path):
        c = json.dumps({"name": "pkg", "version": "1.0", "scripts": {"build": "tsc"},
                        "dependencies": {"a": "^1", "b": "^2"}})
        assert _scan_text(tmp_path, "package.json", c).is_chatlog is False

    def test_prose_doc_markdown_not_flagged(self, tmp_path):
        c = ("# Title\n\n### Overview\nprose\n### Parameters\nprose\n"
             "### Returns\nprose\n### Examples\nprose\n### Notes\nprose\n")
        assert _scan_text(tmp_path, "README.md", c).is_chatlog is False


class TestPerSpeakerStructure:
    def test_speaker_turn_counts_and_alternation(self, tmp_path):
        c = ('{"speaker": "alice", "text": "one"}\n'
             '{"speaker": "bob", "text": "two"}\n'
             '{"speaker": "alice", "text": "three"}\n'
             '{"speaker": "bob", "text": "four"}\n')
        chat = _scan_text(tmp_path, "u.jsonl", c).specialist_metadata["chatlog"]
        assert chat["speaker_turn_counts"] == {"alice": 2, "bob": 2}
        assert chat["alternation"]["longest_single_speaker_run"] == 1
        assert chat["alternation"]["speaker_change_ratio"] == 1.0
        assert set(chat["speaker_turn_chars"]) == {"alice", "bob"}

    def test_fields_present_in_prose_mode(self, tmp_path):
        c = "Alice: hi there friend\nBob: hello back\nAlice: goodbye now\n"
        chat = _scan_text(tmp_path, "chat.txt", c).specialist_metadata["chatlog"]
        assert "speaker_turn_counts" in chat
        assert "alternation" in chat
        assert "speaker_turn_chars" in chat


class TestErrorDetail:
    def test_error_record_supports_detail(self):
        e = ErrorRecord(code="x", message="m", stage="specialist",
                        detail={"reason": "test"})
        assert e.detail == {"reason": "test"}

    def test_detail_defaults_none(self):
        e = ErrorRecord(code="x", message="m", stage="specialist")
        assert e.detail is None
