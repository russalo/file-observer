Based on the pipeline's operational design, when a new "naked" file is introduced into the Stage 0 ingestion queue, the tagging and metadata elements are applied in a sequence that moves from basic machine identity to complex classification and auditability:

### 1. Base Identity (System-Generated YAML Front Matter)
When the "naked" file first hits the ingestion queue (Stage 0), an orchestration script automatically generates and injects a minimal YAML block at the very top of the Markdown file. This establishes the document's stable identity by assigning a unique identifier (`uuid`), a creation timestamp, and logging the `source` of the ingestion (e.g., email, mobile scan, gdrive).[1]

```yaml
---
uuid: "123e4567-e89b-12d3-a456-426614174000"
date: "2026-04-03T08:00:00Z"
source: "mobile-scan"
---
```

### 2. High-Velocity Signals (Inline Markdown Tags)
As the human operator drafts or quickly reviews the document, they use inline Markdown tags (such as `#brainstorm`, `#urgent`, or `#weird-edge-case`) directly in the body of the text. These are treated as fast, temporary contextual signals for the user and operational flags, rather than permanent structural data, and are not part of the YAML front matter.

```markdown
The client requested an accelerated timeline for the database migration.
#urgent #needs-review #billing-question

We need to verify if the current SLA covers this type of rapid deployment.
```

### 3. Structured Classification (Promoted YAML Front Matter)
As the file moves forward in the pipeline, specific operational tags are "promoted" into durable, structured taxonomy keys within the YAML front matter.[1] Either a human operator (clearing the "Needs Metadata" queue) or an autonomous AI agent evaluates the text to assign rigid YAML fields like `project`, `client`, `doc_type`, and `status` (e.g., draft, needs-review, approved). This formal, structured taxonomy allows the Hugo dashboard to categorize and filter the document.[1]

```yaml
---
uuid: "123e4567-e89b-12d3-a456-426614174000"
date: "2026-04-03T08:00:00Z"
source: "mobile-scan"
project: "Database-Migration"
client: "Acme Corp"
doc_type: "meeting-note"
status: "needs-review"
---
```

### 4. Audit and Enrichment Data (JSON Sidecar Creation)
As background scripts and AI models process the document (e.g., generating summaries for large PDFs or tracking execution failures), they write operational data exclusively to an isolated JSON sidecar file (e.g., `123e4567.json`) rather than touching the Markdown file.[1] This sidecar acts as the machine-audit ledger, storing execution timestamps, retry counters, and specific reason codes for "human-in-the-loop" interventions without cluttering the human-readable text.[1]

```json
{
  "uuid": "123e4567-e89b-12d3-a456-426614174000",
  "last_run": "2026-04-03T08:15:00Z",
  "processing_errors": 0,
  "human_in_loop_required": true,
  "reason_codes": ["billing-review-required"],
  "derived_summary": "Meeting notes regarding Acme Corp's request to accelerate the database migration timeline. SLA verification required."
}
```

### 5. Topological Graph Links (Sidecar Reciprocal Injection)
Finally, during the transition to the production stage, a processing script parses the new document for internal links to other existing documents (e.g., a "Database Architecture" note). It then injects reciprocal backlink arrays directly into the JSON sidecars of the referenced *target* files. This completes the bi-directional knowledge graph without altering the target document's original Markdown text.

*(Example schema injected into the target `Database Architecture` sidecar):*
```json
{
  "uuid": "987f6543-e21b-34c1-b567-426614174999",
  "linked_mentions": [
    {
      "source_uuid": "123e4567-e89b-12d3-a456-426614174000",
      "context": "We need to verify if the current SLA covers this type of rapid deployment."
    }
  ]
}
```

---

### Mapping: pipeline stages → taxonomy
| **Stage** | **Storage pattern** | **Data shape** | **Organization model** | **Semantic role** |
|---|---:|---|---|---|
| **1. Base Identity (YAML front matter)** | Embedded / Inline | Structured | Flat (stable keys) | **System / Provenance** |
| **2. High‑Velocity Signals (inline Markdown tags)** | Embedded Inline (body) | Unstructured | Flat (ad‑hoc labels) | **Transient / Operational** |
| **3. Structured Classification (promoted YAML)** | Embedded / Inline (promoted into front matter) | Structured | Hierarchical or Faceted | **Domain / Business** |
| **4. Audit & Enrichment (JSON sidecar)** | Sidecar (external file) | Structured (machine fields) | Flat (ledger) | **System / Audit / Enrichment** |
| **5. Graph Links (sidecar reciprocal injection)** | Sidecar (external file on targets) | Structured (arrays of links) | Topological (graph) | **Provenance / Knowledge Graph** |

