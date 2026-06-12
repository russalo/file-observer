# Example 03 — Chatlog detection

**What it shows:** file-observer recognizes conversational structure from the *content* of a file, not its extension. A plain `.md` that reads as a dialogue gets `is_chatlog: true` and a structured turn/speaker breakdown.

→ Tutorial section: [Chatlog detection](../../docs/TUTORIAL.md#6-chatlog-detection)

## The input

`sample_logs/support_thread.md` — an ordinary Markdown file. Nothing in the name or extension says "chatlog"; it's the *shape* that gets detected:

```
User: the nightly export job failed again, can you take a look?
Agent: Looking now. The traceback points at the S3 upload step …
User: didn't we rotate those last week?
Agent: We rotated the API keys, but the export job uses a separate IAM role …
…
```

## Run it

```bash
./run.sh
# or directly:
file-observer sample_logs --specialists -o out
```

`is_chatlog` is set even **without** `--specialists` (detection is part of the
baseline tier). `--specialists` adds the rich breakdown and the corpus-level
chatlog vector shown below.

## What you get

`files[0]`:

| field | value |
|---|---|
| `is_chatlog` | **`true`** |

`files[0].specialist_metadata.chatlog`:

| field | value |
|---|---|
| `turn_count` | `10` |
| `speaker_labels` | `["Agent", "User"]` |
| `speaker_turn_counts` | `{ "Agent": 5, "User": 5 }` |
| `alternation` | `{ "longest_single_speaker_run": 1, "speaker_change_ratio": 1.0 }` |
| `avg_turn_chars` | `75` |
| `vocabulary_size_estimate` | `94` |

And the `chatlog` vector in `vectors_collected[]`:

```json
{
  "matched_files": 1,
  "total_turns": 10,
  "distinct_speakers": ["Agent", "User"],
  "section_marker_count": 0
}
```

## What just happened

- **Detection is content-based, not extension-based.** Rename the file to `.txt` or `.log` and the result is identical — file-observer looks for the conversational *shape* (speaker labels at line starts, section markers, role/content JSON across ConvoKit / ShareGPT / oasst / hh-rlhf schemas), not a filename pattern.
- **It distinguishes dialogue from prose that merely uses colons.** A changelog (`Added:`, `Fixed:`) or an FAQ (`Question:`) is *not* a chatlog. The detector requires recurring distinct speakers plus a content-shape check (turns that read like utterances — function words, sentence punctuation — not atomic data values), which is why label-heavy data files don't trip it.
- **The breakdown is drift-visible.** `speaker_turn_counts` and `alternation` describe the conversation's structure, so a downstream interpreter can reason about it (who dominates, how balanced the back-and-forth is) without re-parsing the text.
- **`is_chatlog` runs even with specialists off.** The flag is cheap; the rich extraction is the opt-in. file-observer *observes* the structure — what you do with it (route to a conversation pipeline, extract world-facts, train on it) is the consumer's job.

Next: [Example 06](../06-schema-discovery/) — ask file-observer what every field *means*. Or the [tutorial](../../docs/TUTORIAL.md#6-chatlog-detection).
