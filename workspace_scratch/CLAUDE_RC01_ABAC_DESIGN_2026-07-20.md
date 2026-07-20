# RC-01 (row 30) — ABAC gate on API routes: design

**Target confirmed by Vikas:** trusted-local POC, not authenticated/multi-tenant.
That means this fix is about **authorization** (data respects the principal
that's stated) — not **authentication** (verifying who's actually calling).
Real auth (tokens/sessions/spoofing prevention) stays out of scope, and that
boundary is stated explicitly in the resolution note, not silently implied
as solved.

## What's in scope

1. **Every route resolves a principal.** GET routes currently have none at
   all. Add `_principal_from_query(qs, store)` mirroring the existing,
   already-tested `_principal_from_body` logic (same l1/l2/dict/csv-string
   forms), reading from the parsed query string instead of the JSON body.
   Refactor the shared resolution logic into one internal function so GET
   and POST paths can't drift.

2. **Read routes filter by that principal**, reusing `security.py`'s
   existing, tested `filter_raw_objects`/`filter_facts` — not inventing new
   filtering logic:
   - `/v1/raw` → `filter_raw_objects`
   - `/v1/facts` → `filter_facts` (already exists, just not called here)
   - `/v1/episodes` → new `filter_episodes` (mirrors `filter_raw_objects`,
     `Episode.acl_tags` already exists on the model)
   - `/v1/entities` → new `filter_entities` (mirrors the same pattern,
     `Entity.acl_tags` already exists)
   - `/v1/conflicts` → visible iff principal covers
     `derived_acl_from_facts()` of the conflict's `competing_fact_ids`
     (reuses the existing intersection helper — a conflict is only visible
     if you can see everything it's comparing, not a partial view that
     could mislead)
   - `/v1/history` (GET `/v1/history/{name}` and POST `/v1/history`) →
     entity-gate first (404 if `entity.acl_tags` not covered — matches the
     existing deny-quiet convention elsewhere), then filter the timeline's
     underlying facts with `filter_facts` before formatting. Deliberately
     not touching `TemporalService.timeline()`'s signature — it's a
     lower-level, separately-tested service used elsewhere; filtering
     happens at the API layer instead, which is where the other filters
     live too.

3. **A minimal role tag for the routes RC-01 explicitly named as
   unguarded mutations**, not a full viewer/extractor/adjudicator/operator
   taxonomy (that's the target-(b) shape, out of scope here):
   `role:operator` required for: `/v1/entities/merge`, conflict pin
   (`_PIN_RE`), `/v1/reprocess`, `/v1/materialize`, `/v1/actions/decide`,
   `/v1/connectors/poll`, `/v1/connectors/mock-emit`, `/v1/sense/drop`,
   `/v1/webhook`, `/v1/inbox/poll`. `role:admin` required for `/v1/export`
   and `/v1/audit` (not per-record ACL-filtered — the audit log isn't
   fact-ACL-tagged at all, and `export_store()` is also used by legitimate
   full-backup/CLI paths elsewhere; gating the *route* behind a stricter
   role is the correct-sized fix here, not rewriting `export_import.py`'s
   core function signature for every caller).
   - `l1`/`l2` presets (`_principal_from_body`/`_principal_from_query`)
     gain `role:operator` so the existing Sense board UI keeps working
     exactly as today — this preserves current behavior for the trusted
     local demo while making the requirement explicit and testable instead
     of implicitly absent.
   - Neither preset gains `role:admin` — export/audit become *more*
     restricted by default than today, requiring an explicit
     `role:admin`-tagged principal. This is a genuine, testable tightening.

## What's deliberately NOT in scope this pass (stated, not hidden)

- **No real authentication.** Anyone can still claim any principal/role by
  passing it in — this fix makes the *stated* principal's ACL actually
  matter, it does not verify the caller is who they claim. True auth is the
  target-(b) shape.
- **`/v1/ingest` and `/v1/seed` are not role-gated.** RC-01's own route list
  named `/v1/sense/drop` and connector-poll/mock-emit as the mutation
  routes needing a gate, not these two. They're functionally similar-risk
  (landing arbitrary data with arbitrary ACL tags), so this is flagged as a
  known, similarly-scoped follow-up, not silently left inconsistent.
- **`/v1/graph`, `/v1/er/suggestions`, and the various `/v1/metrics`
  `/v1/cost` `/v1/capability` `/v1/poc-status` `/v1/engines` `/v1/ontology`
  `/v1/drift` `/v1/actions` `/v1/connectors` `/v1/stats`
  `/v1/sense/summary`** — meta/aggregate/system-status endpoints RC-01
  didn't name, out of scope for this pass.
- **`/v1/query` and `/v1/ask`** already resolve and apply a principal via
  `_principal_from_body` — unchanged, already correct.

## Tests to add

- Negative test per gated read route: an l1-equivalent-but-missing-ACL
  principal (or a principal with an unrelated domain tag) sees a filtered
  or empty result, not the full store.
- Negative test per role-gated mutation route: a principal without
  `role:operator`/`role:admin` gets 403, not the mutation applied.
- Positive test: existing l1/l2 presets still succeed on every route
  (no regression to the current demo UI flow).
