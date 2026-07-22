# Grok Graph-First Discovery & ER Watch ‚Äî 2026-07-22

**Authority:** `docs/Graph-First Discovery & Entity Resolution.pdf`  
**Role:** Independent monitor (audit only) while Claude implements  
**Report location:** `workspace_scratch/GROK_GRAPH_FIRST_ER_WATCH_2026-07-22.md`  
**Related prior stream:** Schema-field discovery (Master Spec MG1‚Äì4) in `GROK_MASTER_SPEC_WATCH_2026-07-22.md` ‚Äî **additive second layer**, not a replacement (Claude + user choice stated in commit `5fcd916`)

---

## 0. Spec summary (PDF Major Goal 2)

**Objective:** Replace direct column-to-column comparisons with:

1. **Isolated** sequential extraction per file  
2. **Graph-level** Entity Resolution (ER)  
3. Safe support for large heterogeneous folders (JSON, PDFs, tabular)

### The 4-step Right-Way Pipeline

| Step | Spec engine | Required behavior |
|------|-------------|-------------------|
| **1** Isolated Ingestion & Normalization | Data-Juicer | Folder target ‚Üí **no** cross-file compare at ingest; each file independent; chunk to chronological **Episodes**; normalize bytes ‚Üí standard text |
| **2** Temporal Fact Extraction | Graphiti | Per-episode Entities + Facts; **isolated graph per file**; strict lineage to raw block |
| **3** Cross-System ER | ER engine | Tiered: **(1) Blocking** (email domain, tax-id hash, name n-grams‚Ä¶) ‚Üí **(2) Pairwise** semantic/LLM only inside blocks (e.g. cust_id 123 vs client_num 123 as *person* identity) ‚Üí **(3) Clustering** ‚Üí **CandidateEdges (Merge Candidates)** |
| **4** Curation Canvas | HITL UI | Show **ER Merge Candidates + Conflicts** (not file spiderweb); ACCEPT ‚Üí **SAME_ENTITY_AS** in Ontology Registry **and** merge nodes via **stable ID redirect** |

### Scale claims (spec)

1. Works for 100 spreadsheets or 1,000 PDFs (structure-agnostic Graphiti extract)  
2. Token cost **O(N)** extract once per file; cross-compare is cheap blocking  
3. **Discrepancy integrity:** independent facts ‚Üí **Conflict** (Active vs Suspended), not silent overwrite

---

## 1. Snapshot at monitor start (~11:45 local)

| Field | Value |
|-------|--------|
| Git HEAD | `5fcd916` Graph-First ER + Resolve tab; prior `53a82b6` file/folder ingest |
| Ledger | Rows **51‚Äì52 üü¢ DONE** (ingest + Graph-First layer); 48‚Äì50 residual stream closed earlier |
| New modules | `synapse/entity_matching.py`, `ui/src/views/ResolveView.jsx`, tests |
| Claude framing | Explicit **second curation layer** beside `matching.py` field discovery |

---

## 2. Pipeline alignment matrix

