# Task 25 — Codex findings

## Design and implementation

The design note in `CODEX_OBSERVATION_INSTANCE_DESIGN_2026-07-20.md` records the
decision. FHIR now keys a LabResult with `Observation.id` (or `basedOn` when no
ID exists); HL7v2 uses the nearest OBR-2 placer order, falling back to OBR-3
filler order. Both retain the patient plus assigning-authority scope and fall
back to the legacy patient-plus-test key when no instance identifier exists.
The chosen instance ID is stored as `observation_instance_id` for auditability.

## Verification

- Baseline before row 25 implementation: 167/167 tests passing.
- After implementation and semantic test updates: 168/168 tests passing.
- New regression coverage proves two distinct FHIR Observation IDs produce two
  LabResult entities; the updated HL7 test proves two distinct order instances
  do not collide.
- Row 24 fixtures deliberately share the same Observation.id, so the same-time
  two-source conflict remains one LabResult with two competing current values.

Row 25 is ready for Claude review; Codex does not mark it DONE.
