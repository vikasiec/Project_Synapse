import unittest

from synapse.entity_resolution import EntityResolutionService, normalize_name
from synapse.models import EntityStatus
from synapse.scenarios.billing_customer import BillingCustomerScenario
from synapse.store import SemanticStore


class TestEntityResolution(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_name("Acme Corp"), normalize_name("ACME CORP"))
        self.assertEqual(normalize_name("Acme-Corp"), "acmecorp")

    def test_billing_collapses_to_one_customer(self):
        scenario = BillingCustomerScenario()
        bundle = scenario.seed()
        customers = [
            e
            for e in bundle.store.entities.values()
            if e.entity_type == "Customer" and e.status == EntityStatus.ACTIVE
        ]
        self.assertEqual(len(customers), 1, msg=[c.canonical_name for c in customers])
        ent = customers[0]
        # Both casings resolve
        self.assertIsNotNone(bundle.store.get_entity_by_name("Acme Corp"))
        self.assertIsNotNone(bundle.store.get_entity_by_name("ACME CORP"))

        revenues = {
            str(f.object)
            for f in bundle.store.facts_for_entity(ent.entity_id, "annual_revenue")
            if f.valid_to is None
        }
        self.assertIn("1200000.0", revenues)
        self.assertIn("950000.0", revenues)

        l2 = BillingCustomerScenario.principal_l2()
        result = bundle.query.ask(l2, entity_name="Acme Corp")
        self.assertTrue(result.allowed)
        self.assertTrue(
            any(v.conflict.predicate == "annual_revenue" for v in result.conflict_views)
        )
        self.assertIn("AMBIGUOUS annual_revenue", result.claim.statement)

    def test_explicit_merge(self):
        store = SemanticStore()
        er = EntityResolutionService(store)
        a = er.get_or_create(
            "Customer", "Foo Inc", source_system="A", acl_tags=["domain:revenue"]
        )
        # Force a second entity by different normalized key then merge
        b = er.get_or_create(
            "Customer", "Bar Inc", source_system="B", acl_tags=["domain:revenue"]
        )
        from synapse.models import Fact

        Fact  # silence
        fact = __import__("synapse.models", fromlist=["Fact"]).Fact.create(
            b.entity_id,
            "annual_revenue",
            1,
            confidence=0.9,
            evidence_refs=["x"],
            source_system="B",
            acl_tags=["domain:revenue"],
        )
        store.put_fact(fact)
        merge = er.merge(a.entity_id, b.entity_id, adjudicator="tester", reason="dup")
        self.assertEqual(merge.facts_rewritten, 1)
        self.assertEqual(store.entities[b.entity_id].status, EntityStatus.MERGED)
        self.assertEqual(store.entities[b.entity_id].merged_into, a.entity_id)
        self.assertEqual(store.facts[fact.fact_id].subject_entity_id, a.entity_id)


if __name__ == "__main__":
    unittest.main()
