# Visual sense without ETL — proof pack

**Date:** 2026-07-19  
**Scope:** P1 single-domain visual consumer (Sense board), not platform scale  
**Plan:** `docs/Grok_Plan19Jul.txt`  
**Baseline:** `docs/PHASE_A_BASELINE_19Jul.md`

---

## Claim

You can land messy multi-source data **without a warehouse ETL project**, then **see** in a browser:

1. Raw arrival  
2. Extracted meaning (entities / facts) — or an honest empty state  
3. Open conflicts (not silently cleaned)  
4. An answer with citations / ambiguity  
5. A table emit (CSV/JSON) for Excel  

## Non-claims

- Not petabyte interactive latency  
- Not production multi-SaaS CDC catalog  
- Not multi-tenant product  
- Not “any unknown domain auto-understands without rules/residual”  
- Neo4j/Graphiti optional; local SQLite is enough for this proof  

---

## Replay (&lt; 5 minutes)

```powershell
cd "C:\Users\Vikas Sharma\OneDrive\Documents\Claude\Projects\Project_Synapse"

# Optional: quieter demos if Neo4j is not running
# set GRAPHITI_ENABLED=0 in .env

python scripts/sense_demo.py
python -m synapse serve --host 127.0.0.1 --port 8787 --db .data/sense.db
```

Open **http://127.0.0.1:8787/** → click **Open Sense board →**

| Panel | What you should see (checkout corpus) |
|-------|----------------------------------------|
| Status strip | Raw / episodes / entities / facts / open conflicts |
| **RAW** | Landed objects with source + preview; drop zone for JSON/CSV/JSONL |
| **MEANING** | Entity chips (e.g. checkout-service) + facts; path badge `rules` / `residual` |
| **CONFLICTS** | Disagreement list when present (e.g. `current_version`) |
| **ASK** | Entity = `checkout-service` → answer may show AMBIGUOUS / conflict notes |
| **EMIT** | Materialize → preview rows + path to CSV/JSON |

Wizard path still available: Load → Ask → Conflicts → Decide.

---

## API smoke (Sense board contract)

| Method | Path | Role |
|--------|------|------|
| GET | `/v1/sense/summary` | Counts strip |
| GET | `/v1/raw?limit=50` | RAW panel |
| GET | `/v1/episodes?limit=50` | Episodes |
| GET | `/v1/facts?limit=100` | MEANING |
| GET | `/v1/entities` | Entity chips |
| GET | `/v1/conflicts` | CONFLICTS |
| POST | `/v1/materialize` | EMIT |
| POST | `/v1/sense/drop` | Drop land (C1) |

---

## Automated evidence

```powershell
python -m unittest tests.test_sense_api -v
python scripts/sense_demo.py
```

**Grok review (2026-07-19):** `tests.test_sense_api` — **5/5 OK** (list after seed, drop honesty, 400/404).  
`sense_demo.py` prints DB counts + serve URL.

---

## Phase checklist vs plan

| ID | Item | Status |
|----|------|--------|
| A1–A4 | Baseline seed / query / materialize / notes | Done (Grok) |
| B1 | API raw/episodes/facts | Done (Claude) |
| B2–B7 | Sense board panels + status strip | Done (Claude) |
| B8 | `tests/test_sense_api.py` | Done (Claude); reviewed OK |
| C1 | Drop zone | Done (Claude) |
| C2 | Unknown-shape honesty banner | Done (Claude UI + drop test) |
| D1 | Wire `schema_validate` on Path B | **Optional / not done** (still FactVerifier demotion) |
| D2 | Path badges on facts | Done (`rules` / `residual` / `other`) |
| E1 | This doc | Done (Grok) |
| E3 | `scripts/sense_demo.py` | Done (Claude) |

---

## Known demo friction

