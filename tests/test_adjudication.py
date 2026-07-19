import unittest

from synapse.adjudication import AdjudicationError, AdjudicationService
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario


class TestAdjudication(unittest.TestCase):
    def test_human_pin_resolves_and_changes_claim(self):
        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()
        l2 = CheckoutIncidentScenario.principal_l2()

        pre = bundle.query.ask(l2, entity_name="checkout-service")
        self.assertTrue(pre.allowed)
        version_view = next(
            v for v in pre.conflict_views if v.conflict.predicate == "current_version"
        )
        self.assertEqual(version_view.surface_policy, "SURFACED_AMBIGUOUS_CONFLICT")

        k8s = next(r for r in version_view.ranked if r.fact.source_system == "K8s-Cluster-Alpha")
        pin = bundle.adjudication.human_pin(
            version_view.conflict.conflict_id,
            chosen_fact_id=k8s.fact.fact_id,
            adjudicator="sre-lead@example.com",
            reason="Runtime state is authoritative over CI success.",
        )
        self.assertEqual(pin.conflict.status.value, "resolved")
        self.assertEqual(pin.conflict.resolution.method, "human_pin")

        post = bundle.query.ask(l2, entity_name="checkout-service")
        vpost = next(v for v in post.conflict_views if v.conflict.predicate == "current_version")
        self.assertEqual(vpost.surface_policy, "RESOLVED_HUMAN_PIN")
        self.assertIn("HUMAN_PIN", post.claim.statement)
        self.assertIn("v2.4.0", post.claim.statement)

    def test_pin_rejects_unknown_fact(self):
        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()
        l2 = CheckoutIncidentScenario.principal_l2()
        pre = bundle.query.ask(l2, entity_name="checkout-service")
        cid = pre.conflict_views[0].conflict.conflict_id
        with self.assertRaises(AdjudicationError):
            bundle.adjudication.human_pin(
                cid,
                chosen_fact_id="00000000-0000-0000-0000-000000000000",
                adjudicator="x",
                reason="nope",
            )


if __name__ == "__main__":
    unittest.main()
