# Threat model (semantic plane) — POC STRIDE-lite

| Threat | Example | Mitigation in POC |
|--------|---------|-------------------|
| **Spoofing** | Fake source_system labels | Connector actor tags + audit; authority map not trusted for auth |
| **Tampering** | Mutate facts without lineage | Immutable raw; facts derived; reprocess versioned |
| **Repudiation** | Deny pin/query | Audit log on query/pin/action/reprocess |
| **Info disclosure** | Cross-ACL leak via aggregation | ABAC filter on facts/raw before claim; no cross-ACL counts |
| **DoS** | Token / graph cost runaway | Budgets, free-tier throttle, claim cache, interactive caps |
| **Elevation** | L1 reads L2 channels | Principal attributes must subset ACL tags |
| **Poison graph** | Bad residual LLM facts | Path A preferred for structured; confidence + conflict surface |
| **Secret exfil** | Keys in logs/docs | `.env` only; redaction operators; status never prints secrets |
| **Write-back abuse** | Auto ticket spam | Action bus requires approve for high risk; execute is simulated |

## Residual risks (accepted for POC)

- Side channels via timing not fully modeled  
- Full multi-tenant crypto partitions not implemented  
- Simulated write-back only — production needs separate approval workflow SaaS
