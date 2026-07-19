# Road Map — Project Synapse Healthcare Vertical

**Status:** Updated 2026-07-19 (evening) from `Active_File.md` rows 1-20, all closed.
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

1. **Audit remaining core modules for the hardcoded-whitelist pattern** (see above)
   — proactive, cheap, directly motivated by 3 real bugs found this session.
2. **A real conflict-detection proof for FHIR** — row 15 proved extraction +
   cross-format identity convergence, but never tested FHIR against a deliberately
   conflicting second source the way row 4 did for the HL7/CSV pair.
3. **PID-3 / FHIR identifier namespacing** — the stated-but-unfixed limitation from
   rows 13/14/15 (bare identifier, no assigning-authority scope). Independently
   reaffirmed by Codex's row-14 review as the main remaining architectural gap.
   Real fix, not urgent, deferred repeatedly for the same reason (risks the proven
   cross-format convergence without a driving need yet).
4. **Observation-vs-analyte instance modeling** (Codex, row 14) — distinct
   observation instances per order/specimen/time, not just per patient+test.
5. **A third domain** — would mostly re-confirm what banking (row 10) already
   proved; lower marginal value than 1-4 unless a specific new domain becomes a
   real requirement.

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