| Spec step | Implementation | Verdict |
|-----------|----------------|---------|
| **1** Isolated ingest / Data-Juicer | Existing: connectors + `IngestionService` land per-file RawObjects; **row 51** `POST /v1/explore/ingest` + `FileIngest.jsx` for browser files. CSV ‚Üí KV-line RawObjects (same as CsvDrop). **Not** a full Data-Juicer chunker for PDFs. | **PARTIAL** ‚Äî independent land OK; PDF/binary folder story not Graphiti-class |
| **2** Graphiti temporal extract | Existing dual-path rule + optional Graphiti push. Entities/facts already per episode with lineage. **Not** ‚Äúpass every episode through Graphiti local model‚Äù as default offline path. | **PARTIAL** ‚Äî graph memory exists; **default extract is rules**, not Graphiti-first as PDF implies |
| **3** Blocking | `entity_matching._name_blocks`: token (‚â•3 chars) sharing per `entity_type` ‚Äî catches ‚ÄúJustin‚Äù/‚ÄúMason‚Äù / ‚ÄúJ. Mason‚Äù. **No** email domain / tax-id / external_id blocking in this new path (though `EntityResolutionService` has ID authority paths elsewhere). | **PARTIAL** ‚Äî name tokens only; PDF examples broader |
| **3** Pairwise scoring | `0.7√óNameSim + 0.3√óCrossSystemBonus` via hashing-vector cosine. **No** LLM pairwise. Doc admits formula is **module design**, not PDF-mandated weights. | **PARTIAL** ‚Äî deterministic stand-in; honest about no PDF formula |
| **3** Clustering | Pairwise CandidateEdges only; no multi-node cluster object | **SIMPLIFIED** ‚Äî documented |
| **4** Curation UI | **Resolve** tab: merge candidates cards, Merge / Not the same | **PARTIAL** ‚Äî merge candidates **yes**; **Conflicts panel no** |
| **4** ACCEPT ‚Üí SAME_ENTITY_AS + ID redirect | Merge uses existing `POST /v1/entities/merge` ‚Üí `er.merge()` (stable redirect + fact rewrite). **Does not** write Ontology Registry `SAME_ENTITY_AS` relationship edge. | **PARTIAL** ‚Äî merge redirect **yes**; registry SAME_ENTITY_AS **no** (conflated field-layer vs entity-layer) |
| Discrepancy integrity | Pre-existing conflict detection remains separate from Resolve UI | **ORTHOGONAL** ‚Äî Conflicts not surfaced on Resolve tab |

---

## 3. Findings (living)

### GF-001 ¬∑ P2 ¬∑ OPEN ¬∑ Dual ‚ÄúMajor Goal 2‚Äù narratives

| Stream | What ‚ÄúMG2‚Äù means |
|--------|------------------|
| Master Spec roadmap | Hybrid **field** scoring `POST /v1/explore/analyze` |
| Graph-First PDF | Graph-first **entity** ER pipeline |

Claude correctly implements Graph-First as a **second layer**. Residual risk: docs/UI language still say ‚ÄúMajor Goal 2‚Äù in two places. Recommend one glossary: **Field Discovery** vs **Entity Resolve**.

### GF-002 ¬∑ P1 ¬∑ OPEN ¬∑ ACCEPT does not write Ontology `SAME_ENTITY_AS`

**PDF Step 4 Result:**  
> ACCEPT ‚Üí writes SAME_ENTITY_AS to Ontology Registry **and** merges via stable ID redirect.

**Code:** Resolve UI only calls `api.mergeEntities` ‚Üí `er.merge()`. No `ontology.accept_relationship(...)`.

**Impact:** Catalog (field relationships) never shows entity merges; institutional memory of entity SAME_ENTITY_AS is only the MERGED entity status + redirect.

**Recommend:** On successful merge, optionally register a `SAME_ENTITY_AS` edge keyed by entity IDs (or document deliberate split: registry = schema fields only; ER merge = entity graph only).

### GF-003 ¬∑ P1 ¬∑ OPEN ¬∑ Conflicts not on Curation Canvas

**PDF:** UI presents **ER Merge Candidates and Conflicts**.

**Code:** ResolveView = merge candidates only. Conflicts remain on legacy Sense board `/`.

### GF-004 ¬∑ P2 ¬∑ OPEN ¬∑ Blocking keys narrower than PDF

PDF examples: email domain, tax-id hash, name n-grams.  
Impl: name tokens ‚â•3 only (plus entity_type prefix). No ID-value or email blocking in `entity_matching.py`.

Cross-system **ID** identity (cust_id 123 = client_num 123 as same person) is **not** what this scorer does ‚Äî it scores **entity names**, after extraction. That may be correct if extraction already created person entities, but the PDF‚Äôs ‚Äúcust_id 123 vs client_num 123‚Äù wording mixes field IDs with entity ER.

