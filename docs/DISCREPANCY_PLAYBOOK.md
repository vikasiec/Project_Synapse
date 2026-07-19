# Discrepancy playbook (POC)

## Conflict types

| Type | Example | Default policy |
|------|---------|----------------|
| Scalar clash | `current_version` v2.4.0 vs v2.4.1 | Surface ambiguous + rank by \(W_v\) |
| Stale feed | HR leave vs IdP active | Prefer higher authority + fresher \(e^{-\lambda\Delta t}\) |
| Accepted plural | Regional legal names | Mark `ACCEPTED_PLURAL` (product decision) |
| Human pin | SRE pins K8s version | `RESOLVED_HUMAN_PIN`; retain losers |
| Cross-domain | Support ticket vs Billing ARR | Keep domain-scoped ACLs; no silent join leaks |

## Resolution ladder

1. **Detect** — `ConflictResolver.detect_scalar_conflicts`  
2. **Rank** — \(W_v = A_r e^{-\lambda\Delta t} + L_p\)  
3. **Surface** — never hide open regulated conflicts  
4. **Pin** — human adjudicator with reason (audited)  
5. **Reprocess** — if extractor improved, re-run; temporal supersession  

## Domain authority seeds (POC)

| Source | \(A_r\) |
|--------|---------|
| IdP-Okta | 0.95 |
| K8s-Cluster-Alpha | 0.95 |
| Billing-Zuora | 0.92 |
| GitHub-CI | 0.90 |
| HR-Workday | 0.88 |
| CRM-Salesforce | 0.75 |
| Slack-Incident-Feed | 0.70 |
| ITSM-ServiceNow | 0.70 |
| Support-Zendesk | 0.60 |
| FileDrop / Webhook | 0.55–0.65 |

## Multi-domain corpus

`python -m synapse seed --scenario org` loads infra + revenue + identity + support runbooks with intentional clashes for eval.
