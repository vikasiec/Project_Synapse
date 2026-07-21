# Healthcare Extraction Redesign — Implementation Report

**Date:** 2026-07-21 · **Driven by:** `Claude_Instructions.md` · **Author:** Claude (no other AI/model calls used to produce this)

This closes out the convergence-test findings in
`CLAUDE_NEWDATA_CONVERGENCE_FINDINGS_2026-07-21.md`. That doc diagnosed
*why* extraction was overfit to sample shapes; this one is the fix, done
to the standard, not to the file.

---

## Step 1 — Standard domain ontology & grammar mapping

Written as code, not just prose, in `synapse/coding_systems.py` (full
module docstring there). Summary:

1. **Coding systems.** HL7v2 OBX-3 component 3 (Table 0396: `LN`=LOINC,
   `SCT`/`SNM`=SNOMED CT, `RXNORM`=RxNorm, `L`=local) and FHIR
   `coding[0].system` URIs (`http://loinc.org`, `http://snomed.info/sct`,
   RxNorm's NLM URI) are two encodings of the *same* signal. Both were
   being read for code+display and discarded for system — the actual bug
   behind "HL7 and FHIR never converge on the same analyte."
2. **FHIR resource links.** `Observation.subject` is a `Reference`; real
   bulk exports carry it as a bare `"Patient/<id>"` string, not an inline
   resource. Requiring an embedded `Patient` (the original scope) only
   works on hand-assembled demo bundles.
3. **HL7v2 message types.** The tokenizer (`synapse/hl7v2.py`) already
   parses any message type generically. Only the semantic layer was
   hardcoded to one type.
4. **CSV/LIS header synonyms.** `CSV_FIELD_SYNONYMS` in the same module —
   canonical field → header aliases, scoped per ontology type.

## Step 2 — Audit

Already delivered in full, with evidence, in
`CLAUDE_NEWDATA_CONVERGENCE_FINDINGS_2026-07-21.md` §1–4. Not repeated
here.

## Step 3 — Implementation

### 1. `normalize_code(system, code)` — shared HL7/FHIR identity

`synapse/coding_systems.py`. Both `_extract_hl7_oru` (now reading OBX-3
component 3, previously discarded) and `_extract_fhir_bundle` (now
reading `coding[0].system` via new `fhir.coding_system()`) key LabResult
identity through this one function.

**Honesty check, not skipped:** New Data's own fixture does *not*
actually converge through this — its HL7 side emits `TSH` and its FHIR
side emits `LOINC-TSH` for the same real-world result, and neither is a
conformant LOINC code (`3016-3`). Special-casing a `"LOINC-"` prefix
strip to make *this file* converge would be exactly the sample-fitting
the instructions forbid. Instead: `tests/test_code_normalization.py`
proves convergence against a **conformant** self-authored fixture (real
code `3016-3` on both sides), and the fixture's non-conformance is
recorded as a data-quality note, not patched around.

**Validated against the real fixture anyway** (`validate_newdata.py`,
in-process, no server, no live AI): Patient identity — which *is*
comparably encoded across all three sources (`PAT-88301` bare ID) — now
converges to **exactly 120 Patient entities** (was fragmenting into up to
320: 120 LIS + 100 HL7 + 100 FHIR) across LIS CSV, HL7, and FHIR. LabResult
counts (1,380 = 690 HL7 OBX + 690 FHIR Observations, unconverged) confirm
the code-mismatch is real fixture data, not a normalizer bug — if it were
a bug, this number would look different depending on which format landed
first, and it doesn't.

### 2. FHIR external-reference stub-entity linking

`_extract_fhir_bundle` rewritten (`synapse/extraction.py`) to resolve
each Observation's subject independently — embedded resource first
(unchanged), then a stub `Patient` entity keyed on the bare reference id,
named from `subject.display` when the source provided one (a real FHIR
convention for exactly this case), at reduced trust (0.55 vs 0.85 for a
fully-resolved record). Handles multiple distinct patients in one bundle,
not just the single-patient-per-bundle shape the original scope assumed.

**Result:** the 690-observation, 100-patient, zero-embedded-Patient bundle
that extracted nothing before now extracts fully — 1/1 landed episode
produces entities, all 100 patients present, none conflated.

One existing test's premise directly conflicted with this deliverable
(`test_observation_for_unresolvable_subject_skipped` assumed *any*
non-embedded reference should be dropped) — split into two tests in
`tests/test_fhir_extract.py` that distinguish "no usable reference at
all" (still skipped) from "external reference, not embedded" (now a
stub, by design), plus a new bulk-bundle test for the no-Patient-at-all
shape.

### 3. CSV schema-synonym mapping

`resolve_synonyms()` / `_parse_kv_for()` — additive layer applied to
Patient, Doctor, LabResult, AccountHolder, Account, and Transaction
extraction. A header already using the canonical vocabulary is untouched
(zero behavior change, confirmed by the full existing suite staying
green); an unrecognized-but-synonymous header now resolves onto the same
attribute.

