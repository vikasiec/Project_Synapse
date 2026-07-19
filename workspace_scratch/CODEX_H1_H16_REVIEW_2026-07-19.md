# Codex H1–H16 architecture-fit review

**Scope:** Review the healthcare, banking, HL7v2, and FHIR work against the accepted H1–H16 register and the domain-pack contract. This is an architecture-fit review, not a code-level redesign.

## Executive conclusion

The domain-pack work still fits the platform thesis. Healthcare is implemented as pack data, ontology, extraction, and tests; the shared core remains domain-blind. Banking validates that the contract generalizes, while HL7v2 and FHIR demonstrate that the connector layer can accept structurally different healthcare formats.

The work also exposed two risks that are larger than ordinary pack bugs:

1. **Identity namespace/provenance is under-specified.** `strict_identity` prevents unsafe name merges, but HL7 PID-3 and equivalent FHIR identifiers are still treated as bare IDs. An MRN such as `P001` from two facilities could merge unless assigning authority/system is retained and included in identity scope. This is primarily an H8 ontology/entity-resolution gap with H11 governance consequences.
2. **Observation-instance identity is under-specified.** `LabResult` identity is now scoped by patient and test code, which fixed the demonstrated cross-patient conflation, but repeated observations for the same patient and analyte can still converge across order/specimen/time. This is an H8 semantic-model granularity gap, not solved by H6 reprocessing alone.

These should be explicit production limitations or new follow-up holes before claiming healthcare-grade interoperability.

## H1–H16 mapping

| Hole | Fit of completed work | Remaining evidence / risk |
|---|---|---|
| H1 Deterministic precision | Strong POC fit. CSV, HL7v2, and FHIR use deterministic parsers/rules before residual extraction; tests cover malformed input and trigger scoping. | Numeric/unit verification and regulated-predicate authority are not demonstrated by the new interoperability formats. |
| H2 Latency | No domain drift. Domain packs feed the existing router/cache/budget path. | No realistic latency or multi-source load proof; remains design-level. |
| H3 Token economics | No domain-specific leakage. Banking and healthcare use the same budget/control path. | No measured cost envelope for the new formats; no broad long-context economics proof. |
| H4 ACLs | Pack work preserves generic ACL propagation and Sense behavior; healthcare PII redaction was observed. | Multi-facility identifier isolation and anti-inference tests remain incomplete. |
| H5 Schema drift | Domain guards and partial-link behavior are compatible with drift/reprocess design. | No real drift fixture was added for CSV, HL7, or FHIR; connector schema evolution remains unproven. |
| H6 Idempotent reprocess | Land-order dependency is honestly documented; unresolved links can be completed by reprocess. Cross-format records converge through existing identity mechanisms. | Reprocess after connector/parser version changes needs stronger end-to-end evidence, especially for observation identity changes. |
| H7 Freshness / CDC | HL7/FHIR add file-based interoperability formats without contaminating core. | Static files do not prove watermarks, late arrivals, replay, or `as_of` correctness. |
| H8 Ontology / ER | Strongest demonstrated area: L1 packs, strict person identity, disambiguation guards, and cross-format convergence. Banking proves the contract is not healthcare-specific. | Assigning-authority namespaces and observation-vs-analyte modeling are not represented in the current pack contract. This is the main newly exposed architectural gap. |
| H9 Global/local retrieval | Sense board and generic query path remain domain-neutral; no healthcare-specific tabs or branches were added. | No new global synthesis proof for the new formats. |
| H10 Evaluation | Each pack/format has focused tests, smoke evidence, and full-suite regression evidence. | These are mostly extraction tests, not a formal golden-set evaluation of citation precision, conflict honesty, refusal correctness, or cross-format answer quality. |
| H11 Human-in-loop | Existing adjudication/pinning model remains the correct place for identity and conflict decisions. | No namespace collision queue or observation-identity adjudication workflow was exercised. High-impact identity merges need explicit review policy. |
| H12 FinOps | Existing metrics/cost modules remain shared and domain-blind. | No new query-class measurements for banking/HL7/FHIR. |
| H13 DR/retention | Raw landing and export/import remain the rebuild foundation; new formats land as raw objects. | No rebuild-from-raw drill was performed after adding the new formats. |
| H14 Model supply chain | Deterministic connector work reduces unnecessary model dependence; no domain-specific endpoint wiring was introduced. | Residency/endpoint policy is not newly proven by these tasks. |
| H15 Write-back | No new write-back behavior; read-mostly boundary remains intact. | No new evidence required for this pack work; simulated approval path remains the limit. |
| H16 BI escape hatch | Existing generic materialization remains available for pack-derived facts/conflicts. | No new banking/HL7/FHIR materialization proof in this review. |

## Contract assessment

The domain-pack contract correctly caught and generalized the task-4 person-name collision and the task-5/6 disambiguation failures. Its `strict_identity` requirement should be extended with an identifier provenance rule: person identifiers must carry source-system/assigning-authority scope where the source format provides it. Its type checklist should also distinguish a concept/analyte from an observation/result instance, including patient, order/specimen, effective time, and source context.

The contract’s acceptance test—generic Sense board behavior on a different domain—remains valid and was successfully exercised for healthcare and banking. The newly exposed identity and observation gaps should be treated as platform contract extensions, not domain-specific exceptions.

## Recommended follow-ups

1. Add an explicit identity-provenance/namespace requirement to H8 and the domain-pack contract; preserve assigning authority/system from HL7 PID-3 and equivalent FHIR identifiers.
2. Model clinical observations as distinct instances linked to analyte concepts rather than using analyte identity as the result entity key.
3. Add golden cross-format evaluation cases for same ID/different authority, same patient/same analyte/multiple observations, and unresolved subject references.
4. Exercise drift, late-arrival/replay, reprocess, and rebuild-from-raw scenarios before elevating the interoperability claim beyond POC scope.

**Disposition:** Architecture remains coherent and domain-pack work has not drifted, but healthcare-grade interoperability should remain explicitly out of scope until the identity namespace and observation-instance gaps are closed or governed as known limitations.
