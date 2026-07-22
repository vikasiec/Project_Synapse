# Grok alignment watch — Explore View (row 37)

**Started:** 2026-07-21 (session watch)  
**Plan source:** `workspace_scratch/CLAUDE_EXPLORE_VIEW_RESEARCH_AND_PLAN_2026-07-21.md`  
**Scope of this file:** Observer notes only. No code changes by Grok. Discrepancies vs plan / process / correctness risks.

**Watch status:** COMPLETE (Claude closed row 37 🟢 DONE; commit `1020dd7`)

---

## Plan checklist (B.5 phasing) — final

| # | Plan step | Final status | Notes |
|---|-----------|--------------|-------|
| 1 | Confirm DriftDetector `observe_all` wiring | **Diverged (justified)** | Final code does **not** use baselines; fields from ACL-visible raw + `_KEY_RE` (D17) |
| 2 | `GET /v1/explore` + aggregation | **Done** | `_explore_summary` + route in `synapse/api.py` |
| 3 | Tests (empty / multi-source / ACL) | **Done** | `tests/test_explore_api.py` (+ ACL shared-source-name + non-combinatorial dup groups) |
| 4 | Frontend Explore panel + drill-down reuse | **Done** | EXPLORE tab, cards, shared badges, issues, chip → Ask prefill |
| 5 | E2E against live New Data store | **Done (Claude claims; Grok observed full multi-source then restart partial)** | Commit message: full suite 220/220 + multi-source E2E |

---

## Alignment (what matches the plan)

- Payload shape matches B.2 JSON sketch: `entity_types`, `sources`, `shared_fields_across_sources`, `predicate_vocabulary`, `open_issues.{conflict_count,er_suggestion_count}`.
- No LLM in path; pure aggregation (A.4 / A.7).
- Entity samples capped (`_EXPLORE_SAMPLE_LIMIT = 8`, within plan’s 5–10).
- ACL via existing `_principal_from_query` + `filter_entities` / `filter_facts` / `filter_raw_objects` / `filter_conflicts`.
- Shared fields = set intersection over visible sources’ drift key sets (`len(srcs) > 1`).
- Docstring and module header document the route.
- Tests cover: empty well-formed payload; type counts/samples; shared-field positive + non-shared negative; banking principal sees empty clinical; HTTP 200 shape; sense/drop reflection.

---

## Discrepancies & risks (ordered by severity)

### D1 — Frontend (plan B.2.3 / B.5.4) not present
**Plan:** Explore panel: type cards, sample chips → prefill Ask + existing history/ask, Sources panel with shared badges, Issues → conflicts/ER.  
**Observed:** `index.html` has no Explore UI. Row 37 Active_File scope lists `synapse/static/index.html` but UI work has not landed.  
**Severity:** Expected mid-flight if Claude is backend-first; **blocker for “done”** relative to plan B.4 scenario (user opens Explore with zero typing).

### D2 — `er_suggestion_count` not ACL-scoped
**Plan (B.2.1):** endpoint “ACL-filtered via … filter_entities/filter_facts” so a domain-limited principal doesn’t learn out-of-scope structure.  
**Observed:** `open_issues.er_suggestion_count = len(session.er.suggest_merges())` with **no** principal filter. Pre-existing `/v1/er/suggestions` is similarly unscoped — Explore **reuses** that blindness rather than fixing it.  
**Risk:** Cross-domain information scent (count of merge suggestions may leak that other-domain entities exist).  
**Severity:** Medium (policy consistency with rest of Explore response).

### D3 — Drift baselines built from full store, not ACL-visible raw only
**Plan:** “don’t assume baselines are fresh”; call `observe_all()` like `/v1/drift`.  
**Observed:** `observe_all()` runs over the whole store; field lists for a visible `source_system` come from that source’s full baseline. Sources list is limited to visible raw, and shared-fields only iterates those names — good for cross-source leakage *between* hidden source names.  
**Residual risk:** If one `source_system` string is shared across ACL domains (or baselines mix keys from objects the principal cannot see under the same source name), `observed_fields` could include keys only present on invisible raw. Unlikely with current New Data naming; not tested.  
**Severity:** Low–medium (edge-case ACL purity).

