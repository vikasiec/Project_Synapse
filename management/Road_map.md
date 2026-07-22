# Road Map — Project Synapse Healthcare Vertical

**Status:** Sections below (rows 1-20) are historical, last touched 2026-07-19 —
**stale beyond that point.** `Active_File.md` rows 21-47 happened since and are
not reflected in the tables below; read the ledger's own tail for current state,
not this file's "Currently open" section (still says "Nothing" — wrong as of
2026-07-22). See the "2026-07-22 update" section near the bottom for the newest
work stream (rows 38-47, Semantic Discovery & Curation).
**Ownership model:** per `.agent_os/collaboration_model_V2.0.md` (V2.8) Rule 13 —
Lead AI (Claude) allocates, owning agent delivers end-to-end incl. tests
(Rule 14), Lead AI reviews before `🟢 DONE`.

## Completed (rows 1-20, all 🟢 DONE)

| # | Item | Owner | Sequential/Parallel |
|---|---|---|---|
| 1, 4-6 | `hospital_management` full domain pack (Patient/Doctor/Appointment/Treatment/Billing) | Claude | Sequential — each row built on the prior file's entities |
| 2, 3 | Problem statement adoption (Grok proposal), platform-vs-domain constraint (Grok) | Grok → Claude | Sequential, gating |
| 7 | `docs/DOMAIN_PACK_CONTRACT.md` | Claude | After pattern proven 5x |
| 8 | Anonymous-dataset probe (deliberate no-build) | Claude | Independent, could run parallel to 4-6 |
| 9 | Sense board healthcare walkthrough + `query.py` fix | Claude | After row 6 (needs full chain data) |
| 10 | Banking second domain (contract generalization test) | Claude | Independent of healthcare rows |
| 11, 13 | HL7v2 parser + Codex review + fixes | Claude → Codex → Claude | Sequential (build, then review, then fix) |
| 12 | Banking Sense board walkthrough (Codex) + `api.py` principal fix (Claude) | Claude → Codex → Claude | Found a real 403 bug, fixed generically |
| 14 | H1-H16 architecture-fit review (Codex) + `temporal.py` fix (Claude) | Claude → Codex → Claude | Codex's strongest review this session — found the deepest bug (temporal supersession) |
| 15 | FHIR parser (lesson from 13 applied proactively) | Claude | Independent, after 13 |
| 16 | Git repo-scope/remote issue → own repository created | Codex → Claude → Vikas → Claude | Escalated, decided, executed |
| 17 | Collaboration-model V2.7 process fixes + Codex confirmation | Claude → Codex | Sequential, gating for row-append discipline |
| 18 | `management/master_plan.md`/`Features.md`/`Road_map.md` written | Claude | Autonomous pickup, self-paced loop |
| 19 | V2.8 (15-min self-loop rule) notification to Codex | Claude → Codex | Closed — Codex confirmed no standing scheduler, purely turn-based, consistent with its existing Execution Mode declaration |
| 20 | Duplicate independent confirmation of row 12's banking-ASK 403 bug | Codex → Claude | Closed as duplicate-confirmed, no separate fix needed |

## Currently open

Nothing. All 20 rows are `🟢 DONE` as of this update.

## The pattern that emerged this round (rows 9, 12, 14)

Three separate bugs, found independently in three different core modules
(`query.py`, `api.py`, `temporal.py`), turned out to be the **same root cause**: a
hardcoded "known domains/predicates" list quietly baked into code that's supposed to
be domain-blind. Each was found by testing a new domain against existing code, not
by design review. Worth an explicit audit pass over remaining core modules
(`orchestrator.py`, `store.py`, `control_plane.py`, `budget.py`, `resolution.py`)
for the same pattern before a fourth instance is found by accident rather than by
design.

## Natural next candidates (not yet assigned, for discussion)

1. ~~Audit remaining core modules for the hardcoded-whitelist pattern~~ — **done,
   row 22 (2026-07-20).** Checked `orchestrator.py`, `store.py`, `control_plane.py`,
   `budget.py`, `resolution.py`. Clean result: no fourth instance of the pattern.
   Every superficial hit was a legitimate closed vocabulary the module itself
   owns (query-intent categories, `BudgetClass` enum, injected authority map),
   not a domain/predicate leak.
