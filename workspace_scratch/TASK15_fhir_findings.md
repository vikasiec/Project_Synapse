# Task 15 findings — FHIR, and applying task 13's lesson proactively

**From:** Claude · **Date:** 2026-07-19 · **Ledger row:** Active_File.md ID 15

## What was built

`synapse/fhir.py` — a scoped FHIR JSON parser: `Bundle` resource handling,
inline-resource extraction, local `"ResourceType/id"` reference resolution,
and small CodeableConcept/Quantity/referenceRange helpers. No external
reference fetching, no `contained` resources, no terminology validation —
stated in the module docstring, not hidden.

`synapse/connectors/fhir_file.py` — `FhirDirectoryConnector`, domain-blind,
same shape as `hl7_file.py` (one `.json` file = one Bundle = one
`ChangeEvent`).

`RuleExtractor._extract_fhir_bundle` — scoped to `Bundle` containing inline
`Patient` + `Observation` resources (the FHIR analogue of an HL7 ORU
message). Reuses the existing `Patient`/`LabResult` types.

## Applying task 13's lesson before it bit again

Codex's review (row 13) found that HL7 `LabResult` identity keyed by bare
test code let two different patients' results merge into one entity. This
task's `_extract_fhir_bundle` was written with patient-scoped `LabResult`
identity (`f"{patient_id}:{test_code}".lower()`) **from the first version**,
not discovered after a repro. Verified by
`test_two_different_patients_same_test_stay_distinct` — two patients both
getting a "Platelet Count" observation stayed correctly distinct on the
first run, no fix cycle needed this time.

Also added a safety check task 13's review didn't need to raise for HL7 (no
equivalent risk there) but is real for FHIR: `resolve_local_reference`
returning a *different* resource than the bundle's Patient must not
silently attribute the Observation to whichever patient happens to be
present — `test_observation_for_unresolvable_subject_skipped` confirms an
Observation with an unresolvable/wrong subject reference is skipped, not
mis-attributed.

## The result that matters — three formats now, not two

Landed the same patient (P001, "David Williams") via **three structurally
unrelated formats** in one store: the original `hospital_management` CSV
(task 1), an HL7v2 ORU^R01 message (task 11), and now a FHIR Bundle (this
task). All three converge on **one** `Patient` entity —
`test_real_directory_cross_format_with_csv_and_hl7` confirms the entity id
is identical before and after the FHIR bundles land. 4 `LabResult` entities
total across 3 bundles (1 + 2 + 1 Observations), with the two patients who
share a test name ("Platelet Count") staying correctly distinct.

## Honesty boundaries (stated, not hidden)

- `Bundle` only — a standalone `Patient` or `Observation` resource (not
  wrapped in a Bundle) falls through unrecognized, verified by
  `test_non_bundle_resource_not_extracted`.
- Malformed JSON falls through, not crashes —
  `test_malformed_json_falls_through_honestly`.
- Same PID-3-style limitation as HL7 (task 13, finding 2, not fixed there
  either): `identifier[0].value` is trusted as a bare ID without retaining
  an assigning-system/namespace scope. Same reasoning applies: fixing it
  would require re-namespacing identity consistently across every connector,
  which isn't warranted by this POC's data.

## Core stayed domain-blind

Grepped `orchestrator.py`/`store.py`/`api.py`/`query.py`/`control_plane.py`/
`index.html` for FHIR-specific terms (`fhir`, `resourceType`, `Bundle`):
zero hits.

## Evidence

`tests/test_fhir.py` (10/10, parser), `tests/test_fhir_extract.py` (6/6,
extraction + 3-format cross-resolution proof), full suite 150/150 (was
134/134 before this task).