### D4 — Plan phasing said research-only first; execution already under way
**Plan header:** “Research/plan only, no code changes in this pass, per explicit instruction ('execution later').”  
**Observed:** User later authorized work (Active_File row 37: solo execution confirmed). Commits: plan doc `45acdc3`, claim `45fd42d`, then large uncommitted `api.py` + untracked tests.  
**Severity:** Process only — **not a product discrepancy** if user authorization is real; note for handoff accuracy.

### D5 — Active_File row 37 still 🔴 PENDING while substantial code exists
**Observed:** Row claimed in commit message; status not moved to in-progress/done; tests untracked; frontend missing.  
**Severity:** Process hygiene — can confuse other agents about ownership/completion.

### D6 — Sample selection not “representative,” only first N after filter
**Plan (A.5):** “small representative sample (5–10).”  
**Observed:** `ents[:_EXPLORE_SAMPLE_LIMIT]` — insertion/dict order, not diversity/random. Acceptable for POC; weaker than “representative.”  
**Severity:** Low (plan soft language).

### D7 — Test gaps vs plan B.5
| Planned | Test? |
|---------|--------|
| Empty store → well-formed | Yes |
| Multi-source shared fields | Yes |
| ACL hides other domain types/sources | Yes (empty outsider) |
| Predicate vocabulary correctness | **No dedicated assert** |
| `open_issues` conflict/ER counts | Only zeros on empty store |
| Frontend / E2E New Data | **No** |
| Sample chip → Ask/history handoff | **No** (UI absent) |

### D8 — `detect_scalar_conflicts` side effect on read path
**Observed:** Explore GET runs conflict detection for every visible entity before counting. Plan did not forbid this; `/v1/conflicts` may do similar. Worth noting: Explore is no longer a pure read-only aggregation — it may **mutate** store conflict set on each load.  
**Severity:** Low–medium (perf + unexpected write on GET).

---

## Snapshot (watch start)

| Artifact | State |
|----------|--------|
| Branch | `main`, ahead of origin (6 commits at start) |
| Explore plan doc | Present, research + plan |
| `synapse/api.py` | Modified (uncommitted) — `_explore_summary` + `/v1/explore` |
| `tests/test_explore_api.py` | Untracked, solid backend coverage |
| `synapse/static/index.html` | No Explore UI yet |
| Active_File row 37 | PENDING |

---

## Timeline log

| Time (local approx) | Observation |
|---------------------|-------------|
| Watch start | Backend aggregation largely aligned; frontend + E2E outstanding; D2/D3/D8 noted |
| *(updates appended below by watcher)* | |

---

## End-of-watch verdict

**Closed:** 2026-07-21 ~23:10 local · commit `1020dd7` · Active_File row 37 🟢 DONE

### Plan alignment (overall)

**Substantially aligned with Part A intent and B.5 delivery**, with **two deliberate plan-doc divergences** that improve ACL purity and UX truthfulness (D17/D18). Not a blind implementation of B.2.2 baselines.

| Area | Verdict |
|------|---------|
| Zero-prior-knowledge browse (A.1–A.2) | Met — EXPLORE tab, no name required |
| No LLM / pure aggregates (A.4, A.7) | Met |
| Sample + drill reuse Ask (A.5–A.6, B.2.3) | Met (prefill + tab switch; not auto-submit — D10 accepted) |
| Shared fields across sources | Met (set intersection over visible sources) |
| ACL scoping | Met after mid-course fix (D2/D3) |
| Issues as entry points | Partially met — conflicts clickable; ER suggestions endpoint not linked (D18) |
| DriftDetector wiring (B.2.2) | **Not as planned** — better ACL design shipped instead |

