## Task: Formalize Structural Signals Layer (Non-Breaking Patch)

### Objective

Update the existing Scanner Specification to formally incorporate currently implemented structural fields into a defined, contract-safe layer.

This is a **schema formalization**, not a redesign.

---

## Step 1 — Locate Insertion Point

Find the section:

### `Capability Model`

Immediately AFTER this section, insert a new section:

---

## Step 2 — Insert New Section

### `Structural Signals Layer (v1 Extension)`

Add:

The Structural Signals Layer provides lightweight document structure signals derived during baseline processing.

This layer:

* operates within the baseline capability envelope
* requires no specialist tools
* must be best-effort and non-blocking
* must not introduce scan failure
* must not depend on external libraries beyond baseline processing

These signals provide early document understanding without invoking specialist parsing.

---

## Step 3 — Update File Record Schema (CRITICAL)

Locate the File Record JSON schema.

### REMOVE the following top-level fields if present:

* `filename_date`
* `title`
* `heading_structure`
* `document_keys`
* `csv_headers`
* `technology_hints`

---

### ADD the following grouped object:

```json
"structural": {
  "title": null,
  "heading_structure": [],
  "csv_headers": [],
  "document_keys": [],
  "technology_hints": [],
  "filename_date": null
}
```

---

## Step 4 — Add Field Definitions

Create a new subsection under schema definitions:

### `Structural Fields`

Define:

#### `structural.title`

* string or null
* derived from:

  * markdown H1
  * HTML `<title>`
  * fallback: first strong heading

#### `structural.heading_structure`

* array of strings
* ordered headings detected in markdown or HTML

#### `structural.csv_headers`

* array of strings
* extracted from first row of CSV

#### `structural.document_keys`

* array of strings
* top-level keys for JSON/YAML documents

#### `structural.technology_hints`

* array of strings
* inferred via lightweight pattern detection (e.g., `google-fonts`, `react`)

#### `structural.filename_date`

* string or null
* inferred from filename patterns
* normalized to ISO format when possible

---

## Step 5 — Update Classification Layer Mapping

Locate the classification table.

ADD:

| Structural | structural.* | lightweight document structure signals |

---

## Step 6 — Add Constraints (IMPORTANT)

Add rules:

* MUST NOT require specialist tools
* MUST NOT introduce additional dependencies
* MUST NOT cause scan failure
* MUST default to null or empty values
* MUST be deterministic
* MUST NOT override specialist extraction results

---

## Step 7 — Validation Requirements

Ensure:

* schema remains backward compatible except for field grouping
* all structural fields exist under `structural`
* no duplicate flat fields remain
* all fields are always present

---

## Expected Result

The scanner specification now explicitly defines:

Universal → Baseline → Structural → Specialist

with structural signals as a first-class, contract-safe layer.
