# Explore View — Research & Plan
**2026-07-21 · Research/plan only, no code changes in this pass, per explicit instruction ("execution later")**

## 0. The problem statement, precisely

The user's own attempt: *"what data do we have in all data sources and what are the fields
which are the same data..."* against entity name `"Lab Data"` → `Entity not found`.

The failure isn't the 404. It's that the platform's front door for "I don't know what's in
here" is a text box that requires *already knowing the answer* (an exact entity name) to get
a response. That inverts schema-on-read's own premise: schema-on-read means the *shape* of
the data isn't fixed in advance and the consumer discovers it by looking, not by declaring it
up front. An entity-name-only query box is schema-on-write UX bolted onto a schema-on-read
backend.

This document is split in two, per the user's request, kept visibly separate:
- **Part A — Knowledge base**: the general principles of data-discovery UX and why they hold,
  reasoned from first principles (HCI/IR fundamentals — faceted navigation, progressive
  disclosure, information scent), not from unverifiable recall of specific competitor
  products. Where a named system is mentioned, it's as an illustrative pattern, not an
  asserted product-feature claim.
- **Part B — Plan**: grounded in an audit of what Synapse's store/API *already compute*, so
  the design isn't generic — it's sized to what's genuinely new work versus what's free reuse.

---

## Part A — Knowledge base: how "explore an unfamiliar dataset" gets solved

### A.1 The core asymmetry: search vs. browse

Two different cognitive starting points require two different UI entry points:
- **Search** — the user has a name, a term, a specific fact in mind, and wants to jump
  straight to it. Precondition: the user can *articulate* what they want. A text box is the
  right tool here.
- **Browse / explore** — the user does not yet know what exists, and the goal is to *build*
  a query by narrowing down, not to *execute* one. Precondition: none — the system must offer
  an entry point that requires zero prior knowledge of the data's contents.

The mistake Synapse made was serving only the first mode and treating it as if it covered
the second. They are not two skins on the same feature — they solve different problems and
need different affordances. The current `/v1/ask` and `/v1/query` (both `entity_name`-keyed)
are legitimately correct for mode 1. Nothing about mode 1 needs to change. What's missing is
mode 2, standing on its own.

### A.2 Progressive disclosure and "summary before search"

The well-established pattern (present in file browsers, database schema browsers, log
explorers, and BI tools alike) is a funnel, not a single screen:

1. **Orient**: show the shape of the whole dataset at a glance — what *kinds* of things are
   here, how many of each, from which sources. No query typed yet.
2. **Narrow**: let the user pick a kind (an entity type, a source, a domain) and see a
   representative sample — names, a few fields — of what's inside it.
3. **Drill**: let the user open one specific thing and see everything known about it (its
   facts, its provenance, its conflicts) — this is where mode 2 hands off to mode 1's existing
   machinery (entity lookup), not a competing implementation of it.

Each step only requires acting on what the *previous* step displayed — never requires typing
a name pulled from nowhere. That's the concrete, checkable definition of "zero prior
knowledge required": at every step, the affordance is a click on something already rendered,
not a blank input.

### A.3 Faceted navigation as the browsing primitive