**Scoped deliberately, not maximally:** LIS `lab_orders`/`order_line_items`
and middleware `worklist`/`raw_results`/`specimen_tubes` were **not**
wired through this mapping. They describe LabOrder/Specimen/InstrumentTask
concepts that don't exist in the ontology at all yet — inventing new L1
types is real anticipatory design work, but a larger scope than "map
messy headers to existing attributes," and wiring `mw_raw_results.csv`
into the existing `_extract_lab` path specifically would have
reintroduced the exact cross-patient LabResult collision bug the
HL7/FHIR paths were already fixed to avoid (that path's entity key isn't
patient-scoped, unlike the HL7/FHIR ones) — the multi-hop join needed to
patient-scope it (row → task_id → barcode_id → patient_ref) can't be done
from one CSV row in isolation. Flagging this honestly as a real,
correctly-scoped follow-up rather than forcing it.

**Result:** `lis_patient_master.csv` — the one file in this batch that
*does* map cleanly onto an existing type — goes from 0/120 to 120/120
rows extracted.

### 4. Bounded residual (LLM) path

Two independent defects, both fixed:

- **Wrong text reaching the model at all.** `dual_path.py`'s residual-text
  computation is now format-aware (`_compute_residual_text`): for
  HL7/FHIR, it extracts *only* the genuine free-text carrier (NTE
  segments / FHIR `note` arrays — new helpers in `hl7v2.py`/`fhir.py`) and
  treats an empty result as final, not a signal to fall back to the raw
  message. Every OBX/PID/OBR field already has a dedicated, correctly-typed
  extraction path; re-submitting the whole structured message wasted a
  live Gemini call per HL7 message and invited the model to reinterpret
  values already read precisely.
- **Unbounded predicate vocabulary.** `ontology.py`'s new
  `RESIDUAL_PREDICATE_VOCAB` (per-domain allowlist) and
  `canonicalize_residual_predicate()` (synonym folding, e.g.
  `ordering_provider`→`ordering_physician`) are applied once, centrally,
  in `DualPathExtractor.extract()` — so every backend (Gemini, heuristic,
  future) is bounded the same way. The Gemini prompt itself
  (`llm_gemini.py`) is now built from the same per-domain vocabulary
  instead of a fixed SRE-flavored example list, so a clinical episode is
  asked for clinical predicates, not shown `risk_flag`/`incident_theme` by
  default.

**Validated:** re-running all of New Data through the fixed engine
in-process produced **zero** residual facts at all (`HeuristicResidualExtractor`,
no live AI call per the "no other AI usage" instruction for this session's
own validation loop) — confirming the structured-text-treated-as-residual
bug is gone, not just throttled. `tests/test_dual_path.py` adds explicit
coverage: an HL7 message with no NTE segment sends nothing to residual; one
with an NTE segment sends *only* that segment's text, never the pipe-delimited
body; an out-of-domain predicate is dropped; a known synonym is folded.

---

## Verification

- **Baseline, before any change:** `python -m unittest discover` → 189/189
  green (`SYNAPSE_GRAPH_BACKEND=local`, no live Gemini — both pre-existing,
  offline-safe fallbacks this proof already had, just not defaulted to in
  this dev environment's `.env`).
- **After all four changes:** 204/204 green (15 new tests: code
  normalization × 6, dual-path residual gating/bounding × 7, FHIR
  stub-entity × 3 net-new replacing 1 revised, patient CSV synonym × 1).
  No existing test was weakened to make it pass; the one test whose
  premise the new behavior deliberately supersedes was replaced with two
  tests covering the distinction precisely (see item 2 above).
- **Against the real fixture**, in-process, no server, no live AI call:
  `lis_patient_master.csv` 0→120/120 rows extracted; FHIR bundle 0→1/1
  episodes extracted (all 100 patients, all 690 observations landed
  against a correctly-distinguished patient); Patient identity converges
  to 120 entities across all three formats (not 320); residual path fires
  zero times on this dataset.

## What's still honestly not done

- `lis_lab_orders.csv`, `lis_order_line_items.csv`,
  `mw_instrument_worklist.csv`, `mw_raw_results.csv`,
  `mw_specimen_tubes.csv` — need new L1 ontology types (LabOrder,
  Specimen/Tube, InstrumentTask) plus a multi-hop join capability the
  extraction architecture doesn't have yet (single-row, stateless
  extraction). Real work, correctly out of this pass's four scoped items.
- LabResult identity does not converge across HL7/FHIR *for this specific
  fixture* — by design, since the fixture's own code values aren't
  standards-conformant on both sides. `normalize_code` is proven correct
  against a conformant fixture; the New Data fixture's own data quality is
  a separate, documented issue.
- HL7 ADT/ORM/SIU message types remain unregistered in
  `_HL7_MESSAGE_HANDLERS` — structurally pluggable now, not implemented,
  since none of this proof's actual data needs them yet.
