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
| **Identity collision** | Two different real people share a bare identifier value across sources (e.g. two hospitals both issue patient ID "P001" to different patients) | `identifier_authority` scoping on `strict_identity` types (`entity_resolution.py`, `Active_File.md` row 23) — cross-source ID-value blocking (`find_by_external_id_value`) now requires a compatible assigning authority (HL7 PID-3.4 / FHIR `Identifier.system`, normalized), not just a matching bare ID, before merging two sources' records into one entity |

## Residual risks (accepted for POC)

- Side channels via timing not fully modeled  
- Full multi-tenant crypto partitions not implemented  
- Simulated write-back only — production needs separate approval workflow SaaS
- Assigning-authority values (`identifier_authority`) are self-declared by the
  source, not independently/cryptographically verified — same trust boundary as
  `source_system` labels above (Spoofing row). A malicious or misconfigured
  source could still claim another facility's authority string to force an
  unintended merge, or claim a novel one to force an unintended split. Not
  modeled as adversarial in this POC.
