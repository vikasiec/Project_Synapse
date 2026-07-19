# Project Synapse

## Org-wide zero-ETL semantic data core

Project Synapse is a schema-on-read semantic data plane for messy, multi-source enterprise data. It lands source payloads with lineage and policy, applies minimal reversible preparation, extracts meaning through deterministic rules plus selective AI, preserves disagreements as first-class conflicts, and answers with citations under explicit cost and latency budgets.

It sits above systems of record. It does not replace HIS, LIS, CRM, billing, or other operational systems, and “zero-ETL” does not mean zero work: it means no rigid warehouse schema is required before data becomes useful.

**Version:** 0.17.0 · **Status:** working proof · **Python:** 3.10+

---

## The problem

Traditional schema-on-write pipelines force premature agreement across systems that describe the same reality differently.

| Failure mode | Consequence |
|---|---|
| Brittle contracts | An upstream schema change breaks downstream transformations. |
| Batch latency | Data is separated from the moment it becomes actionable. |
| Context destruction | Normalization removes anomalies and narrative detail useful to reasoning systems. |
| Hidden disagreement | Conflicting values are silently collapsed into a misleading “truth.” |

### The Synapse thesis

Store raw operational telemetry permanently alongside rich lineage tags. Defer structural modeling and validation to query time. Maintain an evolving graph of entities, facts, temporal state, and conflicts instead of treating one cleaned table as the only source of truth.

---

## Architecture

```text
Sources: OLTP · SaaS · logs · PDFs · events · spreadsheets · APIs
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ RAW LANDING ZONE                                             │
│ Immutable payloads · hashes · source metadata · ACL tags     │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ INGEST & PREP                                                │
│ Connectors · CDC · light operators · PII tagging · episodes  │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ SEMANTIC DATA PLANE                                          │
│ Episodes · entities · facts · conflicts · derived views      │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ CONTROL PLANE                                                │
│ Router · budgets · ABAC · ontology · eval · cost metering     │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
Consumers: Sense board · NL query · agents · audit · BI emit
```

### Four engine pieces

The architecture is assembled from four specialized open-source roles. They are necessary building blocks, not the whole product; the control plane, contracts, discrepancy model, and evaluation gates make the platform usable.

