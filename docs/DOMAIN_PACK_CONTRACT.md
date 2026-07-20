# Domain Pack Contract

**Status:** Written after building the pattern 5 times (LabResult, Patient, Doctor,
Appointment, Treatment, Billing) across two verticals (clinical lab, hospital ops).
This document describes what was actually built, not an aspirational design —
every mechanism named here exists in `synapse/` today with a working example.

**Why this exists:** per `workspace_scratch/GROK_FEEDBACK_platform_vs_domain_2026-07-19.md` —
*"Core = domain-blind. Healthcare = pack + data + eval."* Project Synapse is meant
to become a platform anybody can point at a new domain (banking, logistics, …),
not a hospital app that happens to be written in Python. This document is the
line between the two.

---

## 1. The platform model

```
PLATFORM CORE (domain-blind — never references a specific domain by name)
  land · contracts (RawObject/Episode/Entity/Fact/Conflict/Claim) · dual-path hooks
  graph · conflict resolution · budget/orchestrator · Sense board shell · connectors

DOMAIN PACKS (plug into core via the mechanisms below)
  ontology L1 types · extraction rules · authority/source-boost data
  sample data · eval golden set

Current packs: clinical_lab (LabResult), hospital_ops (Patient, Doctor,
Appointment, Treatment, Billing)
Future packs: banking, logistics, … — same slots, same contract
```

One deep vertical (healthcare) is how the pack interface gets tested honestly.
A shallow multi-domain sketch would not have caught the entity-resolution bug
task 4 found — depth first, breadth later, is the only way this contract earns
trust.

## 2. What a domain pack MUST provide

A pack is the combination of these five things. None of them touch core files
except in the two explicitly sanctioned ways (§3).

1. **Ontology L1 type(s)** — an entry in `synapse/ontology.py`'s `_L1` list:
   `OntologyType(name, layer="L1", domain=<pack domain string>, parent=<an L0
   type>, predicates=(...), description, strict_identity=<bool>)`.
   - `strict_identity=True` for any type whose canonical name is a **human
     name** (patients, doctors, employees, customers) — see §4, this is not
     optional for person-identity types.
   - `predicates` is the closed set of fact predicates this type is expected
     to carry; used for scope-checking and conflict ranking, not enforcement.

2. **Extraction rule(s)** in `synapse/extraction.py`'s `RuleExtractor`:
   - a `SIGNAL_RE` regex that's cheap to test against raw text,
   - a `_looks_like_X(text) -> bool` guard that disambiguates from every
     *other* row shape sharing a key with this type (see §5 — this is where
     every real bug in this codebase's pack additions has come from),
   - an `_extract_X(episode, raw, text) -> Optional[ExtractionResult]` method
     that calls `self.er.get_or_create(type_name, canonical_name, ...,
     domain=pack_domain)` and builds `Fact`s from a `field_map`,
   - one line wiring it into `extract_from_episode`'s dispatch chain.

3. **Authority / source-boost data (optional)** — entries in `session.py`'s
   `DEFAULT_AUTHORITY` dict (per-source trust weight `Ar`) and/or
   `ontology.py`'s `PREDICATE_SOURCE_BOOST` dict (per-predicate SoR
   preference). Both are plain data, not logic — a pack can add rows here
   without any core file understanding what domain they're for.

4. **Sample data** — lands in `.data/<something>/`, used for smoke scripts
   and skip-if-missing tests (`@unittest.skipUnless((path).is_file(), ...)`).

5. **Tests** — mirroring the existing `tests/test_<pack>_extract.py` files:
   ontology registration, the disambiguation guard, a synthetic minimal-row
   test, and (if sample data exists) a real-data extraction/join test.

## 3. What core must NEVER own

- **No `if healthcare:` / `if domain == "hospital_ops":`-style branches** in
  `orchestrator.py`, `store.py`, `api.py`, `query.py`, or any other
  domain-blind module. If a change only makes sense for one domain, it goes
  in the pack's `_extract_X` method or ontology entry — never as a special
  case in shared code.
- **No domain-specific Sense board tabs or fields.** RAW / MEANING /
  CONFLICTS / ASK / EMIT stay generic; a pack changes what data flows
  through those panels, never their shape.
