# Session handoff — resume here

**Last updated:** 2026-07-22
**Code version:** 0.17.0
**Branch:** `main` — own dedicated repo, `https://github.com/vikasiec/Project_Synapse.git`
**Ledger:** `Active_File.md`, rows 1-50. Check its tail for the current open/closed state before assuming anything below is still accurate — it changes every session.

**New subsystem as of rows 38-46 (2026-07-22): Semantic Discovery & Curation.** This is a genuinely new work stream, additive to everything below, not a replacement — it implements Major Goals 1-4 of `docs/Master Architectural Specification & Implementation Roadmap.md` (an uncommitted spec Vikas supplied this session). It sits one layer *above* the existing entity-resolution core: where `entity_resolution.py` matches *records* (this Patient row = that Patient row), the new layer matches *schema fields across source systems* (does `cust_id` mean the same thing as `client_num`?) before any records are compared, with a human curation step in between. See `synapse/profiling.py` (field profiling + stdlib vectors), `synapse/matching.py` (hybrid scoring + transitive learning), `synapse/ontology.py`'s new `RelationshipEdge` registry, and the new `ui/` Vite/React frontend (`/app`, alongside the legacy Sense board at `/`). **Phase 2 of that spec (Major Goals 5-7) is explicitly NOT started — gated on Vikas's own sign-off of Phase 1, per the spec's own execution gate, not just on tests passing.**

---

## What is done

| Area | Status |
|------|--------|
| Architecture POC H1–H16 | Owned in code + `docs/ADRs_H1_H16.md` |
| Four engines (Graphiti, GraphRAG, Data-Juicer, PageIndex) | Wired (real prefer + local lite fallback), `python -m synapse capability` |
| Healthcare vertical (`hospital_ops` + `clinical_lab`) | `Patient`/`Doctor`/`Appointment`/`Treatment`/`Billing`, full 4-hop join on real hospital data |
| Banking vertical | `AccountHolder`/`Account`/`Transaction` — proved `docs/DOMAIN_PACK_CONTRACT.md` generalizes to a second domain |
| HL7v2 interoperability | `synapse/hl7v2.py`, scoped ORU^R01, self-declared separators |
| FHIR interoperability | `synapse/fhir.py`, scoped Bundle+Patient+Observation |
| Cross-format identity convergence | Patient P001 resolves to ONE entity across CSV, HL7v2, FHIR |
| PID-3/FHIR identifier assigning-authority namespacing | Fixed (row 23) — `identifier_authority` on `entity_resolution.py`, normalized comparison |
| Sense board (`synapse/static/index.html`) | RAW/MEANING/CONFLICTS/ASK/EMIT, proven domain-blind across all 3 verticals |
| Multi-agent collaboration | Claude (Lead) + Codex, governed by `.agent_os/collaboration_model_V2.0.md` (V2.8), ledger-driven |
| Core-blindness discipline | Audited (row 22) — no hardcoded domain/predicate whitelist remaining in core modules |
| Schema field profiling (Major Goal 1) | `synapse/profiling.py` — `data_type`/`entropy_score`/`regex_pattern_match`/`min_hash_sketch` + stdlib hashing-trick semantic vector |
| Hybrid candidate scoring (Major Goal 2) | `synapse/matching.py`, `POST /v1/explore/analyze` — exact spec formula/thresholds |
| Ontology relationship write-back (Major Goal 4) | `synapse/ontology.py`'s `RelationshipEdge` registry, `POST /v1/ontology/relationships` (ACCEPT/REJECT/RELABEL) |
| Transitive learning engine (Major Goal 4) | `synapse/matching.py::transitive_candidates` |
| New Vite/React UI (Catalog + Explore journey) | `ui/`, served at `/app` alongside the legacy Sense board at `/` — not yet at panel parity, so `/` stays default |
| Full test suite | 232/232 as of row 46 (verify against `Active_File.md`'s tail — it moves every session) |

**Superseded, not deleted:** `claudreview.md` is from the pre-healthcare wizard-demo era — read `management/master_plan.md`, `management/Features.md`, and `Active_File.md` for the current, accurate narrative instead.

---

## How to resume

### 1. Read state first, don't assume

```powershell
cd "C:\Users\Vikas Sharma\OneDrive\Documents\Claude\Projects\Project_Synapse"
```

Read `Active_File.md`'s tail (most recent rows) and `management/Road_map.md`'s "Currently open" / "Natural next candidates" sections before picking new work — both are kept in sync every session.

### 2. Verify the suite

```powershell
python -m unittest discover -s tests -t .
python -m synapse capability
```

### 3. Run the Sense board against real multi-vertical data

```powershell
python scripts/smoke_hospital_full_chain.py   # healthcare, full 5-file join
python scripts/smoke_banking_join.py          # banking
python scripts/smoke_hl7_join.py              # HL7v2 cross-format identity proof
python -m synapse serve --host 127.0.0.1 --port 8787 --db .data/sense.db
```

Open **http://127.0.0.1:8787/** for RAW → MEANING → CONFLICTS → ASK → EMIT.

### 4. If working as Lead AI or a contributor

Follow `.agent_os/collaboration_model_V2.0.md` in full — lock discipline (`lock.txt`) for any `Active_File.md` row append, fresh-read-before-ID-assignment, and the row lifecycle (`🔴 PENDING` → `🟡 REVIEW_READY` → `🟢 DONE`, Lead reviews before closing).

---

## Known issues / caveats (still true)

- Gemini free-tier embed quota may 429 Graphiti live pushes — local seed uses the local graph fallback.
- Multiple `python -m synapse serve` processes fight for port 8787 — kill extras if "Failed to fetch".
- Platform-maturity gaps still open, deliberately: multi-tenant ACLs, real SaaS OAuth CDC, real $ FinOps, production-grade fuzzy ER beyond what's built. See `management/master_plan.md` §6.

## Known residuals in the Semantic Discovery subsystem (per Grok's independent review, row 48; updated rows 49-56)

Not blocking the demo, but real and worth knowing:

- **CSV/JSONL uploads via `/v1/explore/ingest` skip entity extraction by design** (row 54, fixed a real timeout bug where per-row extraction made large files take minutes): those sources profile/field-match fine, but won't produce Resolve-tab merge candidates until `POST /v1/reprocess` runs — the "Extract entities (for Resolve)" button in the Explore UI (row 55) does this on demand.
- **Entity merges (Resolve tab) don't write an Ontology Registry `SAME_ENTITY_AS` edge** (Grok's GF-002): merges use the existing `EntityResolutionService.merge()`/stable-ID-redirect mechanism directly, deliberately kept separate from the field-relationship Catalog, since they're two different referents (entities vs. schema fields). Documented split, not an oversight.
- **Entity-pair "dismiss" (Resolve tab) is client-side only**, unlike field-relationship REJECT which persists (`is_pair_rejected`) — a dismissed entity pair will resurface on next load. Stated MVP scope cut (row 52), not yet closed.

