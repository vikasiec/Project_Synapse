# RC-03 (row 31) — Graphiti push/search ACL propagation: design

Follows directly from row 30's principal pattern, same trusted-local-POC
target. Graphiti's real multi-tenancy primitive is `group_id` (push,
`Graphiti.add_episode(..., group_id: str | None)`) and `group_ids`
(search, `Graphiti.search(query, group_ids: list[str] | None)`) —
confirmed against the actual installed `graphiti_core` signatures, not
guessed. This is the correct native mechanism to use, not an invented one.

## Push (`graph_memory.py`)

`group_id` is a single string; an episode's ACL is a set of tags. Encode
deterministically: `derive_group_id(acl_tags) = "|".join(sorted(acl_tags))`.
Pass `group_id=derive_group_id(ep.acl_tags)` on every `add_episode` call
(both the with/without-`reference_time` branches in `_push_episodes`).

## Search (`graphiti_ops.py`, `api.py` `/v1/graphiti/search`)

Two layers, not one, since `group_ids` is a query-side filter Graphiti
applies server-side — trusting it alone would mean no defense if a filter
were ever passed incorrectly:

1. **Query-side**: `GraphitiOps.search()` gains an optional
   `group_ids: Optional[list[str]]` passed straight to `client.search()`.
   The API route computes this from the principal: for every episode
   currently known locally whose `acl_tags` the principal's attributes
   cover (reusing row 30's `filter_episodes`), map through
   `derive_group_id` to get the allowed group_id set.
2. **Result-side**: `EntityEdge` (confirmed via `model_fields`) carries its
   own `group_id`. `SearchHit` gains a `group_id` field; `GraphitiOps.search`
   drops any hit whose `group_id` isn't in the allowed set, even if the
   query-side filter somehow let it through. Belt and suspenders — the
   review's own framing ("a remote graph is a derivative and must not
   become a policy escape hatch... local store filtering cannot repair a
   payload already sent to an unscoped remote index") is exactly why the
   result-side check exists, not just the query-side one.

## What's NOT in scope this pass

- Real Neo4j/live Graphiti integration testing — uses `RecordingGraphitiClient`
  (already exists for this purpose) and a fake search client, no live
  service required, matching row 31's own stated scope.
- Retroactively re-tagging episodes already pushed to a live Graphiti
  instance before this fix — out of scope, this is a going-forward fix.
