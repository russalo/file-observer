# Generated fixtures (self-authored, license-clean)

These exercise format-detection / specialist code paths for which we had **no
fixture coverage**, without redistributing third-party files of unclear license
(ISO/Nokia HEIF conformance files, mixed-provenance corpora).

They are **self-generated** and **spec-accurate** — `generate.py` builds them from
the public format definitions:
- **HEIF/AVIF** (`*.heic`/`*.avif`) — a correct ISO/IEC 23008-12 / MIAF `ftyp` box
  (brand codes per the MP4RA registry) + a minimal `free` padding box. The scanner
  reads only the `ftyp` brand, so these test the exact detection path. `heif_mif1_heic`
  is the `mif1`-major-with-`heic`-compatible case (the v1.16 compatible-brands target).
  Not decodable images — detection fixtures, by design.
- **`generated.xls`** — a real BIFF8 workbook (via `xlwt`).
- **`generated.doc`** — a minimal OLE2/CFB with only a `\x05SummaryInformation`
  property stream (Title/Author) — the part the `.doc` specialist reads.

Regenerate: `python tests/fixtures/generated/generate.py`. Tested by
`tests/test_fixture_coverage.py`.
