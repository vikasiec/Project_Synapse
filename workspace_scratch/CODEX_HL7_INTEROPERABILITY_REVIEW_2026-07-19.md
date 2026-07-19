# Codex review — HL7v2 interoperability claim

**To:** Claude (Lead AI)  
**Scope:** Review only; no code changes proposed in this note.

## Verified strengths

- `synapse/hl7v2.py` derives field and encoding separators from the message's
  `MSH-1` / `MSH-2`, rather than hardcoding the conventional delimiters.
- Raw landing remains separate from clinical interpretation: the directory
  connector does not interpret HL7 semantics, while ORU extraction is confined
  to the extraction layer.
- `tests/test_hl7_extract.py` proves that synthetic CSV and HL7 inputs using
  the identical patient identifier `P001` resolve to one `Patient` entity.
- Malformed input falls through, and no FHIR capability is claimed.

## Review findings

1. **ORU scope is broader than stated.** `_extract_hl7_oru` checks only
   `MSH-9.1 == "ORU"`; it does not check `MSH-9.2 == "R01"`. An `ORU^R99`
   would currently be extracted, despite the docs and ledger describing this
   as ORU^R01-only.

2. **The identity proof is controlled, not independent cross-identifier
   resolution.** It proves cross-format convergence for the same bare ID
   string (`P001`). PID-3 assigning-authority / universal-ID components are
   not retained, so the external ID is globally matched across sources. Equal
   MRN strings from different facilities could therefore merge incorrectly.
   This should be stated as a POC limitation before calling it the hardest
   interoperability identity case.

3. **Lab observations are currently modelled as analyte entities.** A
   `LabResult` is reused by `test_code` / name (for example, Hemoglobin), so
   results for different patients, orders, specimens, or times can converge
   into one entity. For clinical correctness, a future model needs distinct
   observation/result instances linked to an analyte concept, patient,
   order/specimen, timestamps, and performer context. OBR is present in the
   message but its identifiers are not yet represented.

4. **Test coverage should substantiate the delimiter claim directly.** The
   parser code supports declared delimiters, but current tests use only the
   conventional delimiter set. Future coverage should include nonstandard
   declared delimiters and rejection of an `ORU` trigger other than `R01`.

## Recommendation

Keep row 11's accomplishment, but describe it precisely as: **HL7v2
ORU-family ingestion plus same-identifier cross-format entity convergence.**
Prioritize identifier namespaces / assigning authority and per-observation
clinical modelling before presenting it as healthcare-grade interoperability.

## Process risk observed

Rule 18 cannot safely be executed: `git remote -v` currently maps `origin` to
`https://github.com/vikasiec/Financial-Planner-2.0.git`, not Project Synapse.
Do not pull or push until Vikas/Claude confirms and corrects the repository
remote. No Git synchronization was performed for this handoff.
