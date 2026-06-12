# Brand + diagram assets for file-observer

Palette: deep slate `#2e404c` + teal `#279288`. All PNGs have a **real alpha
channel** (transparent background — verify `Image.open(p).mode == "RGBA"`).

| File | What it is | Used in |
|---|---|---|
| `logo.png` | Aperture-to-grid mark (raw input → structured output) | README header; favicon source |
| `logo-wordmark.png` | Mark + "file-observer" lockup | horizontal contexts (social, docs) |
| `logo-mono.png` | Single-color (slate) mark | single-color contexts |
| `favicon.png` | Square 256×256 mark | docs-site favicon |
| `pipeline-diagram.png` | files → deterministic, checksum-sealed observation → one JSON manifest → many consumers | README hero; `docs/TUTORIAL.md` §1 |

## Provenance

The **mark** and the **pipeline diagram** were generated via the Gemini paste-path
(prompts in `scratch/gemini_asset_prompts.md`). The **wordmark, monochrome, and
favicon are composited from the real mark** (Pillow), not regenerated — a
text-to-image model can't reproduce an exact reference mark, so deriving them
programmatically guarantees a pixel-exact match. Backgrounds were made truly
transparent in the same pass (the generator baked a checkerboard into RGB
pixels rather than using a real alpha channel).

Shipped transparent / light-optimized: slate is crisp in GitHub light mode and
dims (teal still pops) in dark mode — a deliberate call, no `<picture>` dark
variant. Pending optional: OG/social card.
