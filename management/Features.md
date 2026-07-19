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

## Sense board (`synapse/api.py`, `synapse/static/index.html`) — verified, not changed

Zero code changes required across every domain tested (checkout, healthcare,
banking) — the 5 panels (RAW / MEANING / CONFLICTS / ASK / EMIT) proved genuinely
domain-blind by demonstration (row 9), not just by inspection.

## Test coverage added this arc

`tests/test_patient_extract.py`, `test_doctor_appointment_extract.py`,
`test_treatment_billing_extract.py`, `test_banking_extract.py`, `test_hl7v2.py`,
`test_hl7_extract.py`, `test_fhir.py`, `test_fhir_extract.py`,
`test_query_generic_narration.py` — full suite at 150/150 as of row 15 (row 17's
process fixes required no code/test changes).
