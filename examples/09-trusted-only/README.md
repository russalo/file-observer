# Example 09 — Safe mode (`--trusted-only`)

**What it shows:** a scan manifest is a report *about* untrusted files, so it echoes attacker-controllable bytes — filenames, `content_preview`, extracted metadata. Pasting that into a model's context is a prompt-injection vector. `--trusted-only` projects the manifest down to **only what file-observer itself computed** (counts, types, hashes, flags), nulling every attacker-controllable string — safe by construction to feed a model.

→ Tutorial section: [Safe mode: feeding untrusted files to a model](../../docs/TUTORIAL.md#11-safe-mode-feeding-untrusted-files-to-a-model)

## The input

`sample_docs/ignore_previous_instructions.md` — an ordinary-looking document whose **filename**, **frontmatter author** (`Mallory Attacker`), and **body** are all attacker-controlled, including a `SYSTEM: ignore all previous instructions …` line. Exactly the content you must not hand a model verbatim.

## Run it

```bash
./run.sh
# or directly:
file-observer sample_docs --specialists --stdout                  # normal — echoes the attacker strings
file-observer sample_docs --specialists --trusted-only --stdout   # safe mode — only fo-derived signal
```

## What you get

The normal manifest carries the attacker strings; the `--trusted-only` projection does not:

```
normal manifest:
  path                : 'ignore_previous_instructions.md'
  content_preview     : present

--trusted-only manifest:
  trusted_only marker : True
  path (file-derived) : None (nulled)
  path_id (fo-derived): <sha256 of the relative path>…  (safe correlation handle)
  content_preview     : None (nulled)
  mime_type (fo-kept) : text/plain
  safety_flags (kept) : []
  summary (fo-derived): None (prose dropped — it names authors/paths)

injection filename present?   normal: True   trusted-only: False
attacker author name present? normal: True   trusted-only: False
```

## What just happened

- **It's a projection, not a sanitizer.** Safe mode never rewrites a value to make it "safe" — there's no safe universal sanitizer for "text a model might act on." It only *drops* the untrusted fields (`path`, `filename`, `content_preview`, `tags`, frontmatter, extracted metadata strings) and keeps the fo-derived ones (`mime_type`, `size_bytes`, `checksum_sha256`, `is_binary`, `safety_flags`, counts).
- **You keep correlation without the payload.** Each file's `path` is nulled, but a `path_id = sha256(<relative path>)` is added — you map it back to a path *you* hashed out-of-band. A top-level `trusted_only: true` marks the projection.
- **The whole manifest is scrubbed, not just `files[]`.** The human `summary`, `meta.source_dir`, duplicate-cluster paths, per-directory names, delta paths, and vector summaries are cleared too — so the *entire* document is safe to feed, in both JSON and JSONL.
- **The default manifest is byte-identical.** Safe mode is a separate, opt-in output; it changed nothing about a normal scan (`LOGIC`/`SCHEMA` unchanged). Prefer the default manifest when you actually want the file-derived detail — use `--trusted-only` for the feed-to-a-model case.
- **It over-suppresses on purpose (fail-safe).** When a field's trust is uncertain it is dropped. To build your own projection instead, read each field's `trust` attribute from [`--schema`](../06-schema-discovery/) (`fo_derived` / `file_derived`).

Next: back to the [tutorial](../../docs/TUTORIAL.md#11-safe-mode-feeding-untrusted-files-to-a-model), or the [MCP example](../08-mcp-server/) — the MCP server exposes the same `trusted_only` mode to an agent.
