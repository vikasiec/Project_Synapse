# Task 6 findings — hospital_management complete, full chain proven

**From:** Claude · **Date:** 2026-07-19 · **Ledger row:** Active_File.md ID 6

## What was built

`Treatment` and `Billing` — same mechanism as every prior pack type in this
domain (ontology L1 entry + one `RuleExtractor._extract_X` method, no core
changes). Disambiguation guards matter here specifically because `billing.csv`
carries `treatment_id` as a foreign key without `appointment_id`, so
`_looks_like_treatment` requires *both* `treatment_id` and `appointment_id`
present — confirmed by `test_billing_row_not_mistaken_for_treatment`.

## Result — the full chain, end to end

`scripts/smoke_hospital_full_chain.py` lands all 5 CSVs in dependency order:

| File | Rows | Extracted | Joined |
|---|---|---|---|
| patients.csv | 50 | 50 | — |
| doctors.csv | 10 | 10 | — |
| appointments.csv | 200 | 200 | 200/200 to Patient + Doctor |
| treatments.csv | 200 | 200 | 200/200 to Appointment |
| billing.csv | 200 | 200 | 200/200 to Patient + Treatment |

**660/660 rows land, 460/460 identity+event rows extract with facts, every
join resolves.** One bill reconstructs its entire real-world story from raw data
alone: Bill B001 ($3941.97, pending) -> Treatment T001 (Chemotherapy) ->
Appointment A001 (Therapy, Scheduled, 2023-08-09) -> patient Alex Smith, seen by
Dr. Sarah Smith (Pediatrics). Zero hand-mapping beyond the domain pack itself —
this is the "whatever data comes together, minimal hand-mapping" thesis working
on 5 genuinely independent raw sources.

`hospital_management/` is now fully covered — this closes out the dataset that
started with task 1.

## Carrying forward Grok's task-5 nits (still accurate for task 6)

- **Land-order dependent**: joins only resolve if referenced entities (Patient
  before Appointment, Appointment before Treatment, etc.) have already landed.
  This is honest H6 behavior (reprocess can complete stragglers later), not
  silently wrong — but worth flagging again since it now applies to a 4-deep
  chain, not just one hop.
- `l1_by_domain["hospital_ops"]` in `ontology.py` still only maps to
  `("Patient", "Patient")` — dead code now that 5 types share the domain, since
  every type is handled by its own early-return branch before that dict is
  reached. Harmless but worth a cleanup pass later, not urgent.

## Evidence

`tests/test_treatment_billing_extract.py` (4/4, including a same-entity-id
consistency check across the whole chain). Full suite: 108/108 (was 104/104
after task 5 — 4 new tests, all else green).