Closed, no longer residual: **F-021** (synonym-map false-positive risk, row 50). **F-027** (relationships were process-memory-only, now durable, row 50). **HL7v2 pipe-delimited payloads now profile correctly** (row 56) — reuses the existing `synapse/hl7v2.py` tokenizer, position-based field names (`PID.5`, `OBX.5`); the earlier "not profiled" residual is fixed, not just documented around.

## Currently open (as of this update — verify against `Active_File.md`)

- Rows 1-56 all closed as of this update.
- **Not started, deliberately: Phase 2 of the new spec** (Major Goals 5-7 — semantic translation/CDM bridge, cross-system conflict routing, federated FHIR/BIAN/OpenAPI exports). The spec's own execution gate requires Vikas's explicit sign-off on Phase 1 before this begins — do not start it on the assumption that tests passing is sufficient.
- The new `ui/` frontend covers Explore + Resolve + Catalog. It has not reached parity with the legacy Sense board's RAW/MEANING/CONFLICTS/ASK/EMIT panels, so `/` still serves the legacy UI by design — don't retire `synapse/static/index.html` until that parity is confirmed.

## Key files

| Path | Role |
|------|------|
| `Active_File.md` | Central state ledger — read this first, always |
| `management/master_plan.md` | Current implementation narrative, ordered by why |
| `management/Features.md` | Domain-pack feature inventory |
| `management/Road_map.md` | Sequenced delivery plan + open/next-candidate lists |
| `docs/DOMAIN_PACK_CONTRACT.md` | Platform/domain boundary contract, incl. `strict_identity` and `identifier_authority` |
| `docs/ADRs_H1_H16.md` | Production-hole ownership register |
| `docs/THREAT_MODEL.md` | STRIDE-lite register |
| `.agent_os/collaboration_model_V2.0.md` | Multi-agent governance (V2.8) |
| `synapse/static/index.html` | Legacy Sense board UI, still served at `/` |
| `ui/` | New Vite/React UI (Catalog + Explore), served at `/app`, `npm run build` from `ui/` to rebuild |
| `synapse/extraction.py` | Extraction rules, all domains + formats |
| `synapse/ontology.py` | L0/L1 domain packs + new `RelationshipEdge` registry (Major Goal 4) |
| `synapse/entity_resolution.py` | Cross-source identity resolution, `strict_identity`/`identifier_authority`/`linked_schema_fields` |
| `synapse/profiling.py` | Schema field profiling + stdlib semantic vectors (Major Goal 1) |
| `synapse/matching.py` | Hybrid candidate scoring + transitive learning (Major Goals 2, 4) |
| `docs/Master Architectural Specification & Implementation Roadmap.md` | The new spec driving rows 38-47 (uncommitted; Phase 2 gated) |
