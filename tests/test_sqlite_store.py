import tempfile
import unittest
from pathlib import Path

from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.sqlite_store import SqliteSemanticStore


class TestSqliteStore(unittest.TestCase):
    def test_persist_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "synapse.db"
            store1 = SqliteSemanticStore(db)
            scenario = CheckoutIncidentScenario(store=store1)
            bundle = scenario.seed()
            entity = store1.get_entity_by_name("checkout-service")
            self.assertIsNotNone(entity)
            n_facts = len(store1.facts)
            store1.close()

            store2 = SqliteSemanticStore(db)
            self.assertEqual(len(store2.raw_objects), 3)
            self.assertEqual(len(store2.facts), n_facts)
            self.assertIsNotNone(store2.get_entity_by_name("checkout-service"))
            store2.close()

    def test_pin_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "synapse_pin.db"
            store1 = SqliteSemanticStore(db)
            scenario = CheckoutIncidentScenario(store=store1)
            bundle = scenario.seed()
            l2 = CheckoutIncidentScenario.principal_l2()
            pre = bundle.query.ask(l2, entity_name="checkout-service")
            view = next(v for v in pre.conflict_views if v.conflict.predicate == "current_version")
            chosen = next(r for r in view.ranked if r.fact.source_system == "K8s-Cluster-Alpha")
            bundle.adjudication.human_pin(
                view.conflict.conflict_id,
                chosen_fact_id=chosen.fact.fact_id,
                adjudicator="ops@example.com",
                reason="runtime pin",
            )
            store1.close()

            store2 = SqliteSemanticStore(db)
            scenario2 = CheckoutIncidentScenario(store=store2)
            bundle2 = scenario2.seed(skip_if_populated=True)
            post = bundle2.query.ask(l2, entity_name="checkout-service")
            v2 = next(v for v in post.conflict_views if v.conflict.predicate == "current_version")
            self.assertEqual(v2.surface_policy, "RESOLVED_HUMAN_PIN")
            store2.close()


if __name__ == "__main__":
    unittest.main()
