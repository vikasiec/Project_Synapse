# Features Delivered — Project Synapse Healthcare Vertical

**Status:** Consolidated 2026-07-19 from `Active_File.md` rows 1-17.
**Contract reference:** `docs/DOMAIN_PACK_CONTRACT.md` — every feature below follows
its 5-part pack shape (ontology L1 type, extraction rule + disambiguation guard,
optional authority/boost data, sample data, tests) with zero core changes except
the two sanctioned generic mechanisms noted below.

## New L1 ontology types

| Type | Domain | `strict_identity` | Links to | Row |
|---|---|---|---|---|
| `Patient` | `hospital_ops` | Yes | — (anchor identity) | 1 |
| `Doctor` | `hospital_ops` | Yes | — (anchor identity) | 5 |
| `Appointment` | `hospital_ops` | No | `Patient`, `Doctor` | 5 |
| `Treatment` | `hospital_ops` | No | `Appointment` | 6 |
| `Billing` | `hospital_ops` | No | `Patient`, `Treatment` | 6 |
| `LabResult` (pre-existing, retrofitted) | `clinical_lab` | **Yes, added row 13** | `Patient` (via HL7/FHIR only) | 1, 13, 15 |
| `AccountHolder` | `banking` | Yes | — (anchor identity) | 10 |
| `Account` | `banking` | No | `AccountHolder` | 10 |
| `Transaction` | `banking` | No | `Account` | 10 |

## New extraction rules (`synapse/extraction.py`, `RuleExtractor`)

One `_extract_X` method + disambiguation guard per type above. Every guard was
designed against a real collision risk in the actual data, not hypothetically:
- `Patient` vs. `Appointment`/`Billing`/`Treatment`: `patient_id` alone is a
  foreign key in those files — guard requires an identity field too.
- `Account` vs. `Transaction`: `account_id` alone is a foreign key in
  `transactions.csv` — guard requires an account-attribute field too.
- `Treatment` vs. `Billing`: both carry `treatment_id`; guard requires
  `appointment_id` (Treatment-only) too.
- HL7/FHIR `LabResult`: guard requires the *patient-scoped* key
  (`patient_id:test_code`), not a bare test code — this is the row-13 bug fix,
  now the standard pattern.

## New generic core mechanisms (the only sanctioned exceptions to "core stays domain-blind")

1. **`OntologyType.strict_identity`** (`synapse/ontology.py`) — a type opts in to
   blocking entity resolution by ID value across sources instead of by name.
   Default `False`; mandatory for any type whose canonical name is a real person
   (per `docs/DOMAIN_PACK_CONTRACT.md` §4). Fixed a real patient-safety bug (row 4)
   and a real clinical-correctness bug (row 13).
2. **`EntityResolutionService.find_by_external_id_value`** — cross-source ID-value
   blocking, used by every cross-entity link (`Appointment→Patient`,
   `Treatment→Appointment`, `Billing→Patient/Treatment`, `Account→AccountHolder`,
   `Transaction→Account`, HL7/FHIR `LabResult→Patient`).
3. **`SemanticStore.known_acl_domains()`** (row 12) — derives the demo/UI viewer
   principal's domain access from whatever ACL domain tags are actually landed in
   the store, instead of a hardcoded domain-name list. Fixed a real 403 on the
   banking pack's ASK path through the actual UI request shape.
4. **`TemporalService.apply_for_entity` generalized** (row 14) — previously gated by
   a hardcoded `OPERATIONAL_PREDICATES` infra/revenue whitelist that silently
   excluded every healthcare/banking predicate from temporal supersession. Now
   applies to any predicate; safety comes from the existing `(predicate,
   source_system)` grouping, not a predicate allowlist. Fixed a real false-conflict
   bug: the same patient's repeated lab result over time looked like an open
   disagreement instead of an updated value.
5. **`identifier_authority` / `normalize_authority`** (`synapse/entity_resolution.py`,
   row 23) — `find_by_external_id_value` and `get_or_create` now accept an optional
   assigning-authority scope for `strict_identity` types, so two different
   real-world sources issuing the same bare ID to two different people no longer
   silently converge. Comparison is normalized (`"HIS"` vs `"urn:oid:HIS"` both
   match), not raw string equality, to preserve the already-proven CSV/HL7/FHIR
   convergence. Closes the PID-3 gap Codex's rows 13/14 reviews independently
   flagged as the main remaining architectural limitation.
6. **`observation_instance_id` scoping on `LabResult`** (Codex, row 25, reviewed by
   Claude) — `LabResult` identity now incorporates the source's own instance
   identifier (FHIR `Observation.id`/`basedOn`, HL7 OBR-2 placer order falling
   back to OBR-3 filler order) when present, retaining the prior patient+test key
   as a fallback. **Corrects a real over-eager part of row 14's fix**: two
   genuinely separate lab orders a month apart are two distinct real-world facts
   and must both stay visible, not have one supersede the other as row 14's
   original test asserted for that same fixture data. `identifier_authority`
   (item 5) stays intact — verified unchanged at both call sites.

