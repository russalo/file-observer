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
- **`generated.ppt`** (v1.25) — a minimal OLE2/CFB with `\x05SummaryInformation`
  (Title/Author/AppName 0x12) + `\x05DocumentSummaryInformation` (SlideCount 0x07,
  VT_I4) — the streams the `.ppt` specialist reads. Round-trip verified through
  `olefile` at generation time.
- **EXIF (`exif_*.jpg` / `exif_phone_gps.heic`)** — self-authored CIPA DC-008 TIFF/IFD
  blocks (Make/Model/Orientation/DateTimeOriginal + GPS-IFD presence + PixelX/YDimension)
  wrapped in a JPEG APP1 segment and an ISO 14496-12 `meta`→`iinf`/`iloc`→`Exif`-item
  structure. They exercise the v1.16 image-EXIF path exactly: `exif_camera_gps.jpg`
  (GPS present → `geotagged`, + XMP marker), `exif_camera_nogps.jpg` (no GPS), and
  `exif_phone_gps.heic` (HEIC dims from EXIF pixel dimensions, GPS present). No
  third-party photo — license-clean.
- **Video (`video_h264.mov`)** — a minimal self-authored QuickTime/ISOBMFF container
  (`moov`{`mvhd`,`trak`{`tkhd`,`mdia`{`hdlr`,`minf`/`stbl`/`stsd`}}}) with the `moov` box
  placed AFTER `mdat` (the tail), so it exercises the v1.17 `video_structure` tail-scan
  (real `.mov` put `moov` at the end — measured 61/62). Container-half fields only
  (codec/duration/dims/creation_date). No third-party video — license-clean.
- **Video w/ Apple keys (`video_qt_gps.mov` / `video_qt_nogps.mov`)** — self-authored
  QuickTime metadata: `moov`→`meta`(not a FullBox)→`{hdlr, keys, ilst}` carrying
  `com.apple.quicktime.make`/`.model` and (gps variant) `.location.ISO6709`. Exercises the
  v1.18 `make`/`model` + `gps_present`/`gps_source` + `geotagged` path, GPS-present and
  GPS-absent. `video_qt_iso_mp4.mp4` is the **ISO FullBox `meta`** form (standard `.mp4`,
  children at +12) vs the QuickTime `.mov` form (+8) — proves both are parsed.
  **Fabricated coordinates** — real geotagged clips stay local-gitignored.

Regenerate: `python tests/fixtures/generated/generate.py`. Tested by
`tests/test_fixture_coverage.py`.
