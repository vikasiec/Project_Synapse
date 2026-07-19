# Project Synapse

Org-wide **zero-ETL / schema-on-read** semantic data core — land messy data with lineage + policy, extract meaning, surface conflicts, answer under budget.

**Version:** 0.17.0 · **Python 3.10+** · **Ontology load-bearing (H8) at extract + resolution**

## Quick start

```bash
python -m unittest discover -s tests -t .
python -m synapse eval --pack all
python -m synapse seed --scenario org --db .data/s.db
python -m synapse ask "What are global themes and failure modes?" --db .data/s.db
python -m synapse materialize --out .data/materialized --db .data/s.db
python -m synapse capability
python scripts/prove_platform.py
python -m synapse serve --port 8787 --db .data/s.db
```

Secrets only in local `.env` (gitignored). See `docs/SETUP_DECISIONS.md`.

## Capability map

| Layer | Implementation |
|-------|----------------|
| Contracts | RawObject → Episode → Entity → Fact → Conflict → Claim + JSON schemas |
| Prep | Data-Juicer-class operators + package detect |
| Extract | Dual-path rules (A) + Gemini residual (B) |
| Graph | Graphiti live (Neo4j) + local mirror |
| Themes | GraphRAG adapter / communities |
| Docs | PageIndex adapter / section trees |
| Query lifecycle | Budgeted orchestrator + ACL claim cache |
| Ontology | L0/L1 + soft L2 |
| Reprocess | H6 re-extract over history |
| Drift | H5 shape baselines |
| BI emit | H16 materialize JSON/CSV |
| Actions | H15 propose → approve → sim execute |
| Eval | checkout · billing · identity · org |
| Connectors | mock CDC · JSONL inbox · webhook inbox |

## CLI surface

```text
simulate seed query ask pin merge conflicts
ingest export import graph eval audit
connectors poll register-jsonl mock-emit inbox webhook
graphiti-search engines themes doc-route
reprocess materialize drift
action-propose action-decide actions
capability cost poc-status serve
```

## Design sources

- `docs/ORG_WIDE_SEMANTIC_DATA_CORE.md`
- `docs/ADRs_H1_H16.md`
- `docs/DISCREPANCY_PLAYBOOK.md`
- `docs/THREAT_MODEL.md`
- `docs/POC_RESULTS.md`
- `docs/schemas/*.schema.json`

## Phase status

| Phase | Status |
|-------|--------|
| 0 Design | Done |
| 1 Local foundation | Done |
| 1.5–1.7 Multi-scenario / eval / metrics | Done |
| 2.0 CDC · dual-path · Graphiti | Done |
| 2.1 Four engines + multi-engine ask | Done |
| 2.2 H-gap closures (reprocess, BI, actions, drift, cost, threat) | Done (0.14) |
| 2.3 as_of · verifiers · CSV drop · UI/CI polish | Done (0.15) |
| 2.4 SaaS stubs · early-exit · prove_platform | Done (0.16) |
| 2.5 Ontology load-bearing extract + ranking (H8 depth) | **Done (0.17)** |
| 3+ Real SaaS OAuth CDC · paid tier · multi-tenant prod | Future ops |

## Install optional engines

```bash
python -m pip install -e ".[engines]"
```