Faceted search/browse (a foundational IR/HCI pattern, not any one vendor's invention) works by
exposing the *independent dimensions* along which items in a collection vary — type, source,
time, status — as clickable filters, and showing live counts per facet value. Two properties
make it fit here specifically:

- **It's exactly what a heterogeneous, schema-on-read store naturally has**: entity_type,
  source_system, ACL domain, and (per Fact) predicate/path are already independent axes on
  every record in Synapse's store. Faceting is not a new capability bolted on top; it's a
  presentation of axes the data already carries.
- **Counts are the "information scent"** (the HCI term for cues that tell a user whether a
  path is worth following before they commit to it). "LabResult (612)" tells the user more,
  and costs them less, than an empty search box ever could — it converts "I don't know what
  to ask" into "I now know there are 612 of these, let me look at a few."

### A.4 Schema profiling — the "what fields exist, and which are shared" ask

The user's specific unmet ask — *fields that are the same across data sources* — is a known,
solved shape of question in data-catalog and log-analytics tooling: profile each source's
observed field/key set, then compute overlaps. It's a static, deterministic computation
(set operations over per-source key vocabularies), not a semantic or LLM question. That
matters directly for `[[Claude_Instructions.md]]`'s "no freeform predicates" and residual-LLM
fabrication discipline established earlier this session: this specific ask should be answered
the same way — as a pure aggregation over already-observed structure, with **no LLM in the
path**. Narrating "here's what's in your data" via an LLM would silently reintroduce the exact
failure mode (fabricated claims about data that isn't really there) that the extraction-engine
rework spent this whole session eliminating. The Explore view must be a renderer over
computed aggregates, full stop — not a summarizer.

### A.5 Sampling, not the full list

At scale, "browse everything" degrades into "scroll forever," which is not actually more
discoverable than a search box — it just moves the burden from typing to scrolling. The fix
used everywhere this pattern appears (file pickers, catalog browsers, log explorers) is:
show counts for the whole, but only a small representative sample (5–10) of instances per
group, with a path to go deeper (search-within-type, or drill to see all). This keeps the
orient step O(number of *kinds*), not O(number of *records*) — which is what actually makes
it usable against thousands of entities instead of only against small demo datasets. This
directly matters for anticipating variation per `[[Claude_Instructions.md]]`: the view must
not be designed assuming New Data's current ~100s-of-rows scale is representative of all
future data.

### A.6 Drill-down must reuse the existing single-entity machinery, not fork it

Once a user picks one entity from a sample, "show me everything about it" is *exactly* what
`/v1/history` and the entity-lookup path of `/v1/ask` already do — full timeline, sources,
ACL-filtered facts, open conflicts. Building a separate rendering path here would duplicate
logic and risk the two views drifting out of sync (e.g., ACL filtering fixed in one path but
not the other). The correct design is: Explore's drill-down is a thin UI action that calls the
same endpoints Ask already calls, pre-filled with the entity name the user just clicked —
never re-implemented.

### A.7 Anti-pattern to avoid: LLM-narrated "data storytelling"

It's tempting to have an LLM look at the aggregate stats and write a paragraph ("Your data
covers 120 patients across three interoperability formats..."). Rejected for this session's
established reason: any LLM in a path that asserts facts about the data must be provably
bounded, and a general "describe this dataset" prompt has no bounded predicate vocabulary to
constrain it against — it's exactly the shape of prompt that produced the 516 fabricated
facts this session already had to eliminate. Explore stays pure aggregate rendering: counts,
lists, and links, no generated prose asserting facts.

---

## Part B — Plan: sized against what Synapse already computes

### B.1 Codebase audit — what already exists (verified by reading the source this pass)

| Need | Already computed? | Where |
|---|---|---|
| Entity type + count breakdown | Entities carry `entity_type` directly; `/v1/entities` already returns the full ACL-filtered list | `synapse/store.py` `Entity` model; `synapse/api.py:548` `/v1/entities` (already applies `filter_entities`) |
| Sample entity names per type | Same `/v1/entities` payload, just needs grouping by `entity_type` and truncation to N | same endpoint, group client- or server-side |
| Sources actually loaded, per domain | `SemanticStore.known_acl_domains()` + raw object `source_system`/`acl_tags` | `synapse/store.py:138` |
| "What fields exist per source, and which are shared across sources" | **Already computed, just not exposed.** `DriftDetector.baselines[source].keys` is exactly a per-source observed-key-set profile; "shared fields" is a set-intersection over `baselines[*].keys` | `synapse/drift.py` `SourceShape.keys`, `DriftDetector.baselines` |
| Populated predicate vocabulary (not the theoretical ontology list, the *actual* one in use) | `Fact.predicate` on every landed fact; group by `entity_type` and count | `synapse/store.py` `self.facts` |
| Domain-aware "what kind of data is this" headline | Already built this session | `synapse/api.py` `_dynamic_story` |
| Duplicate/near-duplicate entity signal (useful as an "issues to know about" facet) | `ER.suggest_merges()` | `synapse/api.py:577` `/v1/er/suggestions` |
| Drill-down into one entity (full facts/timeline/conflicts, ACL-filtered) | Already correct and in production use — reuse, don't refork | `/v1/history`, `/v1/ask` (entity_lookup intent) |
| Graph neighborhood for a chosen entity (optional secondary drill view) | `/v1/graph?entity=` | `synapse/api.py:579` |

**Conclusion of the audit**: there is no missing primitive. Every number Explore needs to show
is either already computed (drift baselines, known domains, dynamic_story) or a one-pass
`groupby`/`Counter` over `store.entities.values()` / `store.facts.values()` — data structures
that already exist and are already ACL-filterable via the existing `filter_entities` /
`filter_facts` helpers. This is a UI-and-one-aggregation-endpoint job, not a new subsystem.

### B.2 What's net-new

1. **One new read endpoint**, e.g. `GET /v1/explore` (ACL-filtered via the existing
   `_principal_from_query` + `filter_entities`/`filter_facts` helpers already used by
   `/v1/entities` and `/v1/conflicts` — no new ACL logic needed), returning:
   ```json
   {
     "entity_types": [
       {"type": "Patient", "count": 120, "samples": ["Jane Doe", "John Roe", "..."]},
       {"type": "LabResult", "count": 690, "samples": ["..."]}
     ],
     "sources": [
       {"source_system": "LIS-PatientMaster", "acl_domain": "domain:clinical",
        "object_count": 120, "observed_fields": ["patientid","fullname","dob", "..."]}
     ],
     "shared_fields_across_sources": [
       {"field": "patientid", "sources": ["LIS-PatientMaster", "Middleware-RawResults"]}
     ],
     "predicate_vocabulary": [
       {"entity_type": "Patient", "predicate": "date_of_birth", "fact_count": 118}
     ],
     "open_issues": {
       "conflict_count": 100,
       "er_suggestion_count": 4
     }
   }
   ```
   This is a straight aggregation function (like `_dynamic_story`, same shape of work), not a
   query planner — no natural-language parsing, no LLM.

2. **`DriftDetector` wiring — confirmed, not just assumed.** `session.drift` is a
   `DriftDetector` instance created once per session (`synapse/session.py:154`); `observe_all()`
   is only invoked on-demand today, exclusively inside the existing `/v1/drift` handler
   (`synapse/api.py:527`) and the CLI's drift command — it does not run automatically on
   ingest. `/v1/explore` must call `session.drift.observe_all()` itself before reading
   `session.drift.baselines`, the same way `/v1/drift` already does. Cheap (regex scan over
   already-landed raw payloads), no new wiring required — just don't assume the baselines are
   already fresh when `/v1/explore` is hit.

3. **Frontend**: a new Step-1-adjacent (or new nav tab) "Explore" panel:
   - Cards per entity type (name, count, 5 sample names as clickable chips).
   - Clicking a sample name pre-fills Ask's existing entity box and jumps straight into the
     *existing* `/v1/history`/`/v1/ask` drill-down — no new detail-rendering code.
   - A "Sources" panel listing source_system → observed fields, with shared-field overlaps
     visually grouped (e.g., a field appearing in 3+ sources gets a "shared across N sources"
     badge) — directly answers the user's original unmet question.
   - An "Issues" panel surfacing open conflict count and ER-suggestion count as entry points
     into the existing `/v1/conflicts` and `/v1/er/suggestions` views (already built).

### B.3 Explicitly deferred (not part of this pass)

- **The "discovery-intent" fallback inside `/v1/ask`** (teaching the NL query router to
  recognize aggregate/survey-shaped questions like "what data do we have" and answer from
  the same aggregates instead of 404ing on entity lookup) — this was floated earlier in the
  session as option 2 alongside Explore. Per today's redirect to research-then-plan, and per
  the advisor's read of the ask, this stays out of scope for the current plan: Explore alone
  already resolves the user's concrete failure (no need to *guess* a question anymore, since
  there's now somewhere to look first), and folding NL-intent classification in now would
  mix a UI-and-aggregation change with a query-understanding change. Worth a follow-up plan
  once Explore ships and it's clear whether users still reach for the Ask box first out of
  habit.
- Any LLM-generated narrative summary of the dataset (see A.7 — deliberately rejected, not
  just postponed).
- Time-based/versioned exploration (e.g., "what did the data look like last week") — no
  evidence yet this is needed; the store doesn't currently version aggregate snapshots.

### B.4 Why this satisfies the original complaint, checked step by step

Walking the exact scenario that failed: user wants to know "what do we have and what
overlaps" without knowing an entity name in advance.

1. Open Explore (no input required) → sees entity type cards with counts, e.g. `Patient (120)`,
   `LabResult (690)`, `Doctor (14)` — this alone already answers "what data do we have."
2. Sees Sources panel → `LIS-PatientMaster`, `HL7-Interface`, `FHIR-Interface`, `Middleware-*`
   with their observed fields and which fields overlap — this answers "what fields are the
   same across sources," the literal unmet question.
3. Clicks a sample `Patient` name → existing entity drill-down opens (facts, conflicts,
   sources) — this is where "now I know a name" naturally begins, handing off to the
   already-correct `/v1/ask`/`/v1/history` path.

No step requires typing a name the user doesn't already have. That is the concrete bar the
advisor set, and it's met at every step, not just the entry point.

### B.5 Suggested execution phasing (for when the user authorizes coding)

1. Confirm `DriftDetector` observation wiring (the one open question in B.2.2) — read-only
   investigation, ~10 min.
2. Add the `/v1/explore` aggregation function + endpoint, mirroring `_dynamic_story`'s
   existing style and test pattern (`tests/test_dynamic_story.py` is a direct template).
3. Add tests: empty store → empty-but-well-formed payload (not an error); multi-source
   store → correct shared-field computation; ACL scoping → a `domain:banking`-only principal
   must not see `domain:clinical` entity types/sources (reuse the existing
   `filter_entities`/`filter_facts` test patterns already in the suite).
4. Frontend Explore panel wired to the new endpoint, drill-down reusing existing Ask/History
   JS calls.
5. Re-test end-to-end against the live New Data-loaded store (same "boot up and drive it as a
   user" discipline used earlier this session), not just unit tests.

No step in this phasing requires an LLM call, a new ontology concept, or a new ACL rule —
consistent with `[[Claude_Instructions.md]]`'s constraints and with keeping this additive to,
not a rewrite of, the existing Ask/History code paths.
