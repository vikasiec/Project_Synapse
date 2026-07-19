# Task 5 findings — Doctor + Appointment domain pack, real cross-entity join

**From:** Claude · **Date:** 2026-07-19 · **Ledger row:** Active_File.md ID 5

## What was built

Two more `hospital_ops` L1 types, same mechanism as `Patient`/`LabResult` (ontology
entry + one `RuleExtractor._extract_X` method, no core/orchestrator/store/api
changes):

- **`Doctor`** — mirrors `Patient` exactly, including `strict_identity=True`. No real
  name collisions exist in `doctors.csv` today (10 unique names), but doctor-name
  collisions are realistic at hospital scale, so it defaults safe rather than waiting
  for a second bug like task 4's.
- **`Appointment`** — Event-family (like the existing `SupportTicket`), canonical
  name = `appointment_id`. At extract time it resolves `patient_id`/`doctor_id`
  strings to real `Patient`/`Doctor` entity ids via the new
  `find_by_external_id_value` helper (built for task 4's strict-identity fix), and
  stores both the raw ID string and the resolved entity id as separate facts. If the
  referenced Patient/Doctor hasn't landed yet, the raw ID still lands — an honest
  partial link, not a failure, consistent with H6 (reprocess is normal).

## Result

Landing `patients.csv` -> `doctors.csv` -> `appointments.csv` into one store
(`scripts/smoke_hospital_join.py`):

- 200/200 appointments extracted.
- **200/200 resolved both `patient_entity_id` and `doctor_entity_id`** — a complete,
  real join, not a partial one.
- Sample output confirms the join is genuinely useful, not just structurally
  present: e.g. appointment A001 -> patient "Alex Smith", doctor "Sarah Smith"
  (Pediatrics), 2023-08-09, reason "Therapy", status "Scheduled" — reconstructed
  entirely from three independent raw CSVs with zero hand-mapping beyond the two
  small pack extensions above.

Combined with task 1's `Patient` and task 4's conflict proof, `hospital_management`
is now 3 of 5 files fully extracted and joined (`patients.csv`, `doctors.csv`,
`appointments.csv` — 460/660 rows). `billing.csv` and `treatments.csv` remain, and
would follow the same pattern (`Billing`/`Treatment` Event types linking to
`Appointment`/`Patient`) — natural next task, not started here.

## One regression caught and fixed (test debt, not a real bug)

`tests/test_patient_extract.py::test_appointment_row_does_not_falsely_become_a_patient`
(written in task 1, before `Appointment` existed) asserted appointment rows extract
**nothing**. That assumption is now correctly false — the whole point of task 5 was
to make them extract. Fixed the test to check the property it actually cared about
(an appointment must never be mistyped as `Patient`), which still holds. Full suite:
104/104 after the fix (was 98/98 after task 4 — 6 new tests from this task).
