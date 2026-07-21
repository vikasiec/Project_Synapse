# New Data (LIS/Middleware/HL7/FHIR) — Convergence Test Findings

**Date:** 2026-07-21 · **Scope:** read-only testing against `New Data/` (no code changed) · **Author:** Claude, on request after initial smoke test

## The thesis

This dataset was clearly *built* to test the one thing Project Synapse exists to
prove: that the same real-world fact, described four different ways by four
different systems, converges into one entity with preserved lineage instead of
four disconnected records. It is not a random pile of files — it is a
convergence fixture.

**It converges on nothing.** Of the four channels, three (LIS CSV, Middleware
CSV, FHIR) extract zero entities. The fourth (HL7) extracts entities that use
a join key no other channel would ever produce, even if its own extractor
were fixed. Verified below with actual values, not a general impression.

Every other issue in this document is a symptom of the same root cause: the
extraction layer was pattern-matched to the *shape of the sample files this
proof was originally built with* (hospital CSV, banking CSV, one HL7 message
type, one FHIR bundle shape), not designed from the standards those formats
are supposed to implement. New data in the same domain, shaped slightly
differently, falls straight through.

---

## 1. The smoking gun: no shared identity key, even where extraction works

The dataset carries the same lab result — patient PAT-88301's TSH — through
three of the four channels. Here is what each one actually keys it on.

| Source | Raw representation | What the extractor reads | Entity identity it would produce |
|---|---|---|---|
| **HL7v2 OBX-3** | `TSH^TSH_LOINC^LN` (code `^` display `^` **coding system**) | `obx.value(3,1)` = `"TSH"` (code), `obx.value(3,2)` = `"TSH_LOINC"` (display). **Component 3 (`LN` = LOINC) is never read.** | canonical_name=`"TSH_LOINC"`, external_id=`pat-88301:tsh:<order>` |
| **FHIR `code.coding[0]`** | `{"system":"http://loinc.org","code":"LOINC-TSH","display":"TSH"}` | `coding_display_and_code()` → display=`"TSH"`, code=`"LOINC-TSH"` | canonical_name=`"TSH"`, external_id=`pat-88301:loinc-tsh` *(bundle actually doesn't extract — see §2 — this is what it would be)* |
| **LIS CSV** | `TestCode=THYROID, TestDescription="Thyroid Function Panel"` | n/a — no rule matches this column set (§2) | n/a |

Even in the one hypothetical where every extractor worked, **HL7 produces
`TSH_LOINC` / `pat-88301:tsh:...` and FHIR produces `TSH` /
`pat-88301:loinc-tsh`** — different canonical names, different identity keys,
for the identical analyte on the identical patient. Entity resolution has no
mechanism that would ever collapse these into one LabResult. The `system`
field FHIR provides (`http://loinc.org`) and the coding-system component HL7
provides (`LN`) — the two places each standard tells you explicitly "this
code means LOINC, normalize against it" — are both present in the data and
both discarded by the parser.

This is the anticipatory-design gap in one sentence: **real interoperability
converges on `code_system | normalized_code` (LOINC, in this domain); this
extractor converges on whatever string happened to be in the demo file's
column.**

Fix shape (not proposing to implement without sign-off): a shared
`normalize_code(system, code)` used by both the HL7 and FHIR extractors —
even a trivial one that strips known system prefixes and uppercases — would
have made this pair converge today, with this exact data.

---

## 2. Per-channel: built to the sample, not the standard

### FHIR — requires an embedded `Patient` resource that real bundles don't send

`_extract_fhir_bundle` (`synapse/extraction.py:993-1001`) does:

```python
patient_res = next((r for r in resources if r.get("resourceType") == "Patient"), None)
if patient_res is None:
    return None
```

Real-world Observation bundles overwhelmingly reference the patient by
`subject.reference` (`"Patient/PAT-88301"`) without embedding the full
resource — that's the point of FHIR references, and it's exactly what this
690-observation bundle does (100% of entries, 0 embedded Patient resources).
The extractor's own docstring calls this scope "Bundle-of-inline-resources
only," which is a reasonable phase-1 boundary for a hand-built demo bundle,
but it means the extractor cannot process the single most common real FHIR
shape: an Observation-only export with external patient references. Given
schema-on-read is the platform's stated design principle, the natural
extension is a lightweight stub entity keyed off the bare reference
(`Patient/PAT-88301` → external_id `PAT-88301`, unresolved/thin) rather than
requiring the full resource — you don't need the patient's name to know an
observation belongs to them.

**Verified impact:** 690/690 observations, 100 patients, 0 entities, 0 facts.

### HL7v2 — hard-gated to one message type

`_extract_hl7_oru` (`synapse/extraction.py:845`):

```python
if msh is None or msh.value(9, 1) != "ORU" or msh.value(9, 2) != "R01":
    return None
```

This test file happens to be 149/149 `ORU^R01`, so it didn't lose data here —
but a real lab interface feed carries `ADT` (admit/discharge/transfer), `ORM`
(orders), `SIU` (scheduling) alongside `ORU`, often on the same channel. The
parser has no fallback path for "land it, note the message type, extract what
a generic PID/segment walk can get" — it's all-or-nothing per message type,
and only one type is wired up. This is scoping debt that this particular file
didn't happen to expose, but the next HL7 feed will.

### LIS + Middleware CSVs — column-name allowlist, not domain semantics

Every `_looks_like_*` gate in `extraction.py` (e.g. `_looks_like_patient`,
`_looks_like_lab`) checks for an **exact, hardcoded key set**:

```python
has_id = "patient_id" in keys
has_identity = bool(keys & {"first_name", "last_name", "insurance_provider", "date_of_birth"})
```

This dataset's LIS extract uses `PatientID`, `FullName`, `GenderCode`, `DOB`
— every one of those is a standard, reasonable column name for the exact
same concept, and none of them is in any allowlist. This isn't a parsing
bug, it's an absence of the layer that should exist between "raw column
header" and "domain concept": a synonym/ontology mapping (`patient_id` ~
`PatientID` ~ `MRN` ~ `mrn_number`), which is exactly the kind of
normalization a schema-on-read platform claims to defer to query time rather
than require up front. Right now it's implicitly required up front, just
silently — the file lands, nothing errors, and the row simply produces no
entity.