### GF-005 ¬∑ P2 ¬∑ OPEN ¬∑ ‚ÄúDismiss / Not the same‚Äù is client-only

`handleDismiss` only sets local React state ‚Äî no REJECT feedback store. Re-load list resurfaces the pair. Field-layer F-026 discipline not mirrored for entity merges.

### GF-006 ¬∑ P2 ¬∑ OPEN ¬∑ Graphiti not the default Step-2 engine

PDF centers Graphiti for entity/fact extraction from text (including PDFs). Platform still primarily **rule extraction** + optional Graphiti. Heterogeneous PDF folders remain out of proven path (ingest is text/CSV/JSON).

### GF-007 ¬∑ P3 ¬∑ NOTE ¬∑ Formula is invent-and-document (acceptable)

No weights in PDF. Claude‚Äôs `0.7/0.3` and thresholds `0.80/0.45` are explicit module design ‚Äî good honesty (module docstring). Demo live score ‚ÄúAcme Corp‚Äù vs ‚ÄúAcme Corp annual‚Äù **0.47** sits barely above floor ‚Äî watch for false positives in large name corpora.

### GF-008 ¬∑ P2 ¬∑ WATCH ¬∑ Justin Mason example depends on token ‚Äúmason‚Äù

Blocking shares `mason`; name cosine may be modest; cross-system bonus +0.3 carries many candidates over 0.45. Unit tests assert candidate surfaces ‚Äî good. No test that **same** person IDs with **different** names still merge (PDF id example).

### GF-009 ¬∑ P3 ¬∑ OPEN ¬∑ `/v1/er/suggestions` vs `/v1/er/merge-candidates`

Two parallel APIs: old exact-name `suggest_merges` (unscoped in GET) vs new scored merge-candidates (ACL-scoped). Resolve uses the new one. Legacy route still ACL-blind for suggestions dump ‚Äî pre-existing risk class.

### GF-010 ¬∑ P2 ¬∑ POSITIVE ¬∑ ACL on merge-candidates

`filter_entities` before generate ‚Äî good. Test proves banking principal sees no clinical-tagged people.

### GF-011 ¬∑ P2 ¬∑ POSITIVE ¬∑ Additive architecture

Does not rip out field discovery. Matches user‚Äôs ‚Äúsecond capability‚Äù choice. Correct product architecture for two specs.

### GF-012 ¬∑ P3 ¬∑ OPEN ¬∑ ui/dist may lag Resolve tab

If production only serves `ui/dist`, confirm rebuild after Resolve tab (dev `/app` with vite may be fine).

---

## 4. VnV-style checklist (inferred from PDF + Claude tests)

| Check | Status |
|-------|--------|
| Justin Mason / J. Mason surfaces as merge candidate | **GREEN** (unit + HTTP tests) |
| Unrelated names drop | **GREEN** |
| Cross-system reason present | **GREEN** |
| ACL hides other domains | **GREEN** |
| ACCEPT merges with redirect | **GREEN** (reuses hardened merge path) |
| ACCEPT writes ontology SAME_ENTITY_AS | **RED / not implemented** |
| Conflicts shown on Resolve canvas | **RED** |
| PDF binary folder extract via Graphiti | **NOT PROVEN** |
| Independent Active vs Suspended ‚Üí Conflict | **Pre-existing platform** ‚Äî not wired to Resolve UI |

---

## 5. File inventory

| Path | Role | Present |
|------|------|---------|
| `docs/Graph-First Discovery & Entity Resolution.pdf` | Authority | YES |
| `synapse/entity_matching.py` | Step 3 scoring | YES (`5fcd916`) |
| `GET /v1/er/merge-candidates` | API Step 3/4 | YES |
| `POST /v1/entities/merge` | ACCEPT merge | YES (pre-existing) |
| `ui/src/views/ResolveView.jsx` | Step 4 UI | YES |
| `POST /v1/explore/ingest` + FileIngest | Folder/files ‚Üí land | YES (`53a82b6`) |
| Conflicts on Resolve | PDF Step 4 | **NO** |
| Ontology SAME_ENTITY_AS on entity merge | PDF Step 4 | **NO** |

