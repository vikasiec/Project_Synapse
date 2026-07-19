# Task 11 findings — real HL7v2 parsing, the actual invention gap closed

**From:** Claude · **Date:** 2026-07-19 · **Ledger row:** Active_File.md ID 11

## Why this task is different from every prior one

Tasks 1-10 all built extraction rules for `key: value` text (CSV rows
converted to that shape by `CsvDropConnector`). That's real, but it's not
what instruments, middleware, or LIS/HIS systems actually emit — they speak
HL7v2 (pipe-delimited segment messages) or FHIR. This was flagged explicitly,
twice, earlier in this engagement as the genuine "garage-to-production" gap:
everything proven so far worked on clean, already-tabular data. This task
closes that gap for real, not partially.

## What was built

- **`synapse/hl7v2.py`** — a real HL7v2 tokenizer, not a toy. It parses using
  the message's own self-declared separators (MSH-1 field separator, MSH-2
  encoding characters) rather than hardcoding `|`/`^`/`~` — this is the
  actually-correct way to parse HL7v2. Scoped honestly: generic segment/
  field/component/repetition structure for any segment type, no Z-segment
  support, no escape-sequence decoding, no full message-type catalog. That
  scope is stated in the module docstring, not hidden.
- **`synapse/connectors/hl7_file.py`** — `Hl7DirectoryConnector`, a
  domain-blind connector (one `.hl7` file = one message = one `ChangeEvent`),
  same shape as `csv_drop.py`.
- **`RuleExtractor._extract_hl7_oru`** — scoped to ORU^R01 (observation
  result) messages, the message type instruments/LIS actually use to report
  lab results. Extracts a `Patient` from the PID segment and one `LabResult`
  per OBX segment, reusing the *existing* `Patient` and `LabResult` ontology
  types rather than inventing new ones — HL7 is a new **format**, not a new
  **domain**.

## The result that actually matters

Landed `patients.csv` (hospital_management, task 1's data) and then 3
synthetic HL7 ORU^R01 messages into the same store — one of which is for
patient P001, the same "David Williams" the CSV already knows about.

**David Williams resolved to exactly one entity across two structurally
unrelated raw formats** (comma-delimited CSV vs. pipe-delimited HL7,
completely different parsers, completely different connectors) — proven by
`test_same_patient_resolves_across_csv_and_hl7` and the live smoke script.
This is the actual thesis this project set out to prove, at its hardest: not
"can we extract structured facts from one clean format," but "when the same
real thing arrives via genuinely different pipes, does it converge into one
identity." It does, and it did so using nothing but the existing
`external_id`/`strict_identity` mechanism already proven in task 4 — no new
resolution logic needed.

Concretely: 3 messages -> 6 `LabResult` entities (1 + 3 + 2 OBX segments per
message) + 3 `Patient` entities (one of which merges with the pre-existing
CSV-landed patient), every field correctly parsed including the abnormal-flag
column (`H`/`N`/`L`), reference ranges, units, and result status.

## Honesty boundaries (stated, not hidden)

- Only ORU^R01 is handled; other HL7 message types (ADT, ORM, ...) fall
  through as unrecognized, same honest-partial pattern as every other pack.
  Verified by `test_non_oru_message_type_not_extracted`.
- Malformed/truncated HL7 (missing MSH separators) fails to parse and falls
  through rather than crashing or guessing — `test_malformed_hl7_falls_through_honestly`.
- No FHIR support yet — a real second format, deliberately not attempted in
  this task to keep scope bounded (HL7v2 alone is substantial, correctly-done
  invention work).

## Core stayed domain-blind

Grepped `orchestrator.py`/`store.py`/`api.py`/`query.py`/`control_plane.py`/
`index.html` for HL7-specific terms: zero hits. The parser and connector are
both generic primitives (any domain could land HL7-shaped data through them);
only `_extract_hl7_oru`'s ORU^R01 semantics are domain-pack logic, correctly
scoped to `extraction.py`.

## Evidence

`tests/test_hl7v2.py` (9/9, parser unit tests), `tests/test_hl7_extract.py`
(5/5, extraction + cross-format resolution), full suite 131/131 (was 117/117
before this task).
