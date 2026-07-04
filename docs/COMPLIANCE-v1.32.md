# Compliance — file-observer v1.32.0

Maps the [v1.32.0 RFC](v1.32.0_RFC_Specification.md) to evidence. Written before merge.
**Verdict: compliant.** New content-detected `fact_block` specialist (FR #114) — generic body
`key: value` extraction, provisional.

## Capability (RFC §4) → implementation
| Requirement | Implementation | Status |
|---|---|---|
| Detect a body-dominant fact-block (frontmatter stripped) | `_fact_block_analyze`: strips `FRONTMATTER_RE`, counts non-structural body lines; fires when fact-pairs ≥3 AND ratio ≥0.6 | **Met** |
| Emit observed pairs verbatim + generic, first-occurrence order | `fact_block` namespace `{pair_count, pairs:[{key,value}], duplicate_keys}`; no key allow-list, no validation/normalization anywhere | **Met** |
| Sentence-value veto (FP-hygiene vs dialogue) | a value with a function word AND (≥5 words OR sentence punctuation) is not a fact-pair; measured 0/60 dialogue with the veto, 60/60 without | **Met** |
| Fallback only — no double-handling | gated on `not requires_specialist_tool`; a MIME-guard miss skips silently (no error) — `.eml`/`.pdf`/etc. stay with their specialist | **Met** |
| Bounded / never-crash | caps `FACT_BLOCK_MAX_PAIRS`/`_MAX_KEY_LEN`/`_MAX_VALUE_LEN`; anchored+bounded regexes; never raises | **Met** |
| Determinism | gate/veto/caps → `rules_hash` (via `fact_block_rules_fingerprint`), thresholds → `static_tuning_hash`; two scans byte-identical | **Met** |

## Acceptance bar (RFC §8, falsify-first) → `tests/test_v1_32.py` (16)
| # | Clause | Result |
|---|---|---|
| 1 | fires on a body fact-block; pairs verbatim, first-occurrence order (frontmatter excluded) | ✅ `TestFires` (2) |
| 2 | does NOT fire on prose / dialogue / FAQ / changelog / frontmatter-only | ✅ `TestDoesNotFire` (5, parametrized) |
| 3 | generic — emits whatever keys appear, no Blueprint handling | ✅ `test_pairs_are_verbatim_and_generic` |
| 4 | bounded — hostile inputs capped, never crash | ✅ `TestBounded` |
| 5 | deterministic; namespace provisional in `--schema`; vector rules_hash present | ✅ `TestSchemaAndDeterminism` (6) |
| 6 | coherence — `.eml` (header kv-block) not double-handled, no spurious probe error | ✅ `TestCoherenceWithDedicatedSpecialists` |
| — | version surfaces (SCANNER ≥1.32.0 / SCHEMA ≥1.18 / LOGIC ≥1.16.0) | ✅ `test_version_surfaces` |

Full suite green; `docs/SCHEMA.md` + `docs/manifest.schema.json` regenerated; drift-guards (README, contract-doc, version-sync, provisional-registry, provenance-trigger completeness) green.

## Measure-first (RFC §3, `scratch/measure_kv_fact_block.py`, 2026-07-04)
The FP-hygiene design question — a `key: value` line collides with dialogue. Gate (≥3 pairs, ratio ≥0.6, **sentence-value veto**), measured on real corpora: **db-corpus 497/497 fire (100%, no FN); kb-corpus prose 0/397; dialogue 0/60.** Without the veto, dialogue = 60/60 (100% FP) — the veto is load-bearing. The scanner reproduces this end-to-end: 496/496 of the discovered db-corpus text files fire; 0/395 kb-corpus.

## Four-leg review
| Leg | Result |
|---|---|
| 1 · in-house (inline) | Caught the `.eml` double-handling (email headers are a kv-block) → gated fact_block on `not requires_specialist_tool` + silent MIME-guard skip; and the trigger-method mismatch → dedicated `fact_block_*` provenance triggers. |
| 2 · cross-model (OpenAI `gpt.sh`) | 6 findings, all grounded/triaged. **ADOPTED:** the distinct-key gate (fire on distinct-key count — rejects repeated-key lists + resolves the dedup/min-pairs inconsistency); the MIME-coherence flag gate (`is_fact_block` ⟺ trusted-text MIME — no flag-without-pairs; excludes code typed non-text); rules-fingerprint completeness (frontmatter + the MIME-guard set now feed the `rules_hash`); bounded hardening (cap value before the veto, bounded `split(None,5)`). **DECLINED w/ doc:** the veto-FN "dialogue-key" fix (re-admits dialogue FPs) → accepted residual §10. |
| 3 · corpus sweep | broad FP scan: dialogue 0/15, prose+code-docs 0/85, agentic 0/5, purecfb 34/1887, general corpora 86/16k. Confirmed the `.py`/`.pyi` flag-only FPs (→ the MIME-coherence fix) **and caught a real-data FN** — a kv-block `.md` libmagic mis-typed `text/html`, recovered by trusting `text/html` (db-corpus back to 496/496). Residual code kv-literals (Pygments style dicts) documented §10. |
| 4 · PR bots | on PR open |

## Version axes (RFC §9)
SCANNER 1.31.0→1.32.0; **SCHEMA 1.17→1.18** (a new namespace = contract-shape change; the v1.24/v1.25 precedent); **LOGIC 1.15.3→1.16.0** (new content-detection routing — `is_fact_block` + the fact_block dispatch; additive, False→True only; the v1.2/v1.29 detection-LOGIC precedent).

## Residuals / out of scope (RFC §10)
- Any interpretation of the pairs (graph edges, agent lanes) — recall's side, behind its own RFC.
- Key validation / normalization / a schema — the bright line; never in fo (recall asked me to push back if the RFC ever grows this).
- Emitting frontmatter pairs — already handled; the specialist targets the body only.