1. **GRAPHITI_ENABLED + Neo4j down** → seed/drop can be slow with retries; set `GRAPHITI_ENABLED=0` for local visual demos.  
2. Free-text ask entity parse can miss; Sense board ASK uses **entity field** (`checkout-service`) — prefer that.  
3. If conflict was pinned earlier in the same DB, CONFLICTS may show empty until re-seed on a clean DB.

---

## Verdict

**Visual-sense core point: demonstrated at POC scope.**  
Architecture was already complete; Claude delivered the **consumer plane** so you can *see* raw → meaning → conflict → answer → emit without CLI.

---

## Second vertical: healthcare (Active_File.md task 9, 2026-07-19)

The checkout corpus proved the Sense board works. It doesn't prove the board is
**domain-blind** — that required a genuinely different vertical. `hospital_management/`
(Active_File.md tasks 1, 4-6: `Patient`/`Doctor`/`Appointment`/`Treatment`/`Billing`
domain pack, 660/660 rows, full 4-hop join) is that second vertical.

```powershell
python scripts/smoke_hospital_full_chain.py    # lands the 5-file db
python -m synapse serve --port 8787 --db .data/hospital_full_chain_demo.db
```

Open **http://127.0.0.1:8787/** → **Open Sense board →**. Same UI, same API, zero
healthcare-specific code in `api.py`/`index.html` — verified panel by panel:

| Panel | Verified against healthcare data |
|-------|------------------------------------|
| Status strip | 660 raw / 660 episodes / 660 entities / 4850 facts |
| **RAW** | Billing/Patient/Doctor rows with readable previews (e.g. `bill_id: B199\npatient_id: P017...`) |
| **MEANING** | Entity chips across all 5 types (Patient, Doctor, Appointment, Treatment, Billing); clicking Bill B001 shows all 8 facts incl. resolved `treatment_entity_id`/`patient_entity_id` |
| **CONFLICTS** | Correctly empty on this db (no front-desk variant landed here — see task 4's `hospital_conflict_demo.db` for the conflict-panel proof, already verified separately) |
| **ASK** | "David Williams" → full narrated answer citing all 8 facts by source (see bug below) |
| **EMIT** | Materialize → 4850 rows, CSV/JSON written, preview correct |

### Real bug found and fixed by this walkthrough

The ASK panel initially returned **"No primary facts visible for David Williams"**
despite 8 real facts existing. Root cause: `query.py`'s answer-narration logic had a
**hardcoded predicate whitelist** (`current_version`, `annual_revenue`, `runtime_state`,
`account_status` — all infra/revenue/identity-specific) baked into the otherwise
domain-blind core. It happened to cover every predicate the checkout/billing/identity
scenarios use, so this was never caught until a genuinely new domain's predicates
(`insurance_provider`, `amount`, `payment_status`, ...) hit it. Same class of finding
as task 4's entity-resolution bug: a real pre-existing core limitation, only exposed
by testing depth on a second vertical.

**Fix:** a generic fallback in `query.py` — if the two hardcoded predicate loops
produce nothing, narrate any remaining visible facts (any predicate, any domain)
instead of declaring false emptiness. The true "no facts" case is unaffected — it's
still caught earlier, at the ABAC gate, before narration ever runs. Regression tests:
`tests/test_query_generic_narration.py` (2/2). Full suite: 110/110 after the fix.

**Also confirmed working in passing:** PII redaction — David Williams' email showed
as `[REDACTED_EMAIL]` in the ASK answer, confirming the prep-pipeline redaction
operator runs correctly on healthcare data with no domain-specific wiring.

### Updated verdict

**The Sense board is genuinely domain-blind** — not by inspection of the code, but
by demonstration: the identical UI and API contract that proved the checkout
scenario now proves a completely independent healthcare vertical, and the one real
gap that surfaced (`query.py`'s narration whitelist) was a **core** bug, not a
missing healthcare-specific feature — exactly the kind of finding
`docs/DOMAIN_PACK_CONTRACT.md` exists to keep catching honestly.
