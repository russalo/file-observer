# Scanner v0.3 Design Document (Draft)

**Project:** Scanner
**Target Version:** 0.3.0
**Status:** Design Proposed
**Date:** 2026-04-07
**Philosophy:** "Report the News" - Deterministic logic provenance and bounded, sample-based structural signals.

---

## 1. Overview

Scanner v0.3 expands the observation layer by increasing operational fidelity and reaching into new file formats. It prioritizes strict determinism and "bounded observation," ensuring the scanner provides rich metadata without crossing the boundary into document processing, semantic interpretation, or full-file parsing.

### 1.1 Core Mandates
- **Capability-Locked Determinism**: Identical inputs AND an identical `ScanContext` MUST always produce identical outputs. Variance across environments is expected if functional capabilities (e.g., library versions) differ, and MUST be explained by the `context`.
- **Structured Provenance**: The manifest MUST explain *why* routing decisions were made using a machine-readable, queryable data structure.
- **Bounded Observation**: New specialist signals MUST be derived exclusively from the existing bounded `sample_size` buffer (default 8KB).

---

## 2. Operational Fidelity (Track A)

### 2.1 ScanContext

The manifest MUST contain a `context` object to fingerprint the environment's functional capabilities. 

```json
{
  "context": {
    "logic_version": "v0.3.0",
    "python_version": "3.12.3",
    "dependencies": {
      "magic": {"available": true, "version": "5.45"},
      "chardet": {"available": true, "version": "5.2.0"},
      "yaml": {"available": true, "version": "6.0.1"}
    }
  }
}
```

- `logic_version`: A hardcoded identifier representing the decision tree structure.
- `dependencies`: Version-aware status of optional libraries that influence extraction logic.

### 2.2 Signal Provenance

Every `FileRecord` MUST include a `provenance` map. This replaces flat string traces with a structured record of which logic gate produced a specific signal.

#### Proposed shape
```json
{
  "provenance": {
    "is_binary": {
      "layer": "derived",
      "method": "detect_binary",
      "trigger": "nul_byte_detected",
      "tier": "universal"
    },
    "mime_type": {
      "layer": "raw",
      "method": "detect_mime",
      "trigger": "libmagic_match",
      "tier": "universal"
    }
  }
}
```

- **Layer**: `raw`, `derived`, or `semantic-local`.
- **Method**: The internal function name or logic block.
- **Trigger**: The specific condition that satisfied the logic (e.g., `extension_match`, `text_ratio_failure`).
- **Tier**: The capability tier where the signal was generated.

---

## 3. Expanded Specialist Reach (Track B)

Specialist tier probes must adhere to the **Sample-Based Constraint**: All structural and envelope extraction MUST occur within the `sample_size` (8KB) buffer. If the necessary headers fall outside the sample, extraction yields `null`.

### 3.1 PDF Text Marker Density

Instead of qualitative judgments ("sparse"/"dense") or full-file density parsing, v0.3 introduces a quantitative, sample-based metric to help downstream engines assess if a PDF is likely a scanned image.

- **`sample_text_marker_density`**: Float ratio of text operator markers (`BT`, `ET`) relative to the sample buffer size.
- **Calculation**: `(count_BT + count_ET) / sample_size_bytes`
- **Limitation**: Evaluates only the first 8KB of the document.

### 3.2 PNG Physicality

Extract structural dimensions from the PNG `IHDR` chunk.

- **Constraint**: Parsed directly from the sample buffer using `struct` (no external imaging libraries).
- **Extracted Fields**:
  - `width` (int)
  - `height` (int)
  - `bit_depth` (int)

### 3.3 MSG Envelope (OLE2/CFB)

Extract routing envelope properties from Outlook `.msg` containers. 

- **Constraint**: This is explicit container structural extraction, NOT semantic body parsing.
- **Implementation**: Utilizes `olefile` (optional dependency). If unavailable, fails gracefully.
- **Extracted Fields**:
  - `subject` (string)
  - `from` (string)
  - `to` (string)
- **Sample Fallback**: If the property streams exist beyond the sample buffer bounds, these fields evaluate to `null`, adding a `trace` entry of `specialist:msg(missing_from_sample)`.

---

## 4. Format Expansion (Track C)

v0.3 formally adds support for structural text formats and validates the new specialist formats.

- **`.xml`**: Handled via `xml.etree.ElementTree`. Extracts the root element and direct child element names to populate `structural.document_keys`.
- **`.toml`**: Handled via Python 3.11+ `tomllib`. Extracts top-level keys to populate `structural.document_keys`.
- **`.png`, `.jpg`, `.gif`, `.msg`**: Added to `SUPPORTED_EXTENSIONS` to eliminate `unsupported_extension` errors and intentionally invoke the specialist tier.

---

## 5. Next Steps

1. Review and finalize this draft.
2. Implement data structures (`ScanContext`, `trace`).
3. Build the `IHDR`, PDF, and CFB extraction functions within the sample buffer constraint.
4. Ensure 100% determinism across the new fields.
