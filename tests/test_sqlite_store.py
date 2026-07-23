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

    def test_legacy_hl7_field_names_migrated_on_session_open(self):
        # open_session() runs hl7_semantics.migrate_legacy_field_names()
        # every startup -- a RelationshipEdge confirmed before HL7
        # profiling became segment-aware (old flat "OBX.5" naming) must
        # come back rewritten to the new virtual source + real field name
        # on the very next session open, not stay dangling.
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "synapse_legacy_hl7.db"

            session1 = open_session(db_path=str(db))
            edge = session1.ontology.accept_relationship(
                candidate_id="cand-legacy",
                source_a={"source_system": "new_data_hl7_v2_oru_r01", "field_name": "OBX.5"},
                source_b={"source_system": "new_data_mw_results", "field_name": "numericvalue"},
                predicate="SAME_ENTITY_AS",
            )
            relationship_id = edge.relationship_id
            session1.close()

            session2 = open_session(db_path=str(db))
            updated = session2.ontology.relationships[relationship_id]
            self.assertEqual(
                updated.source_a,
                {"source_system": "new_data_hl7_v2_oru_r01::OBX", "field_name": "observation_value"},
            )
            session2.close()

    def test_schema_layout_survives_restart(self):
        # Schema View: a deliberately-arranged canvas position must look
        # the same on the next visit, not reset to auto-layout.
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "synapse_layout.db"

            session1 = open_session(db_path=str(db))
            session1.store.put_layout_position("TableA", 123.5, 456.0)
            session1.close()

            session2 = open_session(db_path=str(db))
            self.assertIn("TableA", session2.store.schema_layout)
            entry = session2.store.schema_layout["TableA"]
            self.assertEqual(entry["x"], 123.5)
            self.assertEqual(entry["y"], 456.0)
            session2.close()

    def test_deleted_workspace_stays_deleted_after_restart(self):
        from synapse.workspace import Workspace

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "synapse_delete_ws.db"

            session1 = open_session(db_path=str(db))
            ws = Workspace.create("Temp Workspace")
            session1.store.put_workspace(ws)
            session1.store.put_raw(
                RawObject.create(source_system="TempSource", payload="x: 1", acl_tags=[], workspace_id=ws.workspace_id)
            )
            session1.store.put_layout_position("TempSource", 1.0, 2.0)
            session1.store.delete_workspace(ws.workspace_id, ontology=session1.ontology)
            session1.close()

            session2 = open_session(db_path=str(db))
            self.assertNotIn(ws.workspace_id, session2.store.workspaces)
            self.assertFalse(any(r.source_system == "TempSource" for r in session2.store.raw_objects.values()))
            self.assertNotIn("TempSource", session2.store.schema_layout)
            session2.close()


if __name__ == "__main__":
    unittest.main()
