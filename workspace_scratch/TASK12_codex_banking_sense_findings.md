# Task 12 — Banking Sense-board verification

**Date:** 2026-07-19
**Scope:** Verify the generic Sense board against `.data/banking_demo.db` produced by `scripts/smoke_banking_join.py`.

## Baseline and join proof

`smoke_banking_join.py` completed successfully:

- `AccountHolder`: 8
- `Account`: 10
- `Transaction`: 15
- Account → holder links: 10/10
- Transaction → account links: 15/15
- The two `John Smith` records remained distinct (`NID-55012` and `NID-55014`).

## Sense-board contract

The local server was run against `.data/banking_demo.db` on an isolated port with Graphiti unavailable; the local SQLite path remained functional.

| Panel | Verification | Result |
|---|---|---|
| Status strip | `GET /v1/sense/summary` | HTTP 200; raw 33, episodes 33, entities 33, facts 213, open conflicts 0, total conflicts 0. |
| RAW | `GET /v1/raw?limit=50` | HTTP 200; 33 banking raw objects with source and readable previews. |
| RAW / episodes | `GET /v1/episodes?limit=50` | HTTP 200; 33 prepped episodes with previews. |
| MEANING | `GET /v1/facts?limit=100` and `GET /v1/entities` | HTTP 200; AccountHolder, Account, and Transaction entities/facts returned, including resolved external links. |
| CONFLICTS | `GET /v1/conflicts` | HTTP 200; empty list, expected because this banking corpus contains no authored contradictory source view. |
| ASK | `POST /v1/query` | With a banking-scoped principal, Maria Garcia and John Smith both returned HTTP 200, allowed claims, citations, and the generic low-IDF/PageIndex route. |
| EMIT | `POST /v1/materialize` | HTTP 200; 213-row `entity_facts_active` view and CSV/JSON paths returned. |
| UI shell | `GET /` | HTTP 200; generic Sense-board HTML returned. |

## Real bug found

The generic UI sends `principal: "l2"` for ASK/query actions. `_principal_from_body` maps that principal to fixed tags for `domain:sre`, `domain:revenue`, and `domain:identity`, but not `domain:banking`. Consequently, the banking ASK path returns HTTP 403 (`policy denied`) when invoked using the same principal payload the UI sends. Supplying an explicit principal with `domain:banking` and `clearance:l2` returns HTTP 200 and the expected claim.

This is a shared policy/UI integration bug, not a banking-pack bug. It should not be patched as `if banking:`. Recommended generic fix: make the active domain/policy context explicit and pass it through the UI/API principal contract, or use a domain-agnostic authorization resolution that derives access from the selected dataset without weakening ACL checks. Add a regression test proving a non-default domain can use ASK through the actual UI request shape while an unauthorized principal remains denied.

## Conclusion

The banking pack satisfies the domain-pack contract and the generic board works for RAW, MEANING, CONFLICTS, and EMIT. ASK is correct with an explicit banking-scoped principal but fails through the current UI default principal. The issue is surfaced for Lead review; no code was silently changed.