2. ~~A real conflict-detection proof for FHIR~~ — **done, row 24 (2026-07-20,
   Codex, reviewed by Claude).** `bundle004`/`bundle005` fixtures, same patient/
   authority/`Observation.id`/time, genuinely different values. Proven via
   `scripts/smoke_fhir_conflict.py` and the live Sense API. No bug found.
3. ~~PID-3 / FHIR identifier namespacing~~ — **done, row 23 (2026-07-20).**
   `identifier_authority` threaded from HL7 PID-3.4 / FHIR `Identifier.system`
   through `EntityResolutionService`, compared via `normalize_authority()` so
   equivalent cross-format representations ("HIS" vs "urn:oid:HIS") still
   converge while genuinely different authorities no longer silently merge.
   Two real near-misses caught before shipping (naive string equality would
   have broken cross-format convergence; the exact-match shortcut in
   `get_or_create` initially bypassed the new check entirely) — see row 23's
   resolution note for both. `tests/test_identifier_authority.py` (new, 7
   tests) + 2 format-level regression tests. Full suite 167/167.
4. ~~Observation-vs-analyte instance modeling~~ — **done, row 25 (2026-07-20,
   Codex, reviewed by Claude).** `LabResult` identity now incorporates the
   source's own instance ID (FHIR `Observation.id`/`basedOn`, HL7 OBR-2/3) when
   present. **Corrects a real over-eager part of row 14's original fix**, not just
   an addition — row 14's own regression test had asserted two separate lab
   orders a month apart should supersede into one entity, but on inspection that
   fixture represents two genuinely distinct real-world results, not one
   "correcting" the other. Row 25 fixes that. Lead review added one missing
   regression test (`test_same_hl7_order_id_amended_result_still_supersedes`)
   to confirm the *other* half — a truly amended result for the *same* order
   still supersedes correctly. Full suite 169/169.
5. ~~H6 reprocess idempotency for HL7v2/FHIR/banking~~ — **done, rows 28-29
   (2026-07-20).** Reprocess had only ever been tested against the original
   checkout scenario; this session changed LabResult/Patient identity twice
   (rows 23, 25). Verified empirically for HL7, FHIR (row 28, Claude), and
   banking (row 29, Codex, Lead spot-checked): entity counts and current-fact
   counts unchanged after reprocess, no false conflicts. Negative result, real
   risk closed. Full suite 172/172.
6. **A third domain** — would mostly re-confirm what banking (row 10) already
   proved; lower marginal value unless a specific new domain becomes a real
   requirement.

## Grok-architecture review (Codex, `review_comments.md`, 2026-07-20)

Codex reviewed the implementation against `docs/Project_Synapse_Unified_
Master_Architecture_By_Grok.pdf` and filed 10 findings (RC-01 through
RC-10). Claude verified the 6 most severe ones directly against the code
before opening any tracker rows — all checked out exactly as described.

- **Rows 30, 32-34 — done (2026-07-20).** RC-01 (P0, no ABAC gate on any
  API route), RC-02 (P1, content-hash dedup dropped cross-source
  provenance), RC-04 (P1, claim cache never invalidated on ordinary
  ingest), RC-05 (P1, reprocess overwrote episode pipeline version in
  place). Full suite 181/181.
- **Row 31 — done (2026-07-20).** RC-03 (P1): Graphiti push/search carried
  no ACL/tenant metadata. Used Graphiti's real `group_id`/`group_ids`
  multi-tenancy primitive (confirmed against the installed `graphiti_core`
  signatures), applied both query-side and result-side. Full suite 189/189.
- **Row 36 — done (2026-07-20).** RC-08 (P2): `materialize`/`export` were
  ACL-blind. Split out of row 35 once row 30 landed and unblocked it.
  `role:admin`/`role:operator` grant capability to call the route, not a
  bypass of ACL visibility — proven by test. Full suite 183/183.