---

### Canonical labels and roll‑up keys
Use a compact label set for cataloging and policy rules. Example roll‑up keys:

- **storage**: `embedded` | `sidecar` | `external`
- **shape**: `structured` | `unstructured`
- **org**: `flat` | `hierarchical` | `faceted` | `graph`
- **semantic**: `system` | `provenance` | `domain` | `state` | `sensitivity` | `transient`

**Example combined tag**:  
`storage:sidecar;shape:structured;org:graph;semantic:provenance`

---

### How to apply this to each stage (practical rules)

#### Stage 1 — Base Identity (system YAML front matter)
- **What to store**: `uuid`, `date`, `source`, `ingest_pipeline_version`.
- **Why**: portable identity that must travel with the file.
- **Label**: `storage:embedded;shape:structured;semantic:system;org:flat`
- **Policy**: write-only by ingestion service; immutable except by authorized reingest.

#### Stage 2 — High‑Velocity Inline Tags
- **What to store**: `#urgent`, `#brainstorm`, quick human flags in body text.
- **Why**: fast human signals; not authoritative.
- **Label**: `storage:embedded;shape:unstructured;semantic:transient;org:flat`
- **Policy**: ephemeral; auto-scan to surface to UI but only promoted after human/AI review.

#### Stage 3 — Promoted Structured Classification
- **What to store**: `project`, `client`, `doc_type`, `status`.
- **Why**: durable business metadata for filtering and automation.
- **Label**: `storage:embedded;shape:structured;semantic:domain;org:hierarchical|faceted`
- **Policy**: require controlled vocabulary; promotion workflow (human or AI) writes to front matter.

#### Stage 4 — Audit & Enrichment Sidecar
- **What to store**: `last_run`, `processing_errors`, `human_in_loop_required`, `derived_summary`.
- **Why**: machine audit trail and enrichment without altering human text.
- **Label**: `storage:sidecar;shape:structured;semantic:system,provenance;org:flat`
- **Policy**: sidecar is authoritative for processing state; reconcile process to detect drift.

#### Stage 5 — Graph Links (reciprocal sidecar injection)
- **What to store**: `linked_mentions` arrays, `source_uuid`, `context`.
- **Why**: build bi‑directional knowledge graph without editing target files.
- **Label**: `storage:sidecar;shape:structured;semantic:provenance;org:graph`
- **Policy**: maintain link provenance (who/when); provide TTL or verification for stale links.

---

### Example consolidated artifacts

**Promoted YAML front matter (embedded, human‑facing)**  
```yaml
---
uuid: "123e4567-e89b-12d3-a456-426614174000"
date: "2026-04-03T08:00:00Z"
source: "mobile-scan"
project: "Database-Migration"
client: "Acme Corp"
doc_type: "meeting-note"
status: "needs-review"
storage: "embedded"
shape: "structured"
org: "hierarchical"
semantic: ["domain","system"]
---
```

**JSON sidecar (machine audit + graph + enrichment)**  
```json
{
  "uuid":"123e4567-e89b-12d3-a456-426614174000",
  "storage":"sidecar",
  "shape":"structured",
  "semantic":["system","provenance"],
  "last_run":"2026-04-03T08:15:00Z",
  "processing_errors":0,
  "human_in_loop_required":true,
  "reason_codes":["billing-review-required"],
  "derived_summary":"Meeting notes regarding Acme Corp's request to accelerate the database migration timeline. SLA verification required.",
  "linked_mentions":[
    {"source_uuid":"987f6543-e21b-34c1-b567-426614174999","context":"See Database Architecture note"}
  ]
}
```

---

### Governance checklist (practical controls)
- **Vocab registry**: central list for `project`, `doc_type`, `status`, `sensitivity`. Enforce via schema validation on promotion.
- **Promotion workflow**: inline tags → candidate structured fields → human/AI approval → write to front matter.
- **Sidecar reconciliation**: periodic job that compares front matter vs catalog vs sidecar; flag drift.
- **Access rules**: system tags (checksums, last_run) writable only by processing services; domain tags writable by metadata stewards.
- **Search indexing**: index both front matter and sidecar fields; treat inline tags as lower‑confidence signals until promoted.

---

### Quick naming cheat sheet (one line each)
- **Identity**: `storage:embedded;shape:structured;semantic:system`  
- **Quick flags**: `storage:embedded;shape:unstructured;semantic:transient`  
- **Business metadata**: `storage:embedded;shape:structured;semantic:domain;org:hierarchical`  
- **Audit ledger**: `storage:sidecar;shape:structured;semantic:system`  
- **Graph links**: `storage:sidecar;shape:structured;semantic:provenance;org:graph`