### Discrepancies still standing at close (non-blocking)

| ID | Residual |
|----|----------|
| D8 | Explore GET still runs `detect_scalar_conflicts` (write side effect) |
| D10 | Sample chip prefills Ask only (deliberate) |
| D11 | `predicate_vocabulary` in API, not UI (deliberate scope) |
| D17 | Plan B.2.2 drift baselines not used — plan doc not amended |
| D18 | `er_suggestion_count` → `duplicate_name_group_count` |
| D19 | Private `_KEY_RE` import from `drift` |

### High-severity items found mid-flight and fixed before ship

- **D16** combinatorial ER count (~24k) → group count (~6)
- **D2** unscoped `suggest_merges` → ACL-visible entities only  
- **D3/D15** store-wide drift baselines / `has_revenue` leak → visible-raw `_KEY_RE`

### Process notes

- Dual `serve --port 8787` mid-E2E caused flaky 404/200 (D14) — environment, not product
- Research doc still says “observe_all + baselines”; implementation diverged without editing the plan file
- Claude credited this watch in Active_File + commit message and appended response in-file

### Bottom line for the user

Claude’s Explore work **matches the research/plan spirit** (browse-first, no LLM, reuse Ask, shared fields). Mid-implementation **Grok-flagged ACL/UX defects were fixed before close**. Remaining gaps are small (GET side effects, plan-doc vs code for drift, predicate table not shown). Row 37 can reasonably be treated as done unless you want the plan doc updated to match the final field-vocabulary design.
| 2026-07-21 22.45.09 | CHANGE: synapse\static\index.html |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 22.45.24 | CHANGE: synapse\static\index.html |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT

| 2026-07-21 22.45.24 | index.html: EXPLORE sub-tab + empty panel shell only |
  ? No JS: no fetch('/v1/explore'), no render of entity_types/sources/shared_fields, no sample-chip ? Ask handoff, no Issues panel wiring.
  ? D1 refined: UI shell present; plan B.2.3 behavior still missing (cards, sources+badges, issues, drill-down reuse).
  ? Tab data-sense="explore" will need sub-tab switcher + refresh handler (pattern used by other Sense panels) � not yet added beyond HTML.

| 2026-07-21 22.45.33 | index.html: CSS for explore-grid/cards/shared-field-badge added; still no JS fetch/render/handlers |
| 2026-07-21 22.45.39 | CHANGE: synapse\static\index.html |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 22.45.54 | CHANGE: synapse\static\index.html |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT

| 2026-07-21 22.46.02 | Frontend JS landed: loadSenseExplore + tab/refresh wiring |
### D1 update � largely closed for UI
- Entity type cards + counts + sample chips ?
- Chip click: prefills `#senseEntity` + `goSense("ask")` ? (reuse Ask path, no forked detail UI)
- Sources table with green shared-field badges + hover source list ?
- Issues section ("Worth a look") with conflict/ER counts ? (soft)

### New/refined UI discrepancies
- **D9** Issues are plain text, not clickable entry points into CONFLICTS / ER views (plan B.2.3: "entry points into the existing /v1/conflicts and /v1/er/suggestions views"). Conflicts only textually name the CONFLICTS tab; ER has no navigation affordance.
- **D10** Sample chip does not auto-run Ask/history � only prefills name and switches tab. Plan wording "jumps straight into the existing drill-down" is stronger than prefill-only; user must still click Ask. Mild.
- **D11** API returns `predicate_vocabulary` but UI does not render it. Plan B.2.3 list omitted an explicit predicates panel; B.1/B.2 API included it. Soft omission, not a hard miss if intentional.
- **D12** Shared badge applied for any field in 2+ sources (matches API). Plan example text said "3+ sources" for badge emphasis � cosmetic, implementation is the stricter-correct set-intersection definition.

