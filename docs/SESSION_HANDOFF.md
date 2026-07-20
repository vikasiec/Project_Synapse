# Session handoff — resume here

**Last updated:** 2026-07-20
**Code version:** 0.17.0
**Branch:** `main` — own dedicated repo, `https://github.com/vikasiec/Project_Synapse.git`
**Ledger:** `Active_File.md`, rows 1-26. Check its tail for the current open/closed state before assuming anything below is still accurate — it changes every session.

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
| Full test suite | 167/167 as of row 23 |

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

## Currently open (as of this update — verify against `Active_File.md`)

- Row 24 (Codex): FHIR conflict-detection proof, mirroring row 4's method for HL7/CSV.
- Row 25 (Codex): observation-vs-analyte instance modeling — distinct observation identity per order/specimen/time.

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
| `synapse/static/index.html` | Sense board UI |
| `synapse/extraction.py` | Extraction rules, all domains + formats |
| `synapse/ontology.py` | L0/L1 domain packs |
| `synapse/entity_resolution.py` | Cross-source identity resolution, `strict_identity`/`identifier_authority` |
