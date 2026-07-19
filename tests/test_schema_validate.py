import unittest

from synapse.models import Claim, Conflict, Entity, Episode, Fact, RawObject
from synapse.schema_validate import SchemaValidationError, list_schemas, validate_model_dict


class TestSchemaValidate(unittest.TestCase):
    def test_schemas_present(self):
        names = list_schemas()
        for expected in (
            "RawObject.schema.json",
            "Episode.schema.json",
            "Entity.schema.json",
            "Fact.schema.json",
            "Conflict.schema.json",
            "Claim.schema.json",
        ):
            self.assertIn(expected, names)

    def test_valid_raw_and_fact(self):
        raw = RawObject.create("sys", "hello world", ["domain:sre", "clearance:l2"])
        validate_model_dict("RawObject", raw.to_dict())
        ep = Episode.from_raw(raw, domain="infra_ops")
        validate_model_dict("Episode", ep.to_dict())
        ent = Entity.create("Service", "checkout-service", acl_tags=["domain:sre"])
        validate_model_dict("Entity", ent.to_dict())
        fact = Fact.create(
            ent.entity_id,
            "current_version",
            "v1.0.0",
            confidence=0.9,
            evidence_refs=[raw.object_id],
            source_system="sys",
            acl_tags=["domain:sre"],
        )
        validate_model_dict("Fact", fact.to_dict())
        conflict = Conflict.open(ent.entity_id, "current_version", [fact.fact_id, "00000000-0000-0000-0000-000000000099"])
        validate_model_dict("Conflict", conflict.to_dict())
        claim = Claim.create(
            "ok",
            supporting_fact_ids=[fact.fact_id],
            raw_citations=[raw.object_id],
            confidence=0.5,
        )
        validate_model_dict("Claim", claim.to_dict())

    def test_missing_required_fails(self):
        with self.assertRaises(SchemaValidationError):
            validate_model_dict("RawObject", {"object_id": "x"})


if __name__ == "__main__":
    unittest.main()