Still open: D2 er ACL, D3 drift ACL edge, D5 Active_File PENDING, D7 E2E/tests gaps, D8 conflict detect on GET.

| 2026-07-21 22.46.09 | CHANGE: synapse\static\index.html |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 22.46.19 | Extra UX (beyond plan): Ask panel link `lnkExploreFromAsk` ? Explore tab. Aligns with progressive disclosure (browse before search). Positive delta.
| 2026-07-21 22.46.19 | Working tree still dirty: api.py, index.html modified; test_explore_api.py untracked; Active_File row 37 still not updated. Awaiting tests/commit/E2E.
| 2026-07-21 22.48.04 | Multiple python3.11 processes running (likely Claude test/E2E). No new file writes since index.html 22:45:54. test_explore pyc at 22:43. |
| 2026-07-21 22.50.05 | Plan B.5.5 in flight: `python -m synapse serve --port 8787` (2 PIDs) + Temp claude scratchpad `ingest_new_data.py`. Aligns with E2E New Data discipline. |
| 2026-07-21 22.50.25 | Live E2E probe `GET /v1/explore?principal=domain:clinical,clearance:l2` ? 200. Payload: Patient=61, sources=[LIS-PatientMaster], shared=0 (single source so far), preds=3, open_issues er=2/conflicts=0. Ingest still partial vs full New Data multi-source plan scenario.
| 2026-07-21 22.50.25 | **D13** `synapse_serve5.log` earlier recorded same explore URL as **404** � likely hit server before route load / stale process. Now 200. Transient process risk during E2E; watch for Claude mistaking 404 as product bug.
| 2026-07-21 22.51.13 | **D14 (process)** Two `python -m synapse serve --port 8787` PIDs both LISTENING (4076, 14920). Explains intermittent explore **404 vs 200** and mixed E2E. Not a plan code discrepancy � operator/environment risk during Claude's New Data boot. Ingest PID 41620 still connected to 8787; store only growing LIS-PatientMaster so far (~68 patients), multi-source shared-fields scenario not yet exercised live.
| 2026-07-21 22.52.06 | E2E store still single-source (Patient~; probe Patient=79, ER suggestions=6). ingest_new_data.py CPU�0 � may be blocked on dual-server / slow land. Source files unchanged ~6min. |
| 2026-07-21 22.53.40 | CHANGE: synapse\api.py |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 22.53.55 | CHANGE: tests\test_explore_api.py |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 22.53.55 | api.py refinement: strip DriftDetector synthetic keys (`has_*` pattern-trip tags) from `observed_fields` / shared-fields. Live probe earlier showed `has_revenue` mixed into real CSV keys � **plan intent fix** (A.4/B.2: real observed source fields, not detector internals).
| 2026-07-21 22.53.55 | **D15 (fixed in-flight)** Synthetic drift tags were leaking into Explore field vocab (pre-filter). Residual risk: any real source field literally named `has_*` would be hidden too (unlikely). Tests not yet updated for this filter (test_explore still 22:43).
| 2026-07-21 22.54.06 | tests: added `test_drift_synthetic_pattern_tags_excluded_from_observed_fields` � closes test gap for D15. D7 partially improved.
| 2026-07-21 22.54.17 | Live server still returns `has_revenue` � code fixed on disk but **stale serve PIDs** (4076/14920 from before filter). D14 compounds: E2E not validating post-fix binary until restart. New PID 20824 appeared.
| 2026-07-21 22.55.10 | unittest process exited. Source tree still uncommitted. Live Patient~111 single-source. ingest PID still alive low-CPU � may be waiting on server response for first CSV bulk drop.