---

## 6. Test evidence

Run: `tests.test_entity_matching` + `tests.test_er_merge_candidates_api`  
*(Results filled on first fire ‚Äî see monitor log below.)*

---

## 7. Priority recommendations for Claude (if more work)

1. **GF-002** ‚Äî On merge ACCEPT, write registry edge or document split explicitly in SESSION_HANDOFF.  
2. **GF-003** ‚Äî Surface open Conflicts for the candidate entities on Resolve.  
3. **GF-005** ‚Äî Persist dismiss / negative feedback like field REJECT.  
4. **GF-004** ‚Äî Optional blocking on external_id / email when present on entities.  
5. **GF-006** ‚Äî Don‚Äôt claim Graphiti-first PDF pipeline until default path uses it.  
6. Keep dual-layer glossary clear in UI (Explore = fields, Resolve = entities).

---

## 8. Monitor log (append-only)

### 2026-07-22 ~11:45 ‚Äî Baseline Graph-First audit

- Read PDF (2 pages, full pipeline).  
- Audited commits `53a82b6` (ingest) + `5fcd916` (entity_matching + Resolve).  
- Ledger 51‚Äì52 DONE.  
- Opened findings **GF-001 ‚Ä¶ GF-012**.  
- Continuous watch armed.

---

*Grok continuous watch for Graph-First ER. Updates append below.*

### 2026-07-22 ~11:45 test evidence

Independent re-measure Justin Mason vs J. Mason:
- name_sim (hashing cosine) ò **0.60**
- S_total = 0.7*0.60 + 0.3*1.0 = **0.72** (status candidate)
- Tests: `tests.test_entity_matching` + `tests.test_er_merge_candidates_api` ? **5/5 OK**

Scheduler: 019f886a5e80 every 3m.

### 2026-07-22 ~11:35 +05:30 ó Heartbeat (scheduler 019f886a5e80)

- **Git:** HEAD still `5fcd916` (Graph-First ER + Resolve); prior `53a82b6` ingest. `main...origin/main` clean for tracked code.
- **Dirty/untracked:** only this watch file `?? workspace_scratch/GROK_GRAPH_FIRST_ER_WATCH_2026-07-22.md` (not committed).
- **mtimes:** no new writes under `synapse/`, `ui/src/`, `tests/` since ~11:22ñ11:30; `Active_File.md` 11:28 (ledger mtime only ó no new open Graph-First rows observed this fire).
- **Pipeline re-check:** Steps 1ñ4 status unchanged (PARTIAL / SIMPLIFIED matrix ß2). Dual-layer tension still GF-001 (field `matching.py` Explore vs entity `entity_matching.py` Resolve).
- **Tests:** skipped (no code delta since last 5/5 evidence).
- **Findings:** GF-001ÖGF-012 status frozen; still OPEN on GF-002/003/004/005/006; POSITIVE GF-010/011.
- **Phase 2 / Master Spec gate:** audit-only; no Phase-2 claim. Master Spec MG1ñ4 remain additive field layer; Graph-First is second layer per `5fcd916`.
- **Idle:** Claude not landing new commits this interval.

### 2026-07-22 ~11:38 +05:30 ó Heartbeat (scheduler 019f886a5e80)

- **Git:** HEAD `5fcd916` unchanged; `main...origin/main`; only untracked is this watch file.
- **Code delta:** none under synapse/ui/tests since ~11:20ñ11:22 (entity_matching + Resolve + merge-candidates).
- **Active_File.md:** mtime 11:28 only; no new commits implying ledger Graph-First work this interval.
- **PDF steps 1ñ4 / dual-layer:** no change; GF-001ñ012 frozen.
- **Tests:** skipped (idle).
- **Phase 2 / Master Spec:** audit-only; no gate activity.

