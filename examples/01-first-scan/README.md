# Example 01 — Your first scan

**What it shows:** point file-observer at a folder, get back one deterministic JSON manifest describing every file. No config, no setup.

→ Tutorial section: [First scan](../../docs/TUTORIAL.md#3-your-first-scan)

## The input

`sample_project/` — a small mixed-format folder:

```
sample_project/
├── README.md      # Markdown
├── config.yaml    # YAML
├── data.csv       # CSV
└── logo.png       # PNG (binary)
```

## Run it

```bash
./run.sh
# or directly:
file-observer sample_project -o out
```

## What you get

A manifest with one record per file. The salient fields for each:

| path | mime_type | is_binary | is_chatlog |
|---|---|---|---|
| `README.md` | `text/plain` | false | false |
| `config.yaml` | `text/plain` | false | false |
| `data.csv` | `text/csv` | false | false |
| `logo.png` | `image/png` | **true** | false |

And top-level stats:

```json
{
  "stats": { "total_files": 4, "text_files": 3, "binary_files": 1 },
  "manifest_checksum": "1be2df6284038d24a810dd0f…"
}
```

## What just happened

- **MIME is detected from content, not the extension.** `data.csv` is `text/csv` because of what's inside it; `logo.png` is `image/png` from its magic bytes — rename it to `.txt` and file-observer still calls it a PNG.
- **`is_binary` is a derived routing flag.** The PNG is binary; the three text files aren't. Downstream pipelines route on this without re-sniffing.
- **`manifest_checksum` is the determinism handle.** It's a SHA-256 over the whole manifest *excluding* the volatile `scan_id` and `generated_at`. Scan the same bytes again → identical checksum. That's what makes file-observer safe in a pipeline: same input, same observation, every time.

Every derived field also carries a `signal_provenance` entry saying *how* it was derived (which method, what triggered it) — see [Example 02](../02-pdf-metadata/) and the [tutorial](../../docs/TUTORIAL.md#4-reading-a-filerecord).
