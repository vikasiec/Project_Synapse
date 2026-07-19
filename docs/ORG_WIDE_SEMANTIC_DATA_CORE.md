# Project Synapse — Org-Wide Zero-ETL Semantic Data Core

**Status:** Architecture thesis / hole-plugging blueprint (no runtime simulation)  
**Extends:** `Zero_ETL_Semantic_Data_Blueprint.pdf`  
**Goal:** Determine whether an organization-wide, discrepancy-tolerant, schema-on-read data system is **doable with the right infra and effort** — and specify what “complete” looks like so this can become a credible **future of data management** design.

---

## 0. What We Are Actually Trying to Prove

We are **not** (yet) proving runtime performance on petabytes. We are proving **architectural completeness**:

| Question | How we answer without full infra |
|---|---|
| Can one system accept *any* org data shape? | Data plane contracts + ingestion adapters + discrepancy model |
| Can answers stay trustworthy at scale? | Determinism layers, citations, eval, confidence gates |
| Can it be secure multi-tenant / multi-domain? | ACL/ABAC model on raw blocks + derived views |
| Can cost/latency stay bounded? | Tiered retrieval, caches, budgeted query plans |
| Can it evolve without ETL rewrites? | Schema-on-read + versioned ontologies + idempotent reprocess |
| Is it *doable*? | Explicit capability matrix + effort model + phased maturity |

**Success for this phase of work:** every production hole is named, owned by a subsystem, and has a design-level mitigation — not a hand-wave.

---

## 1. Vision at Organization Scale

### 1.1 Thesis (refined)

Traditional warehouses force **premature agreement** on schema across teams that never fully agree. Org-wide data is:

- **Heterogeneous** — OLTP DBs, SaaS exports, logs, tickets, PDFs, email, metrics, events, spreadsheets, APIs  
- **Discrepant** — same entity, different IDs, conflicting attributes, stale copies, partial truth  
- **Politically multi-owner** — finance, eng, sales, legal each “own” a slice  
- **Consumed by mixed clients** — humans, BI, agents, workflows, compliance audits  

**Synapse thesis:** Store raw truth with lineage; derive **semantic views on read**; maintain a **living graph of entities, facts, and conflicts** rather than a single cleaned table as the only truth.

> **Naming discipline:** This is **minimal, reversible prep + schema-on-read**, not literally zero work. “Zero-ETL” means *zero forced warehouse schema as the price of admission*, not zero transformation.

### 1.2 What “org-wide” means (design targets)

| Dimension | Design target (order-of-magnitude) |
|---|---|
| Domains | 10–50 business domains (CRM, billing, infra, HR, support, …) |
| Source systems | 50–500 systems / connectors |
| Object volume | 10^8–10^11 objects / events over retention window |
| Query consumers | Interactive agents, batch synthesis, audit export |
| Latency classes | Hot (seconds), warm (tens of seconds), cold (minutes, async jobs) |
| Consistency | Eventual for graph; strong lineage back to raw; explicit conflict states |
| Tenancy | Org + BU + team + user ABAC; regulated partitions |

These are **sizing assumptions for architecture**, not SLAs we can simulate today.

### 1.3 Non-goals (for honesty)

- Not a replacement for OLTP systems of record  
- Not the first place for sub-10ms transactional reads  
- Not a guarantee of perfect truth without human governance for regulated numbers  
- Not “one embedding store for everything”

Synapse sits **above** systems of record as the **semantic integration + reasoning plane**.

---

## 2. Design Principles (Org-Wide)

1. **Raw is sacred** — Immutable landing zone; never mutate source bytes. All intelligence is derived.  
2. **Lineage is mandatory** — Every claim points to source block(s) + extraction version + time.  
3. **Discrepancy is first-class** — Conflicts are stored and queryable, not silently “resolved away.”  
4. **Schema emerges, then stabilizes** — Soft ontology early; governed contracts only where consumers demand them.  
5. **Tiered intelligence** — Cheap local models/rerankers by default; large LLMs selectively.  
6. **Budgeted reasoning** — Every query has a cost/latency budget and a degraded answer path.  
7. **Security follows the block** — ACL/ABAC tags travel with raw and all derivatives.  
8. **Reprocess is normal** — Better extractors re-run over history without dual-write nightmares.  
9. **Eval is product** — Continuous answer quality gates; no silent regression.  
10. **Human correction is a write path** — Experts can pin, merge, or reject facts; those are higher-trust edges.