### 2026-07-22 ~11:41 +05:30 ó Heartbeat (scheduler 019f886a5e80)

- **Git:** HEAD `5fcd916`; no new commits; porcelain = watch file only.
- **15m mtimes:** watch log + `Active_File.md` (stale 11:28) only ó no synapse/ui/tests writes.
- **PDF / GF-NNN:** unchanged idle.
- **Tests:** skipped.

### 2026-07-22 ~11:44 +05:30 ó Heartbeat (scheduler 019f886a5e80)

- **Git:** HEAD `5fcd916`; porcelain = watch file only; no Claude landings.
- **Source mtimes (20m):** only `Active_File.md` (11:28) ó synapse/ui/tests quiet.
- **PDF steps / dual-layer / GF-NNN:** frozen; OPEN still GF-002/003/004/005/006.
- **Tests:** skipped (idle).
- **Phase 2 gate:** N/A audit-only.

### 2026-07-22 ~11:47 +05:30 ó Heartbeat (scheduler 019f886a5e80)

- **Git:** HEAD `5fcd916` (~18m since land); porcelain = watch file only.
- **mtimes:** Resolve/UI still last touch ~11:22; no new Claude writes this interval.
- **PDF / GF:** status matrix + OPEN GF-002/003/004/005/006 unchanged.
- **Tests:** skipped (idle).
- **Note:** sustained idle after Graph-First ship ó monitor remains audit-ready if Claude resumes Steps 2/4 gaps.

### 2026-07-22 ~11:50 +05:30 ó Heartbeat (scheduler 019f886a5e80)

- **Git:** HEAD `5fcd916`; ~21m since Graph-First commit; watch file only untracked.
- **10m mtimes:** no synapse/ui/tests/Active_File changes.
- **GF-NNN / PDF steps:** frozen; dual-layer Explore(fields) vs Resolve(entities) still GF-001 OPEN.
- **Tests:** skipped (idle).

### 2026-07-22 ~11:53 +05:30 ó Heartbeat (scheduler 019f886a5e80)

- **Git:** HEAD `5fcd916`; porcelain = watch only; ~24m post Graph-First land.
- **12m source mtimes:** empty (synapse/ui/tests/Active_File quiet).
- **PDF steps 1ñ4 / GF-001ñ012:** no change.
- **Tests:** skipped (idle).

### 2026-07-22 ~11:56 +05:30 ó Heartbeat (scheduler 019f886a5e80)

- **Git:** HEAD `5fcd916` (~27m); only untracked = this watch file.
- **Activity:** no synapse/ui/tests/Active_File or other scratch writes (Claude idle).
- **GF / PDF:** matrix + OPEN GF-002/003/004/005/006 frozen; dual-layer GF-001 still open.
- **Tests:** skipped.
- **Phase 2 / Master Spec:** audit-only; no gate movement.

### 2026-07-22 ~11:56 ó Monitor STOPPED (Claude idle ~30m after Graph-First land)

No commits or source changes after `5fcd916`. Continuous 3m scheduler cancelled.

**Final disposition (Graph-First PDF):**
- Rows 51-52 DONE: browser ingest + entity_matching + Resolve tab as **second layer** beside field Explore.
- Tests: Justin Mason / J. Mason path green (5/5 at baseline).
- **Still open residuals (not blocking stop):** GF-002 ontology SAME_ENTITY_AS on entity merge; GF-003 Conflicts not on Resolve; GF-005 dismiss not persisted; GF-004/006 narrower blocking / not Graphiti-default.
- Phase 2 Master Spec still gated on Vikas Phase-1 sign-off.

End of continuous Graph-First monitoring. Report remains authoritative for review.

### 2026-07-22 ~12:35 ó Monitor RESUMED; Explore landscape mid-flight

