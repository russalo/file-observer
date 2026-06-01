"""v1.2.2 — prose-mode chatlog false-positive corpus + recurrence rule.

Found by the empirical corpus sweep harness (scratch/review/corpus_sweep.py) on
its first run: the v1.2.1 ">=2 distinct speakers" hardening was added to the JSON
path but never ported to prose Rule 1, which still fired on >=3 total
`^Capitalized:` matches with no distinctness/recurrence. Email headers, legal
notices, UTF-8 demos, man-page labels, and form fields were all flagged.

Written FIRST (falsify-before-fix): on the unfixed code the TestProseFalsePositives
cases FAIL (they reproduce the shipped FPs). The fix — Rule 1 requires a recurring
speaker (real back-and-forth) + an expanded stop-list — makes them pass without
regressing the genuine-transcript cases. See scratch/review/v1_2_2_fp_findings.md
and [[feedback_falsify_dont_confirm]].
"""

from file_observer.scanner import Scanner, ScannerConfig


def _is_chatlog(tmp_path, name, content):
    (tmp_path / name).write_text(content)
    return Scanner(source_dir=tmp_path, config=ScannerConfig()).scan().files[0].is_chatlog


class TestProseFalsePositives:
    """Header/label blocks are NOT conversations. Each catalogued from a real
    corpus file the sweep flagged under v1.2.1."""

    def test_email_headers_not_flagged(self, tmp_path):
        # obs-studio QSV11-License-Clarification-Email.txt shape
        c = ("From: alice@example.com\nTo: bob@example.com\nCc: team@example.com\n"
             "Date: Mon, 1 Jun 2026 10:00:00\nSubject: License clarification\n\n"
             "Please see the attached clarification regarding the license terms.\n")
        assert _is_chatlog(tmp_path, "email.txt", c) is False

    def test_usenet_headers_not_flagged(self, tmp_path):
        # tika testRFC822 / testMessageNews shape — 7 distinct one-shot headers
        c = ("Path: news.example.com\nFrom: poster@example.com\n"
             "Newsgroups: comp.lang.python\nSubject: Re: question\n"
             "Date: 1 Jun 2026\nOrganization: Example\nLines: 12\n\nbody text here\n")
        assert _is_chatlog(tmp_path, "news.txt", c) is False

    def test_utf8_demo_labels_not_flagged(self, tmp_path):
        # tmux tools/UTF-8-demo.txt shape — 6 distinct one-shot script labels
        c = ("APL: ⍝ ⌽ ⊖\nBraille: ⠁⠂⠃\nGeorgian: შემოქმედი\n"
             "Russian: Съешь же\nEthiopian: ሰላም\nRunes: ᚠᚢᚦ\n")
        assert _is_chatlog(tmp_path, "UTF-8-demo.txt", c) is False

    def test_language_label_block_not_flagged(self, tmp_path):
        # tika multi-language.txt shape
        c = ("English: The quick brown fox.\nPortuguese: A rápida raposa.\n"
             "Spanish: El zorro rápido.\n")
        assert _is_chatlog(tmp_path, "multi-language.txt", c) is False

    def test_manpage_labels_not_flagged(self, tmp_path):
        # autogpt docs/content/classic/usage.md shape — recurring doc labels
        c = ("Usage: tool [opts]\nOptions: --verbose\nCommands: run\n"
             "Usage: tool run [opts]\nOptions: --dry\nCommands: list\n")
        assert _is_chatlog(tmp_path, "usage.md", c) is False

    def test_doc_section_labels_not_flagged(self, tmp_path):
        # autogpt battleship product spec shape — one-shot section labels
        c = ("Overview: build battleship\nShips: 5 types\n"
             "Setup: place ships\nObjective: sink all\n")
        assert _is_chatlog(tmp_path, "spec.txt", c) is False

    def test_legal_notice_not_flagged(self, tmp_path):
        # tika NOTICE.txt shape
        c = ("License: Apache 2.0\nLicense: see LICENSE file\n"
             "OpenCSV: bundled under Apache 2.0\n")
        assert _is_chatlog(tmp_path, "NOTICE.txt", c) is False

    def test_oauth_form_fields_not_flagged(self, tmp_path):
        # fastapi simple-oauth2.md shape — User:/Password: pairs (Password stop-listed)
        c = ("User: johndoe\nPassword: secret\nUser: alice\nPassword: hunter2\n")
        assert _is_chatlog(tmp_path, "oauth.md", c) is False


class TestProseTruePositivesStillDetect:
    """The fix must not regress genuine prose transcripts."""

    def test_three_turn_two_speaker_recurs(self, tmp_path):
        # 2 speakers, one recurs — minimal real back-and-forth
        c = "Alice: hi there friend\nBob: hello back\nAlice: goodbye now\n"
        assert _is_chatlog(tmp_path, "chat.txt", c) is True

    def test_human_assistant_transcript(self, tmp_path):
        c = ("Human: what's the weather\nAssistant: sunny today\n"
             "Human: thanks\nAssistant: anytime\n")
        assert _is_chatlog(tmp_path, "transcript.txt", c) is True

    def test_markdown_transcript_with_h3_structure(self, tmp_path):
        # detects via the structure rule (5+ H3 + speaker co-signal), not Rule 1
        c = ("### Scene 1\nAlice: hi\n### Scene 2\nBob: hello\n### Scene 3\n"
             "more\n### Scene 4\n### Scene 5\n")
        assert _is_chatlog(tmp_path, "play.md", c) is True