---

## 🧩 Tag Taxonomy Applied to Your Pipeline  
*A Markdown‑formatted reference sheet*

### 1. Overview  
Your pipeline already expresses **five distinct metadata layers**. Using the universal axes we defined — **storage**, **shape**, **organization**, and **semantic role** — we can classify each layer cleanly and consistently.

This gives you a shared vocabulary for governance, automation, dashboards, and contributor onboarding.

---

### 2. Pipeline Stages → Tag Taxonomy

**Stage 1 — Base Identity (YAML Front Matter)**  
> “an orchestration script automatically generates and injects a minimal YAML block…”  

**Classification:**  
- **storage:** `embedded`  
- **shape:** `structured`  
- **org:** `flat`  
- **semantic:** `system`, `provenance`  

**Purpose:** Stable identity, ingestion provenance, immutable system metadata.

---

**Stage 2 — High‑Velocity Inline Tags (Markdown Body)**  
> “inline Markdown tags such as `#urgent`, `#needs-review`…”  

**Classification:**  
- **storage:** `embedded`  
- **shape:** `unstructured`  
- **org:** `flat`  
- **semantic:** `transient`, `operational`  

**Purpose:** Fast human signals; candidates for promotion.

---

**Stage 3 — Structured Classification (Promoted YAML)**  
> “specific operational tags are ‘promoted’ into durable, structured taxonomy keys…”  

**Classification:**  
- **storage:** `embedded`  
- **shape:** `structured`  
- **org:** `hierarchical` or `faceted`  
- **semantic:** `domain`, `business`  

**Purpose:** Durable classification for dashboards, filtering, workflows.

---

**Stage 4 — Audit & Enrichment (JSON Sidecar)**  
> “background scripts… write operational data exclusively to an isolated JSON sidecar…”  

**Classification:**  
- **storage:** `sidecar`  
- **shape:** `structured`  
- **org:** `flat`  
- **semantic:** `system`, `audit`, `provenance`  

**Purpose:** Machine ledger, enrichment, retry logs, summaries.

---

**Stage 5 — Topological Graph Links (Sidecar Injection)**  
> “injects reciprocal backlink arrays directly into the JSON sidecars of the referenced target files…”  

**Classification:**  
- **storage:** `sidecar`  
- **shape:** `structured`  
- **org:** `graph`  
- **semantic:** `provenance`, `knowledge-graph`  

**Purpose:** Bi‑directional linking without touching human text.

---

### 3. Canonical Labels (Cheat Sheet)

Use these consistently across your system:

```yaml
storage: embedded | sidecar | external
shape: structured | unstructured
org: flat | hierarchical | faceted | graph
semantic:
  - system
  - provenance
  - domain
  - state
  - sensitivity
  - transient
```

---

### 4. Example: Promoted YAML Front Matter

```yaml
---
uuid: "123e4567-e89b-12d3-a456-426614174000"
date: "2026-04-03T08:00:00Z"
source: "mobile-scan"

project: "Database-Migration"
client: "Acme Corp"
doc_type: "meeting-note"
status: "needs-review"

storage: "embedded"
shape: "structured"
org: "hierarchical"
semantic: ["domain", "system"]
---
```

---

### 5. Example: JSON Sidecar (Audit + Graph)

```json
{
  "uuid": "123e4567-e89b-12d3-a456-426614174000",
  "storage": "sidecar",
  "shape": "structured",
  "semantic": ["system", "provenance"],

  "last_run": "2026-04-03T08:15:00Z",
  "processing_errors": 0,
  "human_in_loop_required": true,
  "reason_codes": ["billing-review-required"],
  "derived_summary": "Meeting notes regarding Acme Corp's request to accelerate the database migration timeline. SLA verification required.",

  "linked_mentions": [
    {
      "source_uuid": "987f6543-e21b-34c1-b567-426614174999",
      "context": "We need to verify if the current SLA covers this type of rapid deployment."
    }
  ]
}
```

---

### 6. Governance Rules (Markdown‑Friendly)

#### **Promotion Workflow**
- Inline tags → candidate structured fields  
- Human/AI review → approved  
- Write to YAML front matter  

#### **Sidecar Rules**
- Never edited by humans  
- Machine‑only fields  
- Reconciliation job detects drift  

#### **Vocabulary Control**
- `project`, `doc_type`, `status`, `sensitivity` use controlled lists  
- Inline tags remain freeform  

#### **Access Rules/Graph Integrity**
- Reciprocal links maintained automatically  
- Stale links flagged by periodic verification  

---