**Git:** dirty UI only (not committed):
- NEW `SourceGroupNode.jsx/css` ó source as structure card (header + field:type rows)
- REWRITE `ExploreView.jsx` ó auto landscape of all sources; click header runs multi-source field analyze
- REMOVED `ProfilePreview.jsx` ó profiling inlined into SourceGroupNode (`api.profile` per source on load)
- `FileIngest.jsx` tweaked

**Ledger:** still 50-52 DONE; no new row for this UI polish yet.

**PDF alignment notes (this delta is primarily Master-Spec *field* Explore UX, not Graph-First Step 4 entity canvas):**

| Aspect | Assessment |
|--------|------------|
| PDF Step 4 ""not a spiderweb of files"" | Explore is still **source-structure** cards (closer to schema map). Entity merge clusters stay on **Resolve** ó dual-layer OK if labels stay clear |
| Profiling visible | Still present (in-card), so prior F-038 residual not regressed product-wise |
| Edges | Field candidates drawn **source-to-source** (`fieldNodeId` collapses to `src:{system}`) ó edge **labels** carry field pair names. Coarser than field-level nodes; can overplot many field pairs between same two sources |
| Graph-First GF-002/003/005 | **Unchanged** this fire (no ResolveView / entity_matching edits) |

### GF-013 ∑ P2 ∑ OPEN ∑ Explore edges are source-level, multi-pair collision

`buildEdges` sets `source`/`target` only to source-system node ids. Multiple CandidateEdges between the same two sources share the same ReactFlow endpoints ó overlapping edges, harder hit-targets. Recommend field-level handles or bundled edge with multi-select drawer.

### GF-014 ∑ P3 ∑ OPEN ∑ Uncommitted Explore UX rewrite

Working tree dirty; no ledger row yet. Watch for commit + `ui/dist` rebuild for production `/app`.

### GF-015 ∑ P3 ∑ NOTE ∑ Click-header = fan-out analyze to all other sources

Product choice: activate source compares against **every** other loaded source (not one pair picker). Aligns with ""folder landscape"" discovery; cost O(sources) API analyze calls ó fine for POC scale.

**Monitor re-armed** scheduler every 3m.

### 2026-07-22 ~12:38 +05:30 ó Heartbeat / Explore landscape still in-flight (scheduler)

- **Git HEAD:** still `5fcd916` (Graph-First entity ER + Resolve). No new commit this interval.
- **Porcelain (dirty UI, field Explore ó not entity ER backend):**
  - M `ui/src/views/ExploreView.jsx` / `.css` ó auto SourceGroup landscape; header click ? fan-out `analyze`
  - M `ui/src/views/FileIngest.jsx` ó per-file source naming + fail-forward multi-file loop
  - D `ProfilePreview.jsx/css` ó profiling inlined in SourceGroupNode
  - ?? `SourceGroupNode.jsx/css`
  - ?? this watch file
- **mtimes (~12:19ñ12:35):** SourceGroupNode + ExploreView rewrite; FileIngest 12:34; **`ui/dist` rebuilt 12:34** (static bundle refreshed for production `/app`).
- **synapse/ + tests/:** no mtime change since ~11:21 (entity_matching / merge-candidates). **Tests skipped** (no backend delta).
- **Active_File.md:** present (large ledger); no new Graph-First/ER rows inferred this fire (still 51ñ52 era ship; Explore polish not ledger-rowed yet).
- **Dual-layer check:**
  | Layer | Surface | This fire |
  |-------|---------|-----------|
  | Field discovery (Master Spec / Explore) | SourceGroupNode structure cards + field edges | **Active mid-flight** uncommitted |
  | Entity ER (Graph-First PDF Steps 3ñ4) | Resolve + `entity_matching` | **Idle** since `5fcd916` |