- **Row 35 — open, backlog, not urgent.** RC-06/07/09/10 (P2/P3): contract
  validation not enforced at runtime, no WORM/durability root (review
  itself calls this an accepted POC boundary), engine execution-vs-
  detection telemetry split, golden eval quality gates. Logged, not
  assigned for immediate execution.

## Process notes carried forward (V2.8)

- Row-ID assignment requires a fresh read under `lock.txt` — two collisions
  happened before this was enforced (rows 12, 14 each assigned twice, both since
  resolved by renumbering).
- Every agent's Execution Mode is declared in the collaboration model's Variables
  Block. Claude and Codex are both turn-based/per-session, not persistent
  background watchers.
- V2.8 (Rule 12) sets a ~15-minute self-loop as the ideal cadence for both Lead AI
  and contributors during active work, using whatever self-scheduling mechanism
  each agent actually has (Claude: `/loop`). Row 19 is Codex's open confirmation
  of whether it has an equivalent.

## Repository

`https://github.com/vikasiec/Project_Synapse.git`, branch `main`, initial commit
`2b1e9aa` (row 16). Own dedicated repo, decoupled from the parent folder's
`Financial-Planner-2.0` remote/scope issue that started that row.

## 2026-07-22 update — new work stream: Semantic Discovery & Curation (rows 38-47)

Vikas supplied a new spec (`docs/Master Architectural Specification &
Implementation Roadmap.md`, uncommitted) describing "SYNAPSE" as an
embedding/vector-based schema-field discovery and curation engine, in 7
Major Goals across two phases. Investigation confirmed this spec's concepts
(field profiling, hybrid candidate scoring, a curation canvas, an ontology
relationship registry) did not exist anywhere in the prior codebase — the
existing entity-resolution/conflict/FHIR-HL7v2 core (everything above this
section) operates one layer lower, matching *records*, not *schema fields*.

**Vision framing, agreed with Vikas before implementation:** this is an
additive front-door layer that feeds the existing `ER.suggest_merges()`
core (the new spec's own Major Goal 4 names that exact method), not a
replacement for anything above. Confirmed field relationships (e.g.
`cust_id` ↔ `client_num`) become ER blocking metadata; nothing here
retroactively re-merges existing entities.

**Phase 1 (Major Goals 1-4), all done this session:**
- Row 38: `synapse/profiling.py` — schema field profiling (`data_type`,
  `entropy_score`, `regex_pattern_match`, `min_hash_sketch`) + a stdlib-only
  hashing-trick semantic vector standing in for the spec's "cross-encoder"
  (no embedding library is installed in this project).
- Row 39: `synapse/matching.py` + `POST /v1/explore/analyze` — the exact
  spec formula (`0.45·VectorSim + 0.40·ValueOverlap + 0.15·GraphProximity`)
  and thresholds.
- Rows 40-41: `synapse/ontology.py`'s new `RelationshipEdge` registry +
  `POST /v1/ontology/relationships` (ACCEPT/REJECT/RELABEL), wired into ER
  blocking metadata (`entity_resolution.py::link_schema_fields`).
- Row 42: `transitive_candidates()` — a newly-ingested source gets
  auto-proposed candidates against sources already linked in the registry.
- Row 43-45: full UI rebuild, `ui/` (Vite + React + reactflow), served at
  `/app` alongside the legacy Sense board at `/` (not yet retired — new UI
  covers Catalog + Explore only, not RAW/MEANING/CONFLICTS/ASK/EMIT).
  Verified live in a real Chrome session, not just unit-tested: full
  Explore journey (pick sources → analyze → full-canvas node-link graph →
  click edge → explanation drawer with real `match_reasons` → Accept →
  shows up in Catalog immediately).
- Row 46: all 4 of the spec's own VnV Layer scenarios implemented and
  passing as named tests.
- Full backend suite: 232/232 (was 220/220 before row 38).

**Explicitly NOT started:** Phase 2 (Major Goals 5-7 — CDM/translation
bridge, cross-system conflict routing beyond what already exists, FHIR/
BIAN/OpenAPI federated exports). The spec's own execution gate requires
Vikas's explicit sign-off on Phase 1 before this begins.