| Component | Role in Synapse |
|---|---|
| [Graphiti](https://github.com/getzep/graphiti) | Continuous temporal relation modeler; tracks entities and changing state across episodes. |
| [GraphRAG](https://github.com/microsoft/graphrag) | Hierarchical global synthesizer for thematic and cross-corpus questions, preferably offline or asynchronous. |
| [Data-Juicer](https://github.com/datajuicer/data-juicer) | Composable multi-format preparation and streamlining without imposing destination tables. |
| [PageIndex](https://github.com/VectifyAI/PageIndex) | Structure-aware document navigation using layout trees instead of a dense-vector-only design. |

Optional integrations are detected through `python -m synapse capability`; local implementations keep the proof runnable when external engines or credentials are unavailable.

---

## Control-plane guardrails

### Budgeted routing

The router minimizes cost and latency while keeping confidence above a target:

```text
Minimize: αVc + βVl  subject to  Cf ≥ T
```

Information Density Factor:

```text
IDF = evaluated predicates / total token count
```

- **High density (IDF ≥ 0.75):** use local graph/entity paths and reranking; avoid unnecessary long-context calls.
- **Low density (IDF < 0.25):** use structure-aware leaf retrieval and selective synthesis.
- **Budget exhausted:** return a partial answer with an option to continue as a deeper job.

### Conflict-aware truth

Conflicts are retained, not discarded at ingestion. Query-time ranking uses:

```text
Wv = (Ar × e^(-λ·Δt)) + Lp
```

where `Ar` is source authority, `Δt` is elapsed time, and `Lp` is lineage proximity.

The system supports scalar clashes, temporal supersession, domain overlap, compatible multi-values, and explicit human pins. If no human decision exists, the answer surfaces uncertainty and competing evidence rather than fabricating consensus.

### ABAC propagation

Access rights follow the data block into every derivative:

```text
Derived Fact ACL = ACL₁ ∩ ACL₂ ∩ ... ∩ ACLₙ
```

Unauthorized derived nodes are filtered before prompt construction, not merely redacted after generation.

---

## Canonical data contracts

The semantic plane is built around stable, machine-readable contracts in `docs/schemas/`:

```text
RawObject → Episode → Entity → Fact → Conflict → Claim
```

- `RawObject` anchors immutable bytes, source, hash, timestamp, and ACL tags.
- `Episode` groups raw objects with domain and preparation lineage.
- `Entity` represents a real-world node with aliases and external identifiers.
- `Fact` stores a predicate, value, confidence, and evidence references.
- `Conflict` preserves competing facts and its resolution status.
- `Claim` is a query-time answer with supporting facts, citations, confidence, and uncertainty.

Every derived result must remain traceable to its source material and extraction version.

---

## What is proven in this repository

The current implementation extends the PDF’s architecture with a healthcare-first proof and a second-domain generalization test:

- **Healthcare:** `Patient`, `Doctor`, `Appointment`, `Treatment`, and `Billing` across the staged hospital-management data, including a complete multi-hop join.
- **Banking:** `AccountHolder`, `Account`, and `Transaction`, including deliberate same-name collisions that remain distinct under `strict_identity`.
- **HL7v2:** scoped `ORU^R01` parsing with message-declared separators and cross-format patient convergence.
- **FHIR:** partial `Bundle` parsing for `Patient` and `Observation` resources with local reference resolution.
- **Sense board:** generic RAW → MEANING → CONFLICTS → ASK → EMIT flow across domains.
- **Domain-pack contract:** L1 ontology, extraction guards, optional authority data, sample data, and tests remain outside domain-blind core paths.

The proof is architectural and local. It does not claim petabyte-scale performance, production CDC coverage, or healthcare-grade identity namespaces without further work.

---

## Prototype roadmap from the architecture specification

| Phase | Outcome |
|---|---|
| 0. Foundation | Lock contracts, architecture decisions, and validation scenarios. |
| 1. Ingestion | Land raw streams with hashes, lineage, preparation versions, and ACL tags. |
| 2. Semantic memory | Extract temporal entities, facts, and conflicts through the graph layer. |
| 3. Query experience | Provide a cited, budget-aware Sense board and query interface. |
| 4+. Platform maturity | Add stronger ER, adjudication, ABAC, evaluation gates, CDC, global synthesis, and BI materialization. |

The original validation path is infrastructure and operational incidents: deployment systems can report success while clusters report crash loops and engineers report rollbacks in chat. The current healthcare and banking work proves the same semantic core can absorb multiple domains and formats before that broader incident corpus is expanded.

---

## Quick start

```powershell
python -m unittest discover -s tests -t .
python scripts/smoke_banking_join.py
python -m synapse serve --host 127.0.0.1 --port 8787 --db .data/sense.db
```

Open `http://127.0.0.1:8787/` to use the Sense board.

Useful proof scripts:

```powershell
python scripts/smoke_hospital_full_chain.py
python scripts/smoke_banking_join.py
python scripts/smoke_hl7_join.py
python -m synapse capability
```

Optional engine dependencies:

```powershell
python -m pip install -e ".[engines]"
```

Keep secrets in local `.env` files. See `docs/SETUP_DECISIONS.md`.

---

## Design boundaries

- Synapse is not an OLTP replacement or a sub-10ms transactional store.
- It is not a promise of perfect truth without authority ownership and human governance.
- It is not “LLM over a lake” and not a single embedding store for everything.
- Graph, global synthesis, and deep reasoning may be eventual or asynchronous.
- Raw data remains the rebuild root; derived views can be materialized for BI when a contract stabilizes.

## Further reading

- `docs/ORG_WIDE_SEMANTIC_DATA_CORE.md` — full enterprise architecture and H1–H16 register
- `docs/ADRs_H1_H16.md` — subsystem decisions for each production hole
- `docs/DOMAIN_PACK_CONTRACT.md` — platform/domain boundary
- `docs/VISUAL_SENSE_PROOF.md` — Sense-board evidence
- `management/master_plan.md` — current implementation narrative
- `management/Features.md` — domain-pack feature inventory
- `management/Road_map.md` — sequenced delivery plan
- `docs/Project_Synapse_Master_Architecture_By_Gemini.pdf` — source architecture specification
