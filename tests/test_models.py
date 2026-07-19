import unittest

from synapse.models import Claim, Conflict, Entity, Episode, Fact, RawObject


class TestModels(unittest.TestCase):
    def test_raw_object_hash_stable(self):
        a = RawObject.create("sys", "hello", ["domain:sre"])
        b = RawObject.create("sys", "hello", ["domain:sre"])
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertNotEqual(a.object_id, b.object_id)

    def test_episode_inherits_acl(self):
        raw = RawObject.create("sys", "payload text here", ["domain:sre", "clearance:l2"])
        ep = Episode.from_raw(raw, domain="infra_ops")
        self.assertEqual(ep.acl_tags, raw.acl_tags)
        self.assertIn(raw.object_id, ep.raw_object_ids)

    def test_fact_confidence_clamped(self):
        f = Fact.create(
            "e1",
            "p",
            "v",
            confidence=1.5,
            evidence_refs=["r1"],
            source_system="sys",
            acl_tags=["domain:sre"],
        )
        self.assertEqual(f.confidence, 1.0)

    def test_conflict_and_claim_dicts(self):
        c = Conflict.open("e1", "current_version", ["f1", "f2"])
        self.assertEqual(c.to_dict()["status"], "open")
        claim = Claim.create(
            "hello",
            supporting_fact_ids=["f1"],
            raw_citations=["r1"],
            confidence=0.5,
        )
        self.assertEqual(claim.to_dict()["statement"], "hello")
        ent = Entity.create("Service", "checkout-service")
        self.assertEqual(ent.to_dict()["status"], "active")


if __name__ == "__main__":
    unittest.main()
