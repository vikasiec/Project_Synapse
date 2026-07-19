# Phase A baseline — 2026-07-19 (Grok)

**Goal:** Freeze trust loop before Sense board work.  
**DB:** `.data/sense.db`  
**Owner notes:** [OWNER: GROK] A1–A4

---

## A1 Seed

```powershell
cd Project_Synapse
python -m synapse seed --scenario checkout --db .data/sense.db
```

**Result (local store succeeded):**

| Metric | Value |
|--------|--------|
| scenario | checkout |
| entity_hint | checkout-service |
| raw_after | 3 |
| entities | 1 |
| facts | 8 |

**Caveat:** CLI seed still attempts Graphiti/Neo4j when env points at it. Neo4j was **down** (`localhost:7687` refused). Seed process exited non-zero with many retry warnings, but **SQLite still populated**. For Sense board demos, **local store is enough** (UI seed path already prefers local graph — keep that).

**Tip for Claude / demos:** Prefer:

```powershell
# If GRAPHITI_ENABLED=1 and Neo4j is down, seed is slow/noisy.
# Either start Neo4j or set GRAPHITI_ENABLED=0 in .env for local visual demos.
```

---

## A2 Query / conflicts (CLI stand-in for UI)

**Entity query (works):**

```powershell
python -m synapse query checkout-service --db .data/sense.db
```

**Sensed:**

- Entity: `checkout-service` (Service / ontology `InfraService` L1)
- **Open conflict** on `current_version`:
  - K8s-Cluster-Alpha → `v2.4.0` (highest Wv)
  - GitHub-CI → `v2.4.1`
  - Slack-Incident-Feed → `v2.4.0`
- Other facts: `runtime_state=CrashLoopBackOff`, `deploy_status=success`, `change_method=manual_bypass`, `related_incident=Incident-104`
- Claim statement is **AMBIGUOUS** (conflict surfaced, not hidden) — thesis hit
- Citations point at 3 raw objects

**NL ask quirk:**

```powershell
python -m synapse ask "What is wrong with checkout-service?" --db .data/sense.db --budget interactive
```

Entity hint parsed as `wrong with checkout-service` → not found. Prefer:

- UI entity `checkout-service`, or  
- `python -m synapse query checkout-service --db .data/sense.db`, or  
- ask with clearer entity phrase / entity_id if API supports it  

**Conflicts CLI:**

```powershell
python -m synapse conflicts --db .data/sense.db
```

One open conflict: `current_version` on checkout-service.

---

## A3 Materialize (H16)

```powershell
python -m synapse materialize --out .data/materialized_sense --db .data/sense.db
```

**Outputs:**

- `.data/materialized_sense/entity_facts_active.csv` (6 rows)
- `.data/materialized_sense/entity_facts_active.json`

Notes from materializer: open conflicts present; `multi_value` on `current_version`. Usable table form without warehouse ETL.

---

## A4 What already works vs Sense board gap

| Sense criterion | CLI today | UI gap for Claude |
|-----------------|-----------|-------------------|
| 1 Arrived (raw) | 3 raw in DB; not listed easily in one command | **RAW panel** + `GET /v1/raw` |
| 2 Meaning | query shows entity + facts | **MEANING panel** + facts list API |
| 3 Conflicts | open conflict returned | Wire **CONFLICTS** panel (API may exist) |
| 4 Ask / decide | query works; free-text ask entity parse weak | Keep ASK; pin already in wizard |
| 5 Emit | CSV/JSON on disk | **EMIT** button + preview rows |

**Definition for Claude Batch 1:** After seed of this same DB, browser shows counts 3 raw / 1 entity / 8 facts / 1 conflict without CLI.

---

## Replay (anyone)

```powershell
cd "C:\Users\Vikas Sharma\OneDrive\Documents\Claude\Projects\Project_Synapse"
python -m synapse seed --scenario checkout --db .data/sense.db
python -m synapse query checkout-service --db .data/sense.db
python -m synapse conflicts --db .data/sense.db
python -m synapse materialize --out .data/materialized_sense --db .data/sense.db
python -m synapse serve --host 127.0.0.1 --port 8787 --db .data/sense.db
# open http://127.0.0.1:8787/
```

---

## Status

| Item | Status |
|------|--------|
| A1 seed | **Done** (local DB; Graphiti noise noted) |
| A2 query + conflict | **Done** (CLI) |
| A3 materialize | **Done** |
| A4 notes | **This file** |
| Phase B+ | **Claude** — do not wait on Grok |

Grok next (when quota): B9 review of Claude PR, then E1/E2 proof docs.