**Verified impact:** 1,494 CSV rows landed as raw text across 6 files, 0
entities extracted from any of them.

---

## 3. The residual-LLM path: the shortcut made visible

This is where the three gaps above stop being "quietly missing data" and
start actively fabricating it.

`DualPathExtractor._residual_text()` (`synapse/dual_path.py:211-226`) strips
lines matching a `key: value` regex and calls whatever's left "residual
free text" for the Gemini fallback (Path B). HL7's pipe-segment grammar
(`MSH|^~\&|...`, `PID|1||PAT-88301...`) never matches that regex — so for
every HL7 message, **the entire already-structured, already-correctly-parsed
message text gets re-submitted to Gemini as if it were unstructured prose.**

Quantified from this run's data (`.data/sense.db`, via `/v1/facts`):

- **5,818 facts** from the deterministic rules path (`path:"rules"`)
- **516 facts** from the residual LLM path (`path:"residual"`)
- **99 distinct entities** carry at least one residual fact — i.e. **≈99–149
  live Gemini API calls** were made ingesting this dataset once, one per HL7
  message, for text the platform had already fully parsed a moment earlier
- Top invented predicates: `risk_flag` (186), `instrument_id` (59),
  `ordering_physician` (51), `incident_theme` (50), `human_action` (39)

Two compounding problems in that predicate list:

1. **The predicate vocabulary is borrowed from the wrong domain.**
   `synapse/llm_gemini.py:310` primes the model with example predicates —
   `risk_flag, human_action, incident_theme` — written for the original
   SRE/incident-checkout demo. The model dutifully applies SRE-shaped
   predicate names to clinical lab messages, because that's the vocabulary
   it was shown.
2. **The same real fact gets filed under different predicates across calls,
   because nothing constrains the model to a fixed vocabulary.**
   `ordering_physician` appears 51 times, `ordering_provider` — same concept
   — 7 times. Notably, **the rules-based HL7 extractor doesn't extract
   ordering-physician at all**, even though it's sitting right there in the
   OBR segment — so this field exists in the store *only* via the
   non-deterministic path, split across two spellings. Querying
   "ordering_physician" for all patients would silently miss 7 of them.