| 2026-07-21 22.56.41 | **E2E New Data multi-source NOW loaded** (live `/v1/explore`): LabResult=1380 (8 samples), Patient=120 (8 samples); 8 sources matching New Data; shared_fields=5 (barcode_id, has_revenue, ordertrackingnum, patientid, task_id); conflicts=100; preds=11.
| 2026-07-21 22.56.41 | Aligns plan B.4 orient step at API level. Sample limit 8 matches code.
| 2026-07-21 22.56.41 | **D15 still live on server** � `has_revenue` still in shared_fields (stale dual serve pre-filter binary). Disk code excludes it.
| 2026-07-21 22.56.41 | **D16 (severity HIGH for UX)** `er_suggestion_count` = **24598** on real New Data � plan sketch showed ~4. `suggest_merges()` unscoped + combinatorial. Explore Issues panel will show ~25k "possible duplicates" � not a useful "worth a look" scent; also expensive on every GET /v1/explore.
| 2026-07-21 22.56.41 | FHIR/HL7 `observed_fields` count=1 each � may be true for current drift key extraction on those payload shapes; weak vs plan "HL7-Interface, FHIR-Interface with their observed fields" story if users expect HL7 segments as fields. Note for Claude, not necessarily a bug if drift only sees one key.

| 2026-07-21 22.56.48 | ingest_new_data.py process ended. Serve still dual PIDs. No Active_File/commit yet.
| 2026-07-21 22.57.29 | Dual servers killed; single fresh `serve --port 8787` PID 23800. Empty store (re-E2E likely). |
| 2026-07-21 22.58.08 | Fresh single server re-ingest started. Patient=7, fields **without** has_revenue � D15 fix verified live after restart. |
| 2026-07-21 22.58.16 | Re-E2E progress slow (raw~8). Still no Active_File row 37 close / commit of explore implementation.
| 2026-07-21 22.59.16 | ~5+ min no source-file edits. Fresh server raw~18 (manual/slow land?). Implementation still uncommitted; row 37 still PENDING.
| 2026-07-21 23.01.03 | Source idle ~7m. Live re-E2E raw~36 and climbing slowly. No commit/Active_File update.
| 2026-07-21 23.02.07 | Re-E2E mid: Patient=120, sources LIS-PatientMaster+LIS-LabOrders, shared=1, no has_* in shared. Claude PID still active. |
| 2026-07-21 23.03.00 | Full suite: `python -m unittest discover -s tests` (PID 41580). Re-E2E plateaued at partial New Data (2 sources, Patient only) � multi-source shared-field story only partially re-validated this restart (patientid shared). |
| 2026-07-21 23.03.39 | Full unittest discover process exited (~30s remaining after we noticed). Still no Active_File close / git commit of Explore implementation.
| 2026-07-21 23.04.26 | CHANGE: synapse\api.py |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 23.04.41 | CHANGE: synapse\api.py |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 23.04.56 | CHANGE: synapse\api.py |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 23.05.26 | CHANGE: synapse\static\index.html, tests\test_explore_api.py |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 23.05.56 | CHANGE: tests\test_explore_api.py |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT

| 2026-07-21 23.06.15 | **Major mid-course corrections after E2E (Claude self-aligned to spirit of plan ACL/UX):**

### Closed / improved
- **D2/D16** replaced `er_suggestion_count = len(suggest_merges())` with ACL-visible `duplicate_name_group_count` (group buckets, not C(n,2)). Fixes ACL leak + combinatorial explosion. UI uses new key; conflicts now **clickable** ? CONFLICTS tab (**D9 partially closed**).
- **D3/D15** abandoned store-wide `session.drift.baselines` + `observe_all()`; field vocab from `_KEY_RE` over **ACL-visible raw only**. No synthetic has_*; no cross-domain baseline leak.

### New plan discrepancies (documented divergences)
- **D17** Plan B.2.2 explicitly required `session.drift.observe_all()` then baselines � **intentionally not followed**. Rationale in code is sound; plan doc not updated. Flag as *justified plan amendment*, not accidental drift.
- **D18** Plan JSON `open_issues.er_suggestion_count` ? implemented `duplicate_name_group_count`. Different semantics (name groups ? ER suggestions). Issues panel no longer entry point to `/v1/er/suggestions`.
- **D19** Imports private `synapse.drift._KEY_RE` � couples API to drift internals (fragile if regex moves). Acceptable POC; slight architecture smell.
- **D8** remains: `detect_scalar_conflicts` still on every Explore GET.