---

## 3. Reference Architecture (Full Stack)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONSUMER PLANE                                       │
│  Agents │ NL Query API │ Semantic SQL/View API │ Audit Export │ Workflows  │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────────┐
│                         CONTROL PLANE                                        │
│  Query Router │ Budget Governor │ Policy Engine (ABAC) │ Ontology Registry  │
│  Job Orchestrator │ Eval Service │ Cost Metering │ Feature Flags            │
└───────┬─────────────────┬─────────────────┬─────────────────┬───────────────┘
        │                 │                 │                 │
┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐
│ RETRIEVAL     │ │ GRAPH MEMORY  │ │ GLOBAL        │ │ STRUCTURE     │
│ Hot path      │ │ Graphiti-like │ │ SYNTHESIS     │ │ NAVIGATOR     │
│ caches, keys  │ │ temporal KG   │ │ GraphRAG-like │ │ PageIndex-like│
└───────┬───────┘ └───────┬───────┘ └───────┬───────┘ └───────┬───────┘
        │                 │                 │                 │
┌───────▼─────────────────▼─────────────────▼─────────────────▼───────────────┐
│                         SEMANTIC DATA PLANE                                  │
│  Episode store │ Entity/Fact store │ Conflict store │ Community summaries   │
│  Doc trees │ Embeddings (optional, domain-scoped) │ Derived views (versioned)│
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────────────┐
│                         INGEST & PREP PLANE                                  │
│  Connectors │ CDC/Export │ Data-Juicer-like ops │ PII classifiers │ Taggers  │
│  Idempotent episode builders │ Quality signals │ Schema drift detectors      │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────────────┐
│                         RAW LANDING ZONE (System of Record for bytes)        │
│  Object storage (WORM/versioned) │ Catalog │ Checksums │ Source metadata     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ▲
                     Source systems (OLTP, SaaS, logs, files, streams)
```

### 3.1 Mapping original PDF pieces → enterprise roles

| Original piece | Enterprise role | Scale notes |
|---|---|---|
| **Data-Juicer** | Composable prep operators (not a warehouse) | Domain packs of operators; sandboxed; versioned |
| **Graphiti** | Continuous temporal knowledge graph | Partition by domain/tenant; episode backpressure; entity resolution layer |
| **GraphRAG** | Offline/async global community synthesis | Not on interactive path; scheduled or query-triggered jobs |
| **PageIndex** | Structure-first retrieval for long docs | Per-corpus trees; avoids global dense-vector monoculture |

**Additional subsystems the PDF did not include (required at org scale):**

| Subsystem | Why required |
|---|---|
| **Connector & CDC fabric** | Org data is continuous, not one-shot dumps |
| **Entity resolution (ER)** | Same customer/product/employee across systems |
| **Conflict & discrepancy engine** | Explicit multi-source truth management |
| **Ontology registry** | Soft → governed types; multi-domain vocabulary |
| **Query router + budget governor** | Prevents “run all models every time” cost blowups |
| **Policy / ABAC engine** | Row/block security without classical tables |
| **Eval & regression harness** | Only way schema-on-read is trustworthy |
| **Human adjudication UI/API** | Correct the graph; pin canonical facts |
| **Observability & FinOps** | Token $, latency, cache, extraction error rates |
| **Semantic view materializer** (optional) | Cache stable answers as governed views for BI |

---

## 4. Data Model: Handling Variety and Discrepancies

### 4.1 Core objects

```text
RawObject {
  object_id, source_system, source_uri, content_hash,
  ingested_at, bytes_ref, media_type,
  acl_tags[], sensitivity, retention_class, lineage_parent?
}