3. **Provenance is presented as equal-weight.** `/v1/ask` claims stitch
   rules-path and residual-path facts into one statement, both cited as
   `source=HL7-Interface`, with the UI/claim text giving no signal that
   `risk_flag: leukopenia` was an LLM inference from raw segment text and
   `date_of_birth: 19740904` was a direct field read. In a clinical domain
   that distinction is not cosmetic.

None of this is "the LLM is bad." It's doing exactly what a fallback path
should do — interpret unstructured text. The gap is upstream: nothing is
actually unstructured here, and nothing told it to stop.

---

## 4. Why this is the same failure everywhere, restated once

| Layer | What it does | What it should anchor on |
|---|---|---|
| HL7 lab code | reads local code+display, drops coding-system component | `system\|code` (LOINC) |
| FHIR lab code | reads local code+display from `coding[0]`, ignores `system` | `system\|code` (LOINC) |
| FHIR patient link | requires embedded resource | reference/stub, resolve when available |
| HL7 message type | allowlist of one (`ORU^R01`) | segment-grammar dispatch table |
| CSV columns | allowlist of exact header sets, per known file | synonym/ontology-mapped headers |
| Residual text detection | regex for `key: value` lines only | format-aware (know HL7/FHIR/CSV already consumed the line) |

Every row is the same pattern: a rule was written to match the training
fixture's literal shape instead of the standard's underlying grammar. That's
the "built around the data instead of anticipating the domain" critique,
concretely, six times over — not a one-off bug.

---

## 5. Supporting findings (secondary, not the thesis)

- `/v1/entities?type=Patient` — the `type` query param is parsed nowhere in
  the handler (`synapse/api.py:469`); always returns all 790 entities.
- ER merge-suggestions (`/v1/er/suggestions`) blocks purely on
  `canonical_name`, producing **12,302 suggestions** for this dataset —
  almost entirely correct-as-separate same-test-name LabResults across
  different patients. Unusable at this volume without patient-scoped
  blocking.
- `/v1/sense/drop` (kind=json) defaults new data to `domain:sre,
  clearance:l2` ACL tags — wrong domain for clinical data — while the
  purpose-built `Hl7DirectoryConnector`/`FhirDirectoryConnector` correctly
  default to `domain:clinical, clearance:l2`. The generic drop path inherited
  the original demo's default instead of being domain-aware.
- `synapse/drift.py:71` checks every source, including this patient-master
  CSV, against a `has_revenue` signal (`annual_revenue|arr` regex) left over
  from the billing/CRM demo — meaningless noise on clinical schemas.
- `python -m synapse eval` hangs retrying a local Neo4j connection
  (`localhost:7687`) with no offline fallback exercised, despite the
  README's claim that local implementations keep the proof runnable without
  external engines.

---

## 6. What I'd recommend, in priority order (not implemented — awaiting sign-off)

1. **Code-system-normalized identity** for lab analytes (`system|code`,
   LOINC in this domain) shared by both HL7 and FHIR extractors — this alone
   makes the dataset's actual convergence story work.
2. **FHIR: stub-entity patient linking** from `subject.reference` when no
   embedded `Patient` resource exists — unblocks the 690-observation bundle
   entirely.
3. **Constrain the residual path**: only run it on text no format-specific
   parser claimed at all (not "leftover after key:value stripping" — leftover
   after *whichever* parser matched), and constrain its predicate output to
   the existing ontology vocabulary instead of free-form generation.
4. **CSV column synonym mapping** for the known L1 ontology fields
   (`patient_id` ⇄ `PatientID`/`MRN`, etc.) instead of exact-match allowlists.
5. Secondary cleanups: `entities?type=` filter, `/v1/sense/drop` ACL default,
   drift signal domain-scoping, ER suggestion blocking key.

Items 1–2 are the ones that make *this specific dataset's intended proof*
actually run. Say the word and I'll scope an implementation plan.
