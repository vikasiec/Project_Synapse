# Architecture Decision Records — H1–H16

**Status:** Accepted for Project Synapse POC (v0.14)  
**Secrets:** never stored here  

| Hole | Decision | POC owner module |
|------|----------|------------------|
| **H1** Deterministic precision | Dual-path: rules first, LLM residual only | `dual_path`, `llm_gemini` |
| **H2** Latency | Latency classes + claim cache + budgets | `budget`, `claim_cache`, `orchestrator` |
| **H3** Token economics | Hard budgets; free-tier throttle; cost envelopes | `budget`, `cost_model`, Gemini RPM/RPD |
| **H4** ACLs | Tag-at-ingest; filter at query | `security`, `ingestion` |
| **H5** Schema drift | Key/pattern baselines → drift events → reprocess | `drift` |
| **H6** Idempotent reprocess | content_hash + pipeline version; re-extract | `reprocess`, `ingestion` |
| **H7** Freshness / CDC | Watermarks per connector | `connectors/*` |
| **H8** Ontology | L0/L1 load-bearing at extract/ER + predicate SoR boost on ranking | `ontology` → `extraction` / `entity_resolution` / `resolution` |
| **H9** Global vs local | IDF + intent router; multi-engine fuse | `control_plane`, `orchestrator` |
| **H10** Eval | Golden packs checkout/billing/identity/org | `eval_runner` |
| **H11** Human-in-loop | Pin conflicts; approve actions | `adjudication`, `action_bus` |
| **H12** FinOps | Metrics + cost model + cache hit ratio | `metrics`, `cost_model` |
| **H13** DR / retention | Raw landing is rebuild root; export/import | `export_import`, raw store |
| **H14** Model supply chain | Pinned model ids in `.env`; redaction ops | `operators`, SETUP_DECISIONS |
| **H15** Write-back | Propose → approve → **simulated** execute only | `action_bus` |
| **H16** BI escape hatch | Materialize entity_facts + conflicts JSON/CSV | `materialize` |

## Non-decisions (explicit)

- No silent production CRM/ticket mutation in POC.  
- No claim of petabyte interactive latency.  
- Warehouse is optional *consumer* of materialized views, not the system of semantic truth.
