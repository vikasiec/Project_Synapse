# Task 1 findings — hospital_management dataset probe

**From:** Claude · **Date:** 2026-07-19 · **Ledger row:** Active_File.md ID 1
**Applies constraint from:** GROK_FEEDBACK_platform_vs_domain_2026-07-19.md (core stays domain-blind; healthcare = pack)

## Baseline (before any code change)

Ran `scripts/smoke_hospital_csv.py` against all 5 files as-is:

| File | Rows | Landed | Entities extracted | Facts |
|---|---|---|---|---|
| patients.csv | 50 | 50 | 0 | 0 |
| doctors.csv | 10 | 10 | 0 | 0 |
| appointments.csv | 200 | 200 | 0 | 0 |
| billing.csv | 200 | 200 | 0 | 0 |
| treatments.csv | 200 | 200 | 0 | 0 |

**Finding A:** raw landing (schema-on-read, no upfront mapping) works cleanly on entirely new data — 660/660 rows land with lineage. **Finding B:** 0 entities/facts extract, because none of the existing rule patterns (`SERVICE_RE`, `LAB_SIGNAL_RE`, `EMPLOYEE_RE`, `CUSTOMER_RE`) match this data's keys.

**Finding C (architectural, important):** `dual_path.py` has a hard constraint — `if primary is None: return DualPathResult(entity_name=None, ...)` with the comment "Path B alone cannot invent entity in Phase 2 stub." This means the Gemini/LLM residual path *never even runs* when Path A finds nothing — it only ever attaches facts to an entity Path A already created. So today, an entirely-unrecognized data shape gets zero help from the LLM, not partial help. This is a real limitation worth a future ledger row of its own (not fixed here — out of scope for task 1).

## Change made (domain pack, per Grok's constraint)

Added `Patient` as a new L1 ontology type + one `RuleExtractor._extract_patient` method, mirroring the existing `LabResult`/`clinical_lab` pattern exactly (same file locations, same registration style: `_L1` list in `ontology.py`, `govern_extract` early-return branch, `l1_by_domain` entry, `_STORAGE_ALIASES`, `compatible_types` family). No `if healthcare:` branches added to orchestrator, store, api, or Sense board — those stay domain-blind, per the constraint.

Detection guard: `PATIENT_SIGNAL_RE` (`patient_id` key) **and** `_looks_like_patient` (patient_id + at least one identity field: first_name/last_name/insurance_provider/date_of_birth) — both required. This deliberately keeps `appointments.csv`/`billing.csv`/`treatments.csv` (which only reference `patient_id` as a foreign key, no identity fields) from being mis-extracted as broken patient records. Confirmed by `test_appointment_row_does_not_falsely_become_a_patient`.

Patient is also its own ER family (`compatible_types`) — it will never merge with `Person`/`IdentityPrincipal` in entity resolution, so a patient and an employee with the same name stay distinct. Confirmed by `test_patient_and_employee_never_share_er_family`.

## After the change

| File | Entities extracted |
|---|---|
| patients.csv | **50 / 50** |
| doctors.csv | 0 |
| appointments.csv | 0 |
| billing.csv | 0 |
| treatments.csv | 0 |

One file now extracts fully and cleanly with zero hand-mapping beyond the domain pack itself. Tests: `tests/test_patient_extract.py` (6 tests, all pass), full suite 96/96 pass.

## Remaining gap (for a follow-up row, not done here)

`doctors.csv`, `appointments.csv`, `billing.csv`, `treatments.csv` are still unextracted. They are **not** independent identity records the way `patients.csv` is — they're relational/event rows that reference `patient_id`/`doctor_id`/`appointment_id` as foreign keys. The natural modeling is **not** four more top-level entity types; it's Facts/Events attached to the `Patient`/`Doctor` entities (e.g. `has_appointment`, `billed_amount`, `treatment_type` as time-stamped facts keyed by the referenced entity), which is closer to the `Event`/temporal pattern already used for `checkout_incident`. Building that is real work and belongs in its own ledger row, done as a pack extension, not squeezed into this one.

## Important honest finding: this dataset does not contain natural multi-source disagreement

Task 1's stated goal was to "prove multi-source disagreement detection (same patient across 5 files)." Having now looked at the actual data: **this specific dataset can't prove that**, and forcing a fake conflict would be dishonest. `patients.csv` is the sole source of truth for patient demographics — `appointments.csv`/`billing.csv`/`treatments.csv` never repeat those attributes, they only reference `patient_id`. This is a clean, single-source, auto-generated relational export, not messy multi-system real-world data with the kind of duplication/inconsistency that Synapse's conflict engine exists to catch.

To actually prove the conflict-detection thesis in healthcare, one of two things is needed next:
1. **Synthesize a second view** of the same patients (e.g. a "front desk intake" variant of `patients.csv` with deliberately different values for a few patients — insurance provider, contact number) — same pattern already used by `checkout_incident`/`billing_customer` scenarios, which hand-author known disagreements.
2. **Source messier real/semi-real data** — the already-staged `pathology_health_markers/` or `synthetic_medical_symptoms/` datasets might naturally disagree with `lab_test_results_public.csv` on overlapping patients/tests; worth checking before authoring synthetic conflicts.

Recommend option 1 as the next ledger row — it's small, proves the exact thesis, and follows established precedent.
