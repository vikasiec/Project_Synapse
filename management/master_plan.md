# Master Plan — Project Synapse Healthcare Vertical

**Status:** Living document, consolidated 2026-07-19 from `Active_File.md` rows 1-17.
**Owner:** Claude (Lead AI), per `.agent_os/collaboration_model_V2.0.md` (V2.7).

## 1. Problem statement (as adopted, row 2)

Enterprise domains generate messy multi-source data that traditional schema-on-write
ETL handles badly (brittle, delayed, context-destroying). Project Synapse is a
semantic data plane: land data as-is with lineage, extract meaning via dual-path
rules + selective AI, keep multi-source conflicts first-class, answer under budget
with citations, and let humans see raw → meaning → conflicts → answers (Sense board).
We do not replace systems of record; we sit above them. We do not promise zero
handiwork forever — we minimize hand-mapping via domain packs that grow with reprocess.

## 2. The core constraint that shaped every decision (row 3)

Grok's platform-vs-domain review, early in this arc: **core stays domain-blind;
healthcare is a pack.** Every ontology type, extraction rule, and connector added
this session lives in `synapse/ontology.py` / `synapse/extraction.py` /
`synapse/connectors/*` as pack data — never as an `if healthcare:` branch in
`orchestrator.py`, `store.py`, `api.py`, or `query.py`. This was verified by grep
after every single task, not assumed. `docs/DOMAIN_PACK_CONTRACT.md` (row 7) codifies
the resulting contract.

## 3. What was tackled, in order, and why

| Order | Dataset / format | Row(s) | Why this order |
|---|---|---|---|
| 1 | `hospital_management/` CSVs (patients, doctors, appointments, treatments, billing) | 1, 4-6 | Already-staged real Kaggle data; relational shape (5 files, foreign keys) tests entity resolution and cross-entity joins without needing new invention first. |
| 2 | Synthetic front-desk conflict data | 4 | The real CSVs had no natural cross-source disagreement (single source of truth) — had to synthesize a second view to actually prove the conflict-detection thesis. |
| 3 | `pathology_health_markers/`, `synthetic_medical_symptoms/` | 8 | Deliberately **not** pursued — anonymous observational data with no identity column, no entity to resolve. Building extraction here would be "extraction theater," not real proof. Documented as a reasoned "no," not a skipped task. |
| 4 | Sense board healthcare walkthrough | 9 | Closed the original visual-sense ask with real data, not just the checkout demo. Found and fixed a real core bug (`query.py` narration whitelist) in the process. |
| 5 | `synthetic_banking/` (second domain) | 10 | Tests whether the domain-pack **contract** generalizes, not just whether Claude can repeat the healthcare pattern. Worked cleanly on the first attempt. |
| 6 | HL7v2 (`synapse/hl7v2.py`) | 11, 13 | The actual invention gap — instruments/LIS/HIS speak HL7v2, not CSVs. Codex's review (row 13) found and helped fix a real clinical-correctness bug (cross-patient result conflation). |
| 7 | FHIR (`synapse/fhir.py`) | 15 | Second real interoperability format. Applied row 13's lesson **proactively** — patient-scoped `LabResult` identity from the first version, no repro cycle needed. |
| 8 | Collaboration-model process fixes | 16-17 | Two real ID collisions and a missed-task incident forced fixing the governance process itself (V2.6-V2.7), not just the product. |

## 4. Where real invention happened vs. where the pattern repeated

- **Repeated pattern** (fast, low-risk): `Patient`, `Doctor`, `Appointment`,
  `Treatment`, `Billing` (hospital_ops), `AccountHolder`, `Account`, `Transaction`
  (banking) — all built from the same 5-step contract (ontology entry, extraction
  rule, disambiguation guard, tests, smoke script).
- **Real invention**: `synapse/hl7v2.py` and `synapse/fhir.py` — no prior parser
  existed for either format; both required understanding real interoperability
  standards, not just CSV column mapping.

## 5. Real bugs found and fixed (not hidden, not glossed over)

1. **Row 4** — generic name-fallback entity resolution silently merged 3 different
   real patients sharing the name "Michael Taylor" in real data. Patient-safety-class
   defect, pre-existing, exposed by testing depth. Fix: generic `strict_identity`
   mechanism on `OntologyType` — opt-in per type, default off.
2. **Row 9** — `query.py`'s answer-narration logic had a hardcoded infra/revenue/
   identity predicate whitelist baked into otherwise domain-blind core; any other
   domain's facts fell through to a false "no facts visible." Fix: generic fallback
   narrating any visible facts, not a domain-specific patch.
3. **Row 13 (Codex)** — HL7 `LabResult` identity keyed by bare test code let two
   different patients' results merge into one entity, fabricating a false conflict
   between unrelated people. Fix: patient-scoped identity key, same `strict_identity`
   mechanism as bug 1.
