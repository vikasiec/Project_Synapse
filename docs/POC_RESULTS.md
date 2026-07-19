# Project Synapse — POC results (evidence)

**Status:** POC complete for architectural proof (not petabyte production)  
**Version:** 0.16.x  
**Secrets:** never in this file  

---

## What we proved

A **schema-on-read, discrepancy-tolerant semantic data core** is doable with the right subsystems: land raw with ACL + lineage, dual-path extract, temporal facts, conflicts first-class, multi-engine answer under budget, reprocess, materialize for BI, and simulated write-back with approval.

---

## Blueprint engines

| Engine | Package | Status |
|--------|---------|--------|
| Graphiti | graphiti-core + Neo4j | Live |
| GraphRAG | graphrag | Package + store communities |
| PageIndex | pageindex | Package + local trees |
| Data-Juicer | py-data-juicer | Package ops detect + lite chain |

---

## H1–H16 closed in code

See `docs/ADRs_H1_H16.md`. All holes have a module owner and runnable path.

---

## Commands (no secrets)

```powershell
python -m unittest discover -s tests -t .
python -m synapse poc-status
python -m synapse capability
python -m synapse cost
python -m synapse seed --scenario org --db .data/demo.db
python -m synapse ask "What are global themes and failure modes?" --budget deep --db .data/demo.db
python -m synapse history checkout-service --predicate current_version --db .data/demo.db
python -m synapse query checkout-service --as-of 2026-01-01T12:00:00Z --db .data/demo.db
python -m synapse reprocess --db .data/demo.db
python -m synapse materialize --out .data/materialized --db .data/demo.db
python -m synapse drift --db .data/demo.db
python -m synapse action-propose --type create_ticket --payload "{\"title\":\"x\"}" --risk high --by sre --db .data/demo.db
python -m synapse eval --pack all
python scripts/demo_e2e.py
python scripts/prove_platform.py
python scripts/smoke_graphiti_search.py "checkout"
```

---

## Explicit non-claims

- Not a warehouse replacement on day one  
- Not petabyte interactive latency  
- Not production multi-SaaS CDC catalog (50–500 systems)  
- Write-back is **simulated** only  
- Paid unlimited LLM tier not required for proof  

---

## Visual sense without ETL (2026-07-19)

**Claim:** Land messy data → see raw / meaning / open conflicts / answer / table emit in a local browser (Sense board), without warehouse ETL.

**How:** `python scripts/sense_demo.py` then `python -m synapse serve --port 8787 --db .data/sense.db` → **Open Sense board →**

**Evidence:** `docs/VISUAL_SENSE_PROOF.md`, `tests/test_sense_api.py` (5/5 OK), API: `/v1/raw`, `/v1/facts`, `/v1/sense/summary`, `/v1/sense/drop`, POST `/v1/materialize`.

**Non-claim:** Not universal auto-extract for every domain; unknown shapes still show raw + honesty banner until rules/residual hit.

---

## Verdict

**Architecture-complete POC + visual consumer for the core “sense the data” loop.** Remaining work is scale engineering, connector catalog growth, and governance ops — not missing conceptual holes for the P1 thesis.