- **PDF Steps 1ñ4:** matrix unchanged (PARTIAL/SIMPLIFIED). Step 4 entity Conflicts / SAME_ENTITY_AS still open (GF-002, GF-003).
- **GF status this fire:**
  - GF-001 dual MG2 language ó OPEN
  - GF-002 SAME_ENTITY_AS on merge ó OPEN (no Resolve/api touch)
  - GF-003 Conflicts on Resolve ó OPEN
  - GF-005 dismiss client-only ó OPEN
  - GF-012/014 dist lag ó **partially mitigated**: dist rebuilt 12:34 but Explore rewrite **still uncommitted** (GF-014 OPEN until commit)
  - GF-013 source-level multi-pair edge collision ó still OPEN (`fieldNodeId` collapses to `src:{system}`)
  - GF-010/011 positives ó hold
- **VnV:** entity path not re-run (idle backend). Field Explore UX is product polish, not Graph-First Step 4.
- **Attention for Claude:** commit Explore landscape + SourceGroupNode when stable; optional ledger row; entity residuals GF-002/003/005 remain if returning to PDF Step 4.

### 2026-07-22 ~13:50 +05:30 ó api explore/ingest skip-extract for CSV/JSONL

- **Git HEAD:** still `5fcd916`; **uncommitted** now includes `M synapse/api.py` (mtime ~13:48) plus prior Explore UI landscape.
- **Delta (backend):** `POST /v1/explore/ingest`:
  - CSV / JSONL: **land only** (`_land_only`) ó **no** `dual_path.extract` per row/line
  - JSON / other: still land + extract once
  - Rationale in code: bulk per-row extract made ~150-row CSV multi-minute / timeout; Explore profiling/field match uses RawObjects only; entity extract deferred to `POST /v1/reprocess` if wanted
- **PDF pipeline impact:**
  | Step | Effect |
  |------|--------|
  | **1** Isolated land | **Improved UX** for folder CSV (still independent per-file sources via FileIngest) |
  | **2** Extract / Graphiti | **Regressed for Explore CSV path** vs prior land+extract; deeper intentional dual-layer split |
  | **3ñ4** ER / Resolve | New browser CSV uploads produce **no entities/facts** until reprocess ó Resolve merge-candidates will not grow from Explore-only land |
- **UI:** Explore SourceGroupNode landscape still dirty/uncommitted; no ResolveView change; dist still ~12:34.
- **Tests this fire:** `test_explore_ingest` + `test_er_merge_candidates_api` + `test_entity_matching` ? **9/9 OK** (~55s; Neo4j localhost:7687 retry noise, non-fatal).
- **GF updates:**
  - **GF-016 ∑ P1 ∑ OPEN** ó Explore ingest CSV/JSONL skips entity extraction by design. Aligns field-layer speed with Master Spec Explore; **conflicts with Graph-First PDF continuity** (folder ? extract ? ER) unless reprocess is productized in UI after upload. Document journey: land ? profile/match fields ? (optional) reprocess ? Resolve.
  - GF-006 (Graphiti not default) ó **reinforced** by this skip.
  - GF-002/003/005 ó still OPEN (entity Step 4 residuals).
  - GF-013/014 ó still OPEN (source edges; uncommitted Explore UX).
  - GF-010/011 ó hold.
- **Attention:** Commit message should call out land-only CSV + reprocess path; consider UI affordance `Extract entities for Resolve` after FileIngest success.

### 2026-07-22 ~13:53 +05:30 ó Heartbeat; ledger rows 53ñ54; tree still dirty

- **Git HEAD:** still `5fcd916`; **no new commit**. Working tree remains dirty (Explore UX + land-only ingest + SourceGroupNode + Active_File + this watch).
- **Code mtimes:** `synapse/api.py` still 13:48; UI src unchanged since ~12:19ñ12:34. **No further backend delta this interval** ó tests not re-run (prior fire 9/9 OK).
- **Active_File.md:** +2 ledger rows (status ?? DONE, not yet reflected in git commit):
  - **Row 53** ó Explore SourceGroup landscape (delete ProfilePreview; header fan-out analyze). Matches uncommitted UI we already audited (GF-013/014/015).
  - **Row 54** ó FileIngest fail-forward + CSV/JSONL **land-only** (no per-row extract); timed 8-file `new_data/` land **41s** post-fix vs timeout pre-fix. Explicit reprocess tradeoff for GraphProximity/Resolve ó same as **GF-016**.