Episode {
  episode_id, raw_object_ids[], domain, time_span,
  prep_pipeline_version, text_or_structured_payload_ref,
  quality_signals{}, acl_tags[]
}

Entity {
  entity_id, entity_type, canonical_name?,
  aliases[], external_ids[{system, id}],
  trust_score, status  // active | merged | deprecated
}

Fact {
  fact_id, subject_entity_id, predicate, object,
  valid_from, valid_to?,  // temporal
  confidence, extractor_version,
  evidence_refs[]  // → raw/episode spans
}

Conflict {
  conflict_id, subject_entity_id, predicate,
  competing_facts[], status,  // open | resolved | accepted_plural
  resolution? { method, chosen_fact_id?, adjudicator, reason }
}

Claim (query-time) {
  statement, supporting_fact_ids[], raw_citations[],
  confidence, uncertainty_notes[], policy_filtered?
}
```

### 4.2 Discrepancy policy (first-class)

Org-wide systems **must not** silently pick a winner.

| Pattern | Behavior |
|---|---|
| **Compatible multi-value** | e.g. multiple emails → keep set |
| **Contradictory scalar** | e.g. two annual revenues → `Conflict` open; queries surface both + sources |
| **Temporal supersession** | newer CDC wins for operational state; history retained |
| **Authority ranking** | registry: for `legal_entity_name`, Legal system > CRM > free text |
| **Human pin** | adjudicator sets `resolved` with audit trail |
| **Accepted plural** | product deliberately keeps multiple truths (e.g. regional names) |

**Query default:** return *best-effort synthesis with uncertainty*, never fake consensus.

### 4.3 Entity resolution at scale

Pipeline stages:

1. **Blocking** — cheap keys (email domain, tax id hash, normalized name n-grams)  
2. **Pairwise scoring** — local model / rules  
3. **Clustering** — merge candidates within domain + cross-domain links  
4. **Human review queues** — high-impact entity types only  
5. **Stable IDs** — merges create redirect edges; never delete history  

Without ER, Graphiti-style graphs become **duplicate islands** and org-wide intelligence fails.

### 4.4 Variety: connector taxonomy

| Class | Examples | Ingest mode | Prep needs |
|---|---|---|---|
| Structured OLTP | Postgres, SaaS CRM | CDC / snapshot | Light typing, PII tag |
| Semi-structured | JSON events, webhooks | Stream | Schema drift detect |
| Logs / traces | App, security | Stream + sample | Slice, redaction |
| Documents | PDF, slides, contracts | Batch | PageIndex trees |
| Communications | Tickets, email meta | Sync | Thread reconstruction |
| Metrics | TSDB, billable usage | Rollup + ref | Align to entities |
| Tribal / messy | Spreadsheets, notes | Drop zone | High discrepancy rate |

Each class has a **connector contract**: auth, rate limits, watermark, schema-drift signal, ACL default tags.

---

## 5. Plugging Every Hole (Closed-Loop Design)

### 5.1 Holes from the original PDF — closed designs

#### H1. Deterministic precision

**Risk:** LLM field variance on numbers, IDs, dates.  

**Design:**
- **Two-path extraction:** (A) deterministic parsers for known formats; (B) LLM only for residual free text  
- **Structured generation** with JSON schema / constrained decoding (Instructor-class)  
- **Verifier stage:** range checks, unit checks, cross-field consistency  
- **Numeric claims require evidence span** or marked `low_confidence`  
- **Regulated predicates** (revenue, headcount, PII flags) require `authority_source` or human pin  

#### H2. Inference-time latency

**Risk:** Multi-agent reasoning over raw data → multi-minute UX.  

**Design:**
- **Latency classes:** interactive / standard / deep (async job + webhook)  
- **Aggressive caching:**  
  - semantic query keys  
  - community summaries (GraphRAG offline)  
  - entity cards (materialized)  
  - doc tree routes (PageIndex)  
- **Speculative precompute** for top-N dashboards and on-call runbooks  
- **Early-exit retrieval:** stop when confidence ≥ threshold and budget remains  

#### H3. Token economics

**Risk:** Linear cost with unparsed context.  

**Design:**
- **Never** default to full-corpus long context  
- **Tiered models:** local embed/rerank → mid LLM → large LLM only for synthesis  
- **Hard budgets** per tenant/query class (tokens, $ , wall time)  
- **Result reuse:** similar queries hit claim cache with freshness TTL  
- **Domain partitioning** so retrieval sets stay bounded  

#### H4. Access control & ACLs

**Risk:** Dynamic extraction bypasses row-level security.  

**Design:**
- **Tag-at-ingest:** every `RawObject` carries ACL/ABAC attributes  
- **Mandatory propagation:** Episode, Fact, Summary inherit *intersection* of source ACLs  
- **Query-time policy filter** before retrieval and again before response  
- **No cross-ACL aggregation** unless policy allows (prevents inference leaks via counts)  
- **Crypto optional:** envelope encryption per sensitivity class; key per tenant  
- **Audit log:** who retrieved which blocks for which claim  

### 5.2 Additional holes required for org-wide future-state

#### H5. Schema drift & source evolution

**Design:** catalog watches; drift events → reprocess jobs; soft types expand; breaking changes create new predicate versions, not silent overwrite.

#### H6. Idempotency & reprocessing

**Design:** content-hash + pipeline-version define episode identity; facts are versioned; re-run supersedes via temporal edges; no duplicate spam.

#### H7. Freshness / CDC correctness

**Design:** watermarks per connector; `as_of` query parameter; late-arriving data creates temporal corrections, not silent past rewrites without lineage.

#### H8. Multi-domain ontology chaos

**Design:** **layered ontology**  
- L0: universal (Person, Org, Asset, Event, Document)  
- L1: domain packs (Billing, Infra, Support)  
- L2: team extensions (soft, low trust until promoted)  

Registry governs promotion. Cross-domain queries use L0 + mapped L1 links.

#### H9. Global vs local retrieval conflict

**Design:** **Query Router** decision table:

| Intent signal | Primary path | Secondary |
|---|---|---|
| “What is X?” entity lookup | Graph entity card | PageIndex for source docs |
| “What changed for X?” | Temporal graph | Raw episodes in window |
| “Top themes / failure modes” | GraphRAG communities (async if cold) | Sampled evidence |
| “Find in this 400-page contract” | PageIndex | Sparse keyword |
| Hybrid / ambiguous | Parallel fan-out under budget | Rerank + fuse |

#### H10. Evaluation & regression

**Design:**
- Golden question sets per domain  
- Metrics: citation precision, factual agreement with authority sources, conflict honesty rate, refusal correctness  
- CI gate on extractor/model upgrades  
- Shadow traffic compare before promote  

#### H11. Human-in-the-loop governance

**Design:** adjudication queues for ER merges, conflict resolution, ontology promotion; all actions audited; higher trust weight for human-pinned facts.

#### H12. Observability & FinOps

**Design:** RED metrics for query path; extraction error rates; $ per 1k queries; cache hit ratios; per-tenant budgets and kill switches.

#### H13. Disaster recovery & retention

**Design:** raw landing zone is backup root; graph rebuildable from raw + pipeline versions; retention/legal hold on raw and derivatives; right-to-erasure cascades via lineage.

#### H14. Prompt / model supply-chain risk

**Design:** pinned model versions; offline-capable small models for classified partitions; no raw sensitive blocks to unapproved endpoints; redaction operators pre-egress.

#### H15. Write-back & activation

**Design:** Synapse is read-mostly; optional **action bus** (create ticket, update CRM) with human approval for high risk; never silent mutation of systems of record.

#### H16. Materialized “escape hatch” for classical BI

**Design:** when a semantic view stabilizes (high trust, high use), materialize to warehouse tables **as a product of the graph**, not the other way around. Schema-on-read can *emit* schema-on-write where justified.

---

## 6. Query Lifecycle (End-to-End)

```text
1. Authenticate + load user/tenant policy context
2. Parse intent → query class + budget class
3. Policy-scoped retrieval plan (router)
4. Parallel fetch under budget:
     - entity/fact graph
     - doc trees
     - community summaries
     - optional vector/keyword
