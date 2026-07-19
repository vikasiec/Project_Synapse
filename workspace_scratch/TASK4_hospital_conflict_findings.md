# Task 4 findings — proving multi-source conflict detection in healthcare

**From:** Claude · **Date:** 2026-07-19 · **Ledger row:** Active_File.md ID 4

## What was built

`.data/kaggle_raw/hospital_management/patients_front_desk.csv` — a synthesized 10-row
"front desk re-entry" view of the first 10 real patients from `patients.csv`, authored
with 4 deliberate drifts (insurance_provider and/or contact_number changed for
P001, P003, P005, P008) and 6 exact matches (control group), same pattern already
used by `checkout_incident`/`billing_customer`.

Authority weights added (`session.py`): `HIS-Patients: 0.85` (system of record),
`FrontDesk-Intake: 0.55` (re-entry). Source-boost added (`ontology.py`
`PREDICATE_SOURCE_BOOST`, domain pack data, not core logic): HIS-Patients preferred
for `insurance_provider`/`contact_number` when both sources report, mirroring the
existing Lab-LIS-over-Spreadsheet pattern.

`scripts/smoke_hospital_conflict.py` lands both files into one store and reports
per-patient: which sources merged, and any open conflicts.

## Result (after a bug fix — see below)

- 10/10 target patients resolved to exactly **one** entity each, both sources merged.
- Exactly the 4 authored conflicts surfaced (P001, P003, P005, P008) — no false
  positives on the 6 clean patients.
- `HIS-Patients` correctly wins validity-weight ranking on every conflict (system of
  record preferred over front-desk re-entry, as authored).
- Conflicts are genuinely surfaced as `OPEN` (both values visible, not silently
  picked) — the discrepancy-first-class thesis holds for this vertical.

**Task 4's goal is proven**: the same conflict-detection engine that already worked
for checkout-incident/billing/identity scenarios works unmodified for healthcare,
once patient identity resolves correctly across sources.

## Bug found and fixed (bigger finding than the proof itself)

Before the fix, the first full run of `patients.csv` (all 50 real rows, unmodified)
already produced corruption: the real dataset contains genuine name collisions —
3 different real patients named "Michael Taylor" (`P010`, `P016`, `P046` — different
DOB, gender, address, insurance) and ~5 other duplicate-name pairs among 50 patients
(confirmed via `awk` frequency count). `EntityResolutionService.get_or_create`'s
name-fallback blocking (used when external_id lookup misses) merged all three real,
distinct people into **one entity**, silently combining their medical/insurance data.
This is a patient-safety-class defect, not a cosmetic one, and it was latent in the
existing generic ER code — this task's data was just the first thing to trigger it
(the checkout/billing/identity scenarios' hand-authored data never happened to
collide on name).

**Fix (`synapse/ontology.py`, `synapse/entity_resolution.py`):** added a
`strict_identity: bool` field to `OntologyType` (default `False`, so every existing
type's behavior is unchanged), set `True` only for `Patient`. In
`get_or_create`, strict-identity types skip name-fallback blocking entirely and
instead block on the ID *value* alone across sources (`find_by_external_id_value`) —
safe because an ID is authoritative while a name is not. No `if healthcare:` branch
was added anywhere; the mechanism is generic and any future domain pack (e.g. a
banking account holder) can opt in the same way.

Regression tests added: `test_same_name_different_patient_id_never_merges` (two real
Michael Taylors stay distinct) and `test_same_patient_id_across_sources_does_merge`
(the actual cross-source merge this task needs still works). Full suite: 98/98 pass
after the fix (was 96/96 before task 4 — 2 new tests, all else green).

## Why this matters beyond this task

This is exactly the kind of thing the original blueprint review flagged as an open
research question ("Access Control & ACLs," "Deterministic Precision") — but it
surfaced a *different* unaddressed risk neither blueprint named explicitly: **entity
resolution safety under name collision**, which is low-stakes for infra services
(two services rarely share a name) but safety-critical the moment the vertical is
people (patients, and later — banking customers). Worth flagging to Grok/Gemini as
a genuine architecture-level finding, not just a healthcare bug.
