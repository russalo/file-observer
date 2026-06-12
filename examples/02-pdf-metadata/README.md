# Example 02 — PDF metadata with specialists

**What it shows:** add `--specialists` and file-observer pulls structured metadata *out* of a PDF — page count, the producing toolchain, dates, encryption state — and rolls it up into a corpus-level provenance vector.

→ Tutorial section: [Specialists](../../docs/TUTORIAL.md#5-specialists--per-format-extraction)

## The input

`sample_pdf/scanned_form.pdf` — a single-page PDF produced by scanning a paper form (a ScanSnap scanner, then Photoshop's image-conversion plug-in). No text layer — it's an image of a page.

## Run it

```bash
./run.sh
# or directly:
file-observer sample_pdf --specialists -o out
```

`--specialists` is required — by default file-observer stays at the fast
universal/baseline tiers and does no format parsing. The `[pdf]` extra
(`pip install "file-observer[pdf]"`) extends coverage to object-stream and
encrypted PDFs; this example works without it.

## What you get

`files[0].specialist_metadata.pdf` — the structured extraction:

| field | value | |
|---|---|---|
| `page_count` | `1` | read from the page tree via the xref index |
| `producer` | `Adobe Photoshop for Windows -- Image Conversion Plug-in` | |
| `creator` | `PFU ScanSnap Home 3.0.0 #iX1600` | the scanner that made it |
| `creation_date` | `D:20250718093034-07'00'` | raw PDF date string |
| `xref_type` | `classic` | how the index was structured |
| `text_detected` | `false` | no text layer — it's a scanned image |
| `encrypted` | `false` | |

Because there's no text layer, the universal routing flags also shift:

| field | value |
|---|---|
| `requires_specialist_tool` | `true` |
| `requires_vision` | **`true`** — downstream OCR/vision should handle this one |

And the corpus-level `provenance` vector (in `vectors_collected[]`) classifies it:

```json
{
  "toolchains": [{ "name": "Adobe (Acrobat/CS app)", "count": 1 }],
  "production_years": { "2025": 1 },
  "digitization": { "born_digital": 0, "scanned": 1, "ocr_detected": 0, "unknown": 0 }
}
```

## What just happened

- **The metadata lives at the *end* of a PDF, and file-observer reads it there.** Page count, the `/Info` dictionary (producer/creator/dates), and font markers sit in the trailer and compressed streams, not the first few KB. file-observer follows the PDF's own xref index to find them — so `page_count` and `producer` are real, not null.
- **`requires_vision` is a derived routing decision, not a guess.** No text layer + image content → `requires_vision: true`. A born-digital PDF with selectable text would be `false`. Your pipeline routes the scanned ones to OCR and leaves the rest alone.
- **`provenance` aggregates the *how* and *when* across the whole scan.** One file here, but on a real corpus this vector tells you which toolchains produced your documents, across which years, and how many were scanned vs born-digital vs OCR'd — WHAT-made-it / WHEN, complementing `author_aggregate`'s WHO.
- **`null` means "not observed within bounds," never "absent."** `title`/`author` are null here because this scanned form carries none — a distinction file-observer preserves rather than inventing a value.

Next: [Example 03](../03-chatlog-detection/) — content-detected structure that needs no specialist at all. Or the [tutorial](../../docs/TUTORIAL.md#4-reading-a-filerecord) on reading a FileRecord.