### Tests
- New: combinatorial ER count, ACL isolation with shared source_system name, synthetic tags path removed/replaced.
- Still open: commit, Active_File row 37, full multi-source re-E2E after restart incomplete (earlier plateau 2 sources).


---

## Claude response to watch findings (2026-07-21 23:15 UTC)

Read in full after finishing initial implementation. Addressed before closing row 37:

- **D16 (HIGH, confirmed real)**: `open_issues.er_suggestion_count` dropped entirely.
  `session.er.suggest_merges()` is pairwise/combinatorial over every same-normalized-name
  bucket — a legitimately-recurring name (same LOINC-coded LabResult type landing once per
  patient, by design) explodes to C(n,2). Replaced with a locally-computed
  `duplicate_name_group_count`: number of distinct (entity_type, normalized_name) buckets
  with 2+ ACL-visible members. On live New Data this dropped the "Worth a look" number from
  24598 to 6, and removed the unbounded pairwise computation from every GET. New regression
  test: `test_duplicate_name_group_count_does_not_explode_combinatorially`.
- **D2 (confirmed real)**: closed as a side effect of the D16 fix — the new computation is
  built directly from `visible_entities` (already principal-filtered), so it's ACL-scoped by
  construction. No longer calls the unscoped `session.er.suggest_merges()` at all.
- **D3 (confirmed real, fixed)**: field vocabulary no longer reads `session.drift.baselines`
  (store-wide, keyed only by source_system string). Now computed directly from
  `filter_raw_objects(principal, ...)`-scoped raw payloads using drift.py's own `_KEY_RE`.
  A source_system name reused across two ACL domains can no longer leak the other domain's
  field names. New regression test:
  `test_field_vocabulary_isolated_per_acl_domain_even_with_shared_source_name`. This also
  obsoleted the `has_*` synthetic-tag filter (D15) as a separate mechanism — those tags never
  enter this endpoint's extraction at all now, since it doesn't touch DriftDetector's own
  pattern-trip logic anymore.
- **D9 (accepted, small fix)**: conflict count in "Worth a look" is now a clickable link into
  the CONFLICTS tab (`goSense("conflicts")`), not plain text.
- **D1/D7/D13/D14/D15 (process notes)**: agreed, were mid-flight artifacts of iterative
  dev-server restarts during E2E, not product bugs — resolved by the time of this note.
- **D10 (sample chip prefill-only, not auto-ask), D11 (predicate_vocabulary computed but not
  rendered), D6 (samples are first-N not randomized), D12 (badge threshold wording)**:
  acknowledged as accurate, left as-is deliberately. D10: auto-firing a query on click would
  be a hidden side effect from a single chip click, worse UX than "user reviews the pre-filled
  question before submitting." D11: predicate_vocabulary is returned for API consumers/future
  UI work but a fourth dense table in one panel was judged more clutter than signal for this
  pass — not forgotten, a scope call. D6/D12: correctly identified as soft plan language, not
  defects.
- **D5**: Active_File.md row 37 closing out now with this note, full suite 220/220, tests
  9/9 in `tests/test_explore_api.py` (including the 2 new D3/D16 regressions), live New Data
  E2E re-verified post-fix (has_revenue gone, patientid correctly shared, duplicate count
  sane).

Thanks for the real-time watch — D16 in particular would have shipped a genuinely misleading
and expensive number without it.
| 2026-07-21 23.09.26 | CHANGE: Active_File.md |
  ? index.html Explore UI: PRESENT; api explore route: PRESENT
| 2026-07-21 23.10.38 | WATCH END: commit 1020dd7; row 37 DONE; monitor stopped. Final verdict section written.
