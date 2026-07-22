import tempfile
import unittest
from pathlib import Path

from synapse.models import RawObject
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.session import open_session
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

    def test_ontology_relationships_survive_restart(self):
        # F-027: an accepted/rejected relationship must still be there
        # after the process restarts, not just within one session's
        # in-memory OntologyRegistry.
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "synapse_relationships.db"

            session1 = open_session(db_path=str(db))
            acl = ["domain:sre", "clearance:l2"]
            for val in ("84920112", "10293847", "55512309"):
                session1.store.put_raw(
                    RawObject.create(source_system="TableA", payload=f"cust_id: {val}", acl_tags=acl)
                )
                session1.store.put_raw(
                    RawObject.create(source_system="TableB", payload=f"client_num: {val}", acl_tags=acl)
                )
            from synapse.matching import analyze_sources
            from synapse.profiling import SchemaProfiler

            profiler = SchemaProfiler(session1.store)
            candidates = analyze_sources(
                session1.store,
                session1.ontology,
                profiler.profile_source("TableA"),
                profiler.profile_source("TableB"),
            )
            edge = session1.ontology.accept_relationship(
                candidate_id=candidates[0].candidate_id,
                source_a=candidates[0].source_a,
                source_b=candidates[0].source_b,
                match_reasons=candidates[0].match_reasons,
                similarity_score=candidates[0].similarity_score,
            )
            session1.close()

            session2 = open_session(db_path=str(db))
            self.assertIn(edge.relationship_id, session2.ontology.relationships)
            reloaded = session2.ontology.relationships[edge.relationship_id]
            self.assertEqual(reloaded.source_a["field_name"], "cust_id")
            self.assertEqual(reloaded.source_b["field_name"], "client_num")
            session2.close()


if __name__ == "__main__":
    unittest.main()