- **Ledger inconsistency note (audit):** Row **51** closeout still claims every landed row runs `dual_path.extract()`; row **54** supersedes that for CSV/JSONL. Historical row text is now stale ó OK as chronology, but SESSION_HANDOFF / ingest docs should not cite row 51 extract behavior without row 54 caveat.
- **PDF / dual-layer:**
  | Layer | Status |
  |-------|--------|
  | Field Explore | Landscape + bulk land fix **claimed DONE in ledger**, **uncommitted** |
  | Entity Graph-First Steps 3ñ4 | Still `5fcd916` only; GF-002/003/005 OPEN |
  | Step 2 after browser CSV | **Opt-in reprocess only** (GF-016 P1 OPEN) |
- **GF-NNN:** no new IDs; GF-016 reinforced by row 54 narrative; GF-014 still OPEN until commit; GF-006 reinforced.
- **Attention:** Working tree has substantial DONE-but-uncommitted work (rows 53ñ54). Next Claude hygiene pass should commit Explore landscape + land-only ingest + ledger together; entity Step 4 residuals remain separate.

### 2026-07-22 ~13:57 +05:30 ó Reprocess UI + edge bundling (Explore dual-layer polish)

- **Git HEAD:** still `5fcd916`; tree dirtier (uncommitted). **No new commit.**
- **New UI delta (~13:54ñ13:55):**
  - `ui/src/api.js` ó `api.reprocess()` ? `POST /v1/reprocess` (pre-existing backend; operator role)
  - `FileIngest.jsx` ó after any successful land, secondary button **\"Extract entities (for Resolve)\"**; title documents CSV land-only tradeoff; one-shot disable after success; `onLanded` refresh landscape
  - `ExploreView.jsx` ó **bundle edges** one ReactFlow edge per source-pair (sort by score; label `N field matches (best x.xx)`); click opens drawer on **top** candidate only (`selectedGroup` state set but **not** multi-list UI yet)
- **Backend:** `synapse/api.py` mtime still 13:48 (land-only CSV) ó **no new backend this fire**. Tests skipped.
- **PDF / dual-layer impact:**
  | Item | Assessment |
  |------|------------|
  | GF-016 land-only CSV | **PARTIAL CLOSE product-wise** ó UI path to entity extract exists; not auto, matches intentional dual-layer |
  | Graph-First Step 2 after folder | Still not automatic; reprocess is **store-wide** (`ReprocessService.run` all episodes, optional domain/limit) ó not scoped to just-uploaded sources |
  | GF-013 multi-edge collision | **MITIGATED** via bundling (was OPEN P2) |
  | Resolve / SAME_ENTITY_AS / Conflicts | Unchanged (GF-002/003/005 OPEN) |
- **GF status updates:**
  - **GF-013** ? **MITIGATED / WATCH** ó bundle edges clickable; residual: drawer shows only best pair, not full `selectedGroup` picker (minor)
  - **GF-016** ? **PARTIAL** ó reprocess button closes UX gap; residual: global reprocess cost/side-effects; no source filter; button only after this-session `landedAny` (reload loses affordance until re-upload)
  - **GF-017 ∑ P3 ∑ OPEN** ó `api.reprocess()` sends no `domain`/`limit`/source filter; large stores re-extract everything when user only wanted new CSV entities
  - GF-014 still OPEN (uncommitted; dist may lag again after this polish)
  - GF-002/003/005/006 still OPEN/reinforced
- **Attention:** Commit rows 53ñ54 + this reprocess/bundle polish together; consider multi-candidate list in drawer; scope reprocess if store grows.
