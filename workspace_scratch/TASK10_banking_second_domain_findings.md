# Task 10 findings — the domain pack contract, tested for real on a second domain

**From:** Claude · **Date:** 2026-07-19 · **Ledger row:** Active_File.md ID 10

## What this task actually tested

Not "can Claude repeat the healthcare pattern" — that would just prove memory.
The real question: **does `docs/DOMAIN_PACK_CONTRACT.md`, written after healthcare,
actually work as a followable process for someone (or something) that didn't
build healthcare?** I tried to answer that by treating the contract as the
instructions and checking off each item explicitly rather than working from
habit.

## What was built

Synthetic dataset (`.data/synthetic_banking/`, 8+10+15 rows — deliberately small,
matching task 1's size discipline, not hospital_management's real-data scale)
with an intentional name collision: two different "John Smith" account holders
(`H001`, `H003`), same as task 4 found by accident in real data — here, planted
on purpose to test whether the contract's checklist item 1 actually gets
followed without a bug forcing it.

Three L1 types, same mechanism as every healthcare type (ontology entry + one
`_extract_X` method, zero core changes): `AccountHolder` (`strict_identity=True`,
set *before* running anything, per checklist item 1 — not discovered after a
failure this time), `Account` (links to `AccountHolder`), `Transaction` (links
to `Account`).

## Result: worked cleanly on the first attempt

- Baseline: 33/33 rows land, 0 extracted (confirmed no accidental collision
  with existing rules before writing any pack code — checklist discipline,
  not skipped).
- After the pack: 8 AccountHolders, 10 Accounts, 15 Transactions — matches
  every CSV row count exactly.
- **10/10 accounts resolved to their holder, 15/15 transactions resolved to
  their account** — full join, first try.
- **The two "John Smith" holders stayed distinct** (`test_two_holders_sharing_a_name_stay_distinct`)
  — no repeat of task 4's bug, because `strict_identity` was applied per the
  checklist instead of discovered after damage.

Disambiguation guards needed real thought (checklist item 2), not
copy-paste: `accounts.csv` carries `holder_id` as a foreign key (guard needs
`holder_id` + an identity field to exclude it), and `transactions.csv` carries
`account_id` as a foreign key (guard needs `account_id` + an account-attribute
field to exclude it) — structurally identical to the `patient_id`/`treatment_id`
disambiguation problem from healthcare, confirming that's a real, recurring
pattern the contract correctly generalizes, not a one-off.

## Core stayed domain-blind — checked, not assumed

Grepped `orchestrator.py`/`store.py`/`api.py`/`query.py`/`control_plane.py`/
`index.html` for banking-specific terms: zero real hits (one comment in
`query.py` uses "banking" as an illustrative example in a docstring, not
logic; one grep false-positive on the HTML attribute `placeholder=`
containing the substring "holder"). Checklist item 3 passes.

## Conclusion

The contract holds. This is the real proof the platform claim needed — not
"Claude can add packs," but "the documented process, followed as written,
produces a correct pack with zero core changes and catches the one class of
bug (name-collision) it explicitly warns about, without that bug needing to
happen first." Evidence: `tests/test_banking_extract.py` (7/7), full suite
117/117 (was 110/110 before this task).
