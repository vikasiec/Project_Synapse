import unittest

from synapse.harness import run_checkout_incident_simulation
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario


class TestIncidentScenario(unittest.TestCase):
    def test_seed_extracts_entity_and_version_conflict(self):
        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()
        store = bundle.store

        self.assertEqual(len(store.raw_objects), 3)
        entity = store.get_entity_by_name("checkout-service")
        self.assertIsNotNone(entity)

        facts = store.facts_for_entity(entity.entity_id, predicate="current_version")
        values = {str(f.object) for f in facts}
        self.assertIn("v2.4.1", values)
        self.assertIn("v2.4.0", values)

    def test_abac_l1_denied_l2_allowed_with_conflict(self):
        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()

        denied = bundle.query.ask(
            CheckoutIncidentScenario.principal_l1(),
            entity_name="checkout-service",
        )
        allowed = bundle.query.ask(
            CheckoutIncidentScenario.principal_l2(),
            entity_name="checkout-service",
        )

        self.assertFalse(denied.allowed)
        self.assertTrue(allowed.allowed)
        self.assertIsNotNone(allowed.claim)
        self.assertTrue(allowed.conflict_views)
        self.assertTrue(any(v.conflict.predicate == "current_version" for v in allowed.conflict_views))

        version_view = next(
            v for v in allowed.conflict_views if v.conflict.predicate == "current_version"
        )
        self.assertIsNotNone(version_view.preferred)
        self.assertEqual(version_view.preferred.fact.source_system, "K8s-Cluster-Alpha")

    def test_harness_report_shape(self):
        report = run_checkout_incident_simulation(verbose=False, demonstrate_pin=True)
        self.assertEqual(report["scenario"], "checkout_incident")
        self.assertEqual(report["counts"]["raw_objects"], 3)
        self.assertFalse(report["abac"]["l1_allowed"])
        self.assertTrue(report["abac"]["l2_allowed"])
        self.assertTrue(report["query_l2_pre_pin"]["claim"]["route_used"])
        self.assertIsNotNone(report["human_pin"])
        self.assertIn("HUMAN_PIN", report["query_l2_post_pin"]["claim"]["statement"])


if __name__ == "__main__":
    unittest.main()
