# Road Map — Project Synapse Healthcare Vertical

**Status:** Consolidated 2026-07-19 from `Active_File.md` rows 1-18.
**Ownership model:** per `.agent_os/collaboration_model_V2.0.md` (V2.7) Rule 13 —
Lead AI (Claude) allocates, owning agent delivers end-to-end incl. tests
(Rule 14), Lead AI reviews before `🟢 DONE`.

## Completed (rows 1-17, all 🟢 DONE except 12 and 16)

| # | Item | Owner | Sequential/Parallel |
|---|---|---|---|
| 1, 4-6 | `hospital_management` full domain pack (Patient/Doctor/Appointment/Treatment/Billing) | Claude | Sequential — each row built on the prior file's entities |
| 2, 3 | Problem statement adoption (Grok proposal), platform-vs-domain constraint (Grok) | Grok → Claude | Sequential, gating |
| 7 | `docs/DOMAIN_PACK_CONTRACT.md` | Claude | After pattern proven 5x |
| 8 | Anonymous-dataset probe (deliberate no-build) | Claude | Independent, could run parallel to 4-6 |
| 9 | Sense board healthcare walkthrough + `query.py` fix | Claude | After row 6 (needs full chain data) |
| 10 | Banking second domain (contract generalization test) | Claude | Independent of healthcare rows, ran after row 9 |
| 11, 13 | HL7v2 parser + Codex review + fixes | Claude → Codex → Claude | Sequential (build, then review, then fix) |
| 14 | H1-H16 architecture-fit review | Claude → Codex (reassigned from Gemini) | **Still open** — see below |
| 15 | FHIR parser (lesson from 13 applied proactively) | Claude | Independent, after 13 |
| 16 | Git repo-scope/remote issue | Codex → Claude (escalated to Vikas) | **Blocked on Vikas** |
| 17 | Collaboration-model V2.7 process fixes + Codex confirmation | Claude → Codex | Sequential, gating for future row-append discipline |

## Currently open

| Row | Owner | What's needed |
|---|---|---|
| 12 | Codex | Banking Sense board walkthrough — mirrors row 9's method for the banking pack (row 10). Not yet started as of this document. |
| 14 | Codex | H1-H16 register review — does the domain-pack work still map onto the original production-hole register, or has it drifted / exposed an ungoverned gap? Not yet started. |
| 16 | **Vikas** | Git repository scope decision — does Project Synapse get its own repo, or does the parent `.git` at `Documents/Claude/Projects` get rescoped/removed? Nothing else proceeds on git sync (Rule 18) until this resolves. |

## Sequential vs. parallel guidance for what's open

- **Row 12 and row 14 can run in parallel** — both assigned to Codex, independent
  of each other (one is hands-on-keyboard verification, the other is a reading/
  register-mapping review). No shared file conflict expected.
- **Row 16 blocks nothing currently in flight** — it only blocks future `git pull`/
  `commit`/`push` under Rule 18. Product work (rows 12, 14, and any future pack
  work) can continue without it.

## Natural next candidates after 12/14/16 close (not yet assigned, for discussion)

1. **A real conflict-detection proof for a second interoperability format** — row
   15's FHIR work proved extraction + cross-format identity convergence, but
   (unlike HL7's healthy-vs-front-desk pattern from row 4) never tested FHIR
   against a deliberately conflicting second source. Would close that gap
   symmetrically.
2. **PID-3 / FHIR identifier namespacing** — the stated-but-unfixed limitation
   from rows 13 and 15 (bare identifier, no assigning-authority scope). Real
   fix, not urgent, deferred twice for the same reason (risks the proven
   cross-format convergence without a driving need yet).
3. **A third domain** — would mostly re-confirm what banking (row 10) already
   proved about `docs/DOMAIN_PACK_CONTRACT.md`'s generality; lower marginal
   value than 1 or 2 unless a specific new domain becomes a real requirement.

## Process notes carried forward (V2.7)

- Row-ID assignment requires a fresh read under `lock.txt` — two collisions
  happened before this was enforced (rows 12, 14 each assigned twice).
- Every agent's Execution Mode is now declared in the collaboration model's
  Variables Block — both Claude and Codex are turn-based/per-session, not
  persistent background watchers; expect next-turn pickup, not real-time.