## New interoperability formats (real invention, not pack repetition)

| Format | Module | Scope | Row |
|---|---|---|---|
| HL7v2 | `synapse/hl7v2.py` + `synapse/connectors/hl7_file.py` | `MSH`/`PID`/`OBR`/`OBX` segments, self-declared separators (MSH-1/MSH-2), ORU^R01 message type only | 11, 13 |
| FHIR | `synapse/fhir.py` + `synapse/connectors/fhir_file.py` | `Bundle` of inline `Patient`+`Observation` resources, local reference resolution only | 15 |

Both reuse the existing `Patient`/`LabResult` types — no format-specific ontology
entries. The proof that matters: patient P001 ("David Williams") converges to
**one entity across three structurally unrelated formats** (CSV, HL7v2, FHIR) in
one store (row 15).

## Core bugs fixed (see `master_plan.md` §5 for full narrative)

- Cross-format/cross-source entity resolution safety (`strict_identity`, rows 4, 13).
- `query.py` answer-narration domain-blindness (row 9).
- `api.py` demo-principal domain-tag hardcoding (row 12).
- `temporal.py` supersession predicate hardcoding (row 14).

**Pattern to watch:** three of these four bugs (rows 9, 12, 14) are the same root
cause — a hardcoded "known domains/predicates" list quietly baked into code meant to
be domain-blind — found independently in three different core modules. Worth an
explicit audit pass over remaining core modules for the same pattern before it's
found a fourth time by accident.

## Sense board (`synapse/api.py`, `synapse/static/index.html`) — verified, not changed

Zero code changes required to the UI/HTML across every domain tested (checkout,
healthcare, banking) — the 5 panels (RAW / MEANING / CONFLICTS / ASK / EMIT) proved
genuinely domain-blind by demonstration (rows 9, 12), not just by inspection. (The
API's principal-derivation *logic* did need a fix, row 12 — the UI/panel contract
itself never changed.)

## Test coverage added this arc

`tests/test_patient_extract.py`, `test_doctor_appointment_extract.py`,
`test_treatment_billing_extract.py`, `test_banking_extract.py`, `test_hl7v2.py`,
`test_hl7_extract.py`, `test_fhir.py`, `test_fhir_extract.py`,
`test_query_generic_narration.py`, `test_principal_from_body.py` (row 12),
`test_temporal_generic.py` (row 14) — full suite at 158/158 as of row 14's fix.

---

## New platform capability (not a domain pack): Semantic Discovery & Curation

**Status:** Added 2026-07-22, `Active_File.md` rows 38-46. Unlike everything
above, this is core platform infrastructure, not a per-vertical pack — it
implements Major Goals 1-4 of `docs/Master Architectural Specification &
Implementation Roadmap.md` (a separate, uncommitted spec).

| Capability | File | Notes |
|---|---|---|
| Schema field profiling | `synapse/profiling.py` | `data_type`/`entropy_score`/`regex_pattern_match`/`min_hash_sketch` per observed field, plus a stdlib char-trigram hashing-trick semantic vector (no embedding library installed) with a small synonym-canonicalization step (classical COMA/Cupid-style schema-matching technique, e.g. `cust`/`client`→`customer`, `id`/`num`→`identifier`) |
| Hybrid candidate scoring | `synapse/matching.py`, `POST /v1/explore/analyze` | Exact spec formula: `S_total = 0.45·VectorSim + 0.40·ValueOverlap + 0.15·GraphProximity`; thresholds 0.85 high-confidence / 0.50 candidate / drop below |
| Ontology relationship registry | `synapse/ontology.py` (`RelationshipEdge`), `POST /v1/ontology/relationships` | ACCEPT/REJECT/RELABEL curation actions; ACCEPT wires into `entity_resolution.py::link_schema_fields` as new ER blocking metadata |
| Transitive learning | `synapse/matching.py::transitive_candidates` | A newly-profiled source is auto-evaluated against already-linked sources in the registry |
| New Vite/React UI | `ui/`, served at `/app` | Catalog (browse confirmed relationships) + Explore (guided journey: pick source → analyze → full-canvas node-link graph via `reactflow` → explanation drawer → curate). Legacy Sense board stays at `/` until panel parity is reached. |

VnV: all 4 of the spec's own VnV Layer scenarios pass as named tests (see
`tests/test_profiling.py`, `test_explore_analyze.py`,
`test_ontology_relationships_api.py`). Full suite: 232/232.

**Not built (Phase 2 of that spec, gated):** semantic translation/CDM
bridge, cross-system conflict routing beyond what already exists above,
FHIR/BIAN/OpenAPI federated exports. Gated on Vikas's explicit Phase 1
sign-off per the spec's own execution gate — not started.