4. **Row 12 (Codex)** — `api.py`'s `_principal_from_body` hardcoded
   `domain:sre/revenue/identity` for the demo `l1`/`l2` presets; the banking pack's
   ASK path returned 403 through the actual UI request shape because `domain:banking`
   was never in that list. Same class of bug as #2. Fix: `SemanticStore.known_acl_domains()`
   derives the preset from whatever ACL domain tags are actually landed, not a
   hardcoded list.
5. **Row 14 (Codex H1-H16 review, verified by Claude)** — `temporal.py`'s
   `OPERATIONAL_PREDICATES` was a **third** instance of the same pattern: a hardcoded
   infra/revenue predicate whitelist meant temporal supersession silently never
   applied to `"result"` or any other healthcare/banking predicate, so the same
   patient's repeated lab result over time looked like a false open conflict. Fix:
   removed the whitelist — supersession now applies to every predicate, safety comes
   from the existing `(predicate, source_system)` grouping, not from a predicate
   allowlist. Also fixed HL7/FHIR extraction to supersede every `LabResult` entity
   created, not just the patient.

Each fix is a generic core/ontology mechanism, never a domain-specific hack —
directly satisfying the row-3 constraint. Bugs 2, 4, and 5 are the same underlying
pattern (a hardcoded "known domains/predicates" list quietly baked into code that's
supposed to be domain-blind) found three separate times in three different core
modules (`query.py`, `api.py`, `temporal.py`) — worth treating as a systemic class
of risk, not three unrelated bugs, when auditing any other core module later.
**Audited (row 22, 2026-07-20)**: checked the remaining core modules
(`orchestrator.py`, `store.py`, `control_plane.py`, `budget.py`, `resolution.py`) —
no fourth instance found.

6. **Row 23 (2026-07-20)** — the PID-3/FHIR assigning-authority namespacing gap
   (previously deferred, see prior version of §6 below) was fixed: added
   `identifier_authority` to `get_or_create`/`find_by_external_id_value`, normalized
   via `normalize_authority()` so equivalent cross-format representations still
   converge. Two near-misses caught before shipping, not after: naive string
   equality between HL7's `"HIS"` and FHIR's `"urn:oid:HIS"` would have broken the
   proven cross-format convergence (caught by inspecting the actual fixture data
   before writing the comparison logic); and the pre-existing exact
   `(source_system, external_id)` shortcut in `get_or_create` bypassed the new
   authority check entirely, caught by a failing regression test, not by design
   review. Full suite 167/167 (was 158/158).

7. **Rows 24-25 (2026-07-20, Codex, reviewed by Claude)** — FHIR same-time
   conflict proof (row 24, mirrors row 4's method, no bug found) and
   observation-instance identity scoping for `LabResult` (row 25). Row 25 is
   worth stating plainly rather than glossing over: it **corrects** part of row
   14's fix, not just extends it. Row 14's own regression test asserted that two
   Hemoglobin results a month apart (different lab orders, `OBR|1|ORD1` vs
   `OBR|1|ORD2`) should supersede into one entity with one "current" value —
   but that's clinically wrong; two separate draws are two separate real facts,
   and superseding one hid real data. Row 25 fixes this by scoping `LabResult`
   identity to the source's own order/observation instance ID when one exists.
   Codex updated the affected test openly rather than hiding the behavior
   change, which is the right instinct, but repurposing the only test covering
   that path left a real gap: nothing still proved a genuinely *amended* result
   for the *same* order still supersedes (the actual case row 14 was for).
   Lead review added `test_same_hl7_order_id_amended_result_still_supersedes` to
   close it. Full suite: 169/169 (was 167/167).

## 6. What's deliberately not done, and why (stated, not hidden)

- **Observation-vs-analyte instance modeling** (row 14) — `LabResult` identity is
  patient+test scoped (fixed, row 13) and now correctly supersedes over time (fixed,
  row 14), but doesn't yet model a distinct observation instance per order/specimen.
  Flagged by Codex as an H8 semantic-model granularity gap; not built this arc.
- **Anonymous observational datasets** (row 8) — no entity to resolve, deliberately
  not built.
- **Real-time/continuous ingestion, real $ FinOps, multi-tenant ACLs, GraphRAG/
  Data-Juicer package swaps** — held per the original Grok visual-sense plan
  (`docs/Grok_Plan19Jul.txt`), not revisited this arc.

## 7. Repository

Project Synapse now has its own dedicated repository, decoupled from the parent
folder's unrelated `.git`/`Financial-Planner-2.0` remote (row 16):
`https://github.com/vikasiec/Project_Synapse.git`, `main` branch, initial commit
`2b1e9aa`.

## 9. Open decisions

None currently blocking. Row 16 (git repo scope) was resolved 2026-07-19 — see §7.
The parent folder's `Financial-Planner-2.0` repo/remote issue itself was left
untouched throughout, as instructed; Project Synapse's own history starts clean
from its own root.
