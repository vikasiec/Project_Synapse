# Synapse frozen contracts (Phase 1)

Machine-readable JSON Schema (Draft 2020-12) for the semantic data plane.

| Schema | Object |
|--------|--------|
| `RawObject.schema.json` | Immutable landing-zone bytes + ACL |
| `Episode.schema.json` | Prepared extract unit |
| `Entity.schema.json` | Resolved identity |
| `Fact.schema.json` | Temporal claim with evidence |
| `Conflict.schema.json` | Multi-source discrepancy + resolution |
| `Claim.schema.json` | Query-time answer packet |

Runtime validation (stdlib, no extra deps):

```python
from synapse.schema_validate import validate_model_dict
validate_model_dict("RawObject", raw.to_dict())
```

These schemas lock the Phase 1 contract surface. Breaking changes require an ADR.