- **No changes to the core contracts** (`RawObject`, `Episode`, `Entity`,
  `Fact`, `Conflict`, `Claim` in `models.py`). Every pack built so far has
  fit inside the existing schema — a pack that needs a new field on `Fact`
  itself is a signal to stop and re-examine the design, not to add it.

The two sanctioned exceptions, both used already and both generic mechanisms
(not domain hacks):
- `OntologyType.strict_identity` (§4) — a flag any pack can set, default off.
- `EntityResolutionService.find_by_external_id_value` — a generic cross-source
  ID-blocking helper any pack's extractor can call.

## 4. `strict_identity` — mandatory for person-identity types

**Found in task 4, not designed up front:** generic name-fallback entity
resolution silently merged 3 different real patients who shared the name
"Michael Taylor" in a 50-row real dataset (~6% collision rate). This is a
patient-safety-class defect for any domain where the entity is a real person.

**Rule:** any pack type whose canonical name is a human name — patients,
doctors, employees, account holders, borrowers, whoever — must set
`strict_identity=True`. This makes `get_or_create` block on the ID value
(`find_by_external_id_value`, cross-source, safe because an ID is
authoritative) instead of falling back to name matching (unsafe, because two
different real people can share a name). It does not block legitimate
cross-source merges of the *same* ID — see `test_same_patient_id_across_sources_does_merge`.

Types where a name genuinely is a safe blocking key (services, generic
support tickets, lab analyte names) leave this `False` — the default.

## 4.1 `identifier_authority` — assigning-authority scoping for `strict_identity` types

**Found in HL7v2/FHIR review (Active_File.md rows 13/14, closed row 23):**
`find_by_external_id_value` blocks by bare ID value alone. That's safe within
one facility/system, but two different real-world sources can independently
issue the *same* bare ID to two *different* real people — e.g. two hospitals
both calling a patient "P001". Left unscoped, a second source's data would
silently widen the first source's entity with an unrelated person's facts.

**Rule:** if a source format carries an assigning-authority concept for an
identifier — HL7v2 PID-3's 4th component, FHIR's `Identifier.system` — pass
it through `get_or_create(..., identifier_authority=...)`. Sources with no
such concept (plain CSV columns) simply omit it; matching stays permissive
by bare ID in that case, preserving existing convergence.

Comparison uses `entity_resolution.normalize_authority`, not raw string
equality — the same real authority is represented differently across
formats (HL7's bare `"HIS"` vs. FHIR's URI-wrapped `"urn:oid:HIS"`), and
naive exact matching would fracture the proven cross-format identity
convergence instead of protecting it. Only genuinely different, both-sides-
known authorities block a match; an unstated authority on either side is
never treated as a conflict.

## 5. Disambiguation is the hard part, not extraction

Every real defect in this codebase's pack work has been a disambiguation
miss, not an extraction miss:
- `_looks_like_patient` requires `patient_id` **and** an identity field, so
  `appointments.csv` (which references `patient_id` as a foreign key with no
  identity fields) doesn't get misread as a broken patient record.
- `_looks_like_treatment` requires `treatment_id` **and** `appointment_id`,
  because `billing.csv` also carries `treatment_id` as a foreign key without
  `appointment_id`.

**Rule for every new pack type:** before writing the guard, list every other
row shape in the same domain (or a plausible future one) that shares at
least one key with this type, and make sure the guard requires a
combination unique to this type — never a single key alone if any other
row shape in the domain might carry it as a foreign key.

## 6. Land-order and partial links are honest, not bugs

Cross-entity resolution (`find_by_external_id_value`) is best-effort at
extract time: if the referenced entity hasn't landed yet, the raw ID string
still lands as a fact, and the resolved `_entity_id` fact is simply absent.
This is intentional — H6 (reprocess is normal) means a later pass can
complete the link; a pack must not treat an unresolved link as an error.

## 7. Checklist for adding a new domain

1. Does the new domain need any type whose name is a real person? Set
   `strict_identity=True` on it. No exceptions without a written reason.
2. For every new type's guard: what other row shapes in this domain share a
   key with it? Does the guard require a combination unique to this type?
3. Did anything get added to `orchestrator.py`/`store.py`/`api.py` that
   mentions this domain by name? If yes, stop — it belongs in the pack.
4. Does the Sense board still work identically for a completely different
   domain's data with zero code change? (It always has so far — this is the
   real acceptance test for "core stays domain-blind.")
5. Sample data + tests committed, smoke script run, full suite green.