5. Conflict-aware fusion (never hide open conflicts for regulated predicates)
6. Structured answer + citations + confidence + gaps
7. Cache claim (TTL, acl-bound)
8. Emit telemetry + optional human feedback signal
```

**Failure modes (designed):**
- Budget exhausted → partial answer + “continue deep job”  
- Policy blocks evidence → refuse or redacted synthesis  
- Low confidence → escalate / ask clarifying question  
- Open conflict → present both sides with authority ranking  

---

## 7. Security, Privacy, Compliance (Org Baseline)

| Control | Implementation concept |
|---|---|
| ABAC | Attributes on blocks: `domain`, `team`, `region`, `sensitivity`, `legal_hold` |
| Purpose limitation | Query purpose tags for regulated domains |
| Minimization | Retrieval returns least-privilege spans, not whole objects |
| PII | Classifier at ingest; dynamic masking by role |
| Residency | Storage + model endpoints pinned by region partition |
| Audit | Immutable query/extract/adjudication logs |
| Separation | Prod graph ≠ training corpus unless explicitly opted-in |

---

## 8. Doability Assessment (Without Full Simulation)

### 8.1 What “doable” means here

A design is **doable** if:

1. Every critical hole maps to a known subsystem pattern (not research magic)  
2. Open-source + cloud primitives exist for each plane  
3. Effort is decomposable into phases with value at each step  
4. Hard limits are explicit (where humans/governance still required)  
5. Failure modes degrade gracefully  

### 8.2 Capability matrix

| Capability | Feasibility today | Dependency | Residual risk |
|---|---|---|---|
| Multi-format landing + prep | **High** | Object store + operator libs (Data-Juicer class) | Operator sprawl |
| Continuous temporal graph | **Medium-High** | Graphiti-class + managed graph store | Cost of extraction at stream volume |
| Entity resolution org-wide | **Medium** | ER service + human queues | Long-tail identity mess |
| Conflict-aware truth | **Medium** | Custom conflict store + policies | Product/UX complexity |
| Structure-aware doc retrieval | **High** | PageIndex-class / tree index | Less mature than vectors |
| Global theme synthesis | **Medium** | GraphRAG-class offline jobs | Expensive; stale summaries |
| ABAC on unstructured | **Medium** | Policy engine + tag propagation | Inference side-channels |
| Deterministic numeric claims | **Medium** | Hybrid parser + verifier | Never 100% without SoR |
| Interactive latency at scale | **Medium** | Cache + materialization | Deep queries still async |
| Token cost control | **High** if budgets enforced | Router + tiers | Culture of “just ask the big model” |
| Full org single brain day-1 | **Low** | — | Must domain-slice |

**Verdict (architecture-level):**  
**Doable as a multi-year platform** with phased domain rollout.  
**Not doable** as a single big-bang “replace the warehouse next quarter” project.  
**Most doable path:** semantic intelligence plane *alongside* existing warehouses, gradually absorbing integration use cases that ETL handles poorly (messy docs, cross-domain narrative, agent memory, discrepancy surfacing).

### 8.3 Effort model (indicative, not a bid)

| Phase | Scope | Outcome |
|---|---|---|
| **P0 — Paper complete** | This doc family: contracts, gaps closed, ADRs | Shared north star |
| **P1 — Single domain slice** | One domain, 3–5 sources, Graph + PageIndex + eval | Proof of trust loop |
| **P2 — Discrepancy + ER** | Multi-source same entities, conflict UX | Org-data realism |
| **P3 — Multi-domain + ABAC** | Ontology layers, policy, FinOps | Platform shape |
| **P4 — Global synthesis + BI emit** | GraphRAG jobs, materialized views | Warehouse coexistence |
| **P5 — Org default path** | Connectors catalog, self-serve domains | Future of data mgmt claim becomes operational |

Rough order: **platform skeleton months; org-default years** — contingent on team size and source access.

### 8.4 Proofs we *can* do without petabyte infra

1. **Contract completeness review** — every hole has an owner subsystem (this document)  
2. **Threat model** — ACL leak, hallucination, cost runaway, poison graph  
3. **Query router decision tables** — cost/latency envelopes on paper  
4. **Synthetic discrepancy corpora** — small but nasty multi-source conflicts  
5. **Golden-set design** — how we would know success before building  
6. **Failure injection scenarios** — drift, late CDC, contradictory SoRs  
7. **Reference cost model** — tokens/query class × expected QPS (spreadsheet-level)  

These are the **engineering science** of the project until infra exists.

---

## 9. Why This Can Be the Future of Data Management

Classical stack optimized for **known questions on agreed tables**.  
Modern orgs need **unknown questions on disagreed data**, answered by humans *and* agents, with lineage and uncertainty.

| Era | Paradigm | Weakness |
|---|---|---|
| Warehouse | Schema-on-write | Brittle, slow to new questions, context loss |
| Lakehouse | Cheap storage + SQL | Still schema-heavy for meaning |
| Classical RAG | Chunk + embed | Weak global + temporal + conflict handling |
| **Synapse (proposed)** | Raw + temporal graph + structure + conflict + policy | Harder platform; better fit for agentic org cognition |

**Future-state claim (precise):**  
> Organizational data management shifts from “clean once into tables” to “land once with policy and lineage, continuously extract meaning, resolve identity and conflict explicitly, and answer under budget with citations.”

That is a **platform shift**, not a tool swap.

---

## 10. Open Decisions (To Resolve Next)

1. **Primary first domain** for the theoretical deep-dive (e.g. Support+Infra incidents vs Finance)  
2. **Graph store assumption** (managed vs self-hosted; partition strategy)  
3. **How much vector search is allowed** alongside PageIndex (hybrid default?)  
4. **Authority ranking owners** per predicate (data governance RACI)  
5. **Model residency** constraints for your org class  
6. **Coexistence policy** with existing warehouse / lakehouse (parallel forever vs absorb)  

---

## 11. Workstreams Going Forward (No Infra Required)

| Workstream | Deliverable |
|---|---|
| **A. Architecture ADRs** | One ADR per hole (H1–H16) with chosen pattern |
| **B. Canonical data contracts** | JSON schemas for RawObject, Episode, Fact, Conflict, Claim |
| **C. Query router spec** | Intent taxonomy + path selection + budgets |
| **D. Discrepancy playbook** | Conflict types + resolution policies by domain |
| **E. Security model** | ABAC attributes, propagation rules, anti-inference rules |
| **F. Eval blueprint** | Metrics, golden set design, promotion gates |
| **G. Cost & latency envelopes** | Spreadsheet model by query class |
| **H. Phased roadmap** | P0–P5 with exit criteria |
| **I. Threat model** | STRIDE-style on semantic plane |
| **J. Narrative deck** | Exec-ready “future of data management” story |

---

## 12. Bottom Line

- **Org-wide, messy, discrepant data** is the correct target for Synapse — and it forces first-class **entity resolution, conflict storage, ABAC, budgets, and eval**, not just “LLM over a lake.”  
- The PDF’s four open-source pieces are **necessary but not sufficient**; the control plane and discrepancy model are what make it enterprise-real.  
- **Doable:** yes, as a phased platform coexisting with warehouses, if holes above are treated as core product.  
- **Not doable:** as magic zero-work zero-cost zero-governance replacement of all ETL.  
- **Our work now:** plug every hole in design, contracts, and proof methods — so when infra appears, build is assembly, not invention.

---

*Next recommended step: pick workstream A+B (ADRs + data contracts) or a single vertical scenario and walk a full discrepancy-laden query through this architecture end-to-end on paper.*
