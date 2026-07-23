"""Workspaces: the top-level project boundary sources are imported into.
One workspace's confirmed relationships are its schema; multiple
workspaces give multiple schemas."""

from __future__ import annotations

import unittest

from synapse.matching import score_pair
from synapse.models import RawObject
from synapse.ontology import OntologyRegistry
from synapse.session import open_session
from synapse.store import SemanticStore
from synapse.workspace import DEFAULT_WORKSPACE_ID, Workspace


class TestWorkspace(unittest.TestCase):
    def test_put_and_lookup(self) -> None:
        store = SemanticStore()
        ws = Workspace.create("Lab Ops", "Lab data")
        store.put_workspace(ws)
        self.assertIn(ws.workspace_id, store.workspaces)
        self.assertEqual(store.workspaces[ws.workspace_id].name, "Lab Ops")

    def test_raw_object_defaults_to_default_workspace(self) -> None:
        raw = RawObject.create(source_system="X", payload="a: 1", acl_tags=[])
        self.assertEqual(raw.workspace_id, "default")

    def test_workspace_for_source_resolves_real_and_virtual_names(self) -> None:
        store = SemanticStore()
        ws = Workspace.create("Clinical")
        store.put_workspace(ws)
        store.put_raw(
            RawObject.create(source_system="LabFile", payload="a: 1", acl_tags=[], workspace_id=ws.workspace_id)
        )
        self.assertEqual(store.workspace_for_source("LabFile"), ws.workspace_id)
        # A virtual sub-source ("base::SEGMENT") resolves back to the same
        # workspace as its base source.
        self.assertEqual(store.workspace_for_source("LabFile::PID"), ws.workspace_id)

    def test_workspace_for_unknown_source_is_none(self) -> None:
        store = SemanticStore()
        self.assertIsNone(store.workspace_for_source("Nope"))

    def test_ensure_default_workspace_idempotent(self) -> None:
        store = SemanticStore()
        first = store.ensure_default_workspace()
        second = store.ensure_default_workspace()
        self.assertEqual(first.workspace_id, DEFAULT_WORKSPACE_ID)
        self.assertEqual(first.workspace_id, second.workspace_id)
        self.assertEqual(len(store.workspaces), 1)

    def test_open_session_auto_creates_default_workspace(self) -> None:
        session = open_session()
        self.assertIn(DEFAULT_WORKSPACE_ID, session.store.workspaces)
        session.close()


class TestCloneWorkspace(unittest.TestCase):
    def _seeded_store(self):
        from synapse.profiling import SchemaProfiler

        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = Workspace.create("Lab Ops")
        store.put_workspace(ws)
        store.put_raw(
            RawObject.create(source_system="Orders", payload="order_id: O1\npatient_id: P1\n", acl_tags=[], workspace_id=ws.workspace_id)
        )
        store.put_raw(
            RawObject.create(source_system="Patients", payload="patient_id: P1\nname: Jane\n", acl_tags=[], workspace_id=ws.workspace_id)
        )
        profiler = SchemaProfiler(store)
        profiles_a = profiler.profile_source("Orders")
        profiles_b = profiler.profile_source("Patients")
        edge = score_pair(store, ontology, profiles_a["patient_id"], profiles_b["patient_id"], force=True)
        ontology.accept_relationship(
            candidate_id=edge.candidate_id,
            source_a=edge.source_a,
            source_b=edge.source_b,
            predicate="SAME_ENTITY_AS",
            match_reasons=edge.match_reasons,
            similarity_score=edge.similarity_score,
        )
        store.put_layout_position("Orders", 10, 20)
        return store, ontology, ws

    def test_clone_creates_new_workspace(self) -> None:
        store, ontology, ws = self._seeded_store()
        clone = store.clone_workspace(ws.workspace_id, "Lab Ops Copy")
        self.assertNotEqual(clone.workspace_id, ws.workspace_id)
        self.assertEqual(clone.name, "Lab Ops Copy")
        self.assertIn(clone.workspace_id, store.workspaces)

    def test_clone_copies_sources_under_renamed_source_system(self) -> None:
        store, ontology, ws = self._seeded_store()
        clone = store.clone_workspace(ws.workspace_id, "Lab Ops Copy")

        cloned_raws = [r for r in store.raw_objects.values() if r.workspace_id == clone.workspace_id]
        cloned_names = {r.source_system for r in cloned_raws}
        self.assertEqual(len(cloned_raws), 2)
        # Renamed, not reused -- source_system is a global identity key.
        self.assertNotIn("Orders", cloned_names)
        self.assertNotIn("Patients", cloned_names)
        # Original workspace's own sources are untouched.
        original_raws = [r for r in store.raw_objects.values() if r.workspace_id == ws.workspace_id]
        self.assertEqual({r.source_system for r in original_raws}, {"Orders", "Patients"})

    def test_clone_copies_confirmed_relationships_with_remapped_fields(self) -> None:
        store, ontology, ws = self._seeded_store()
        clone = store.clone_workspace(ws.workspace_id, "Lab Ops Copy")

        cloned_raws = [r for r in store.raw_objects.values() if r.workspace_id == clone.workspace_id]
        cloned_names = {r.source_system for r in cloned_raws}

        matching_edges = [
            e
            for e in store.relationship_edges.values()
            if e.source_a["source_system"] in cloned_names or e.source_b["source_system"] in cloned_names
        ]
        self.assertEqual(len(matching_edges), 1)
        edge = matching_edges[0]
        self.assertIn(edge.source_a["source_system"], cloned_names)
        self.assertIn(edge.source_b["source_system"], cloned_names)
        self.assertEqual(edge.source_a["field_name"], "patient_id")
        self.assertEqual(edge.source_b["field_name"], "patient_id")
        # Original relationship still exists, untouched.
        original_edges = [e for e in store.relationship_edges.values() if e.source_a["source_system"] == "Orders"]
        self.assertEqual(len(original_edges), 1)

    def test_clone_with_ontology_keeps_live_registry_in_sync(self) -> None:
        # Real bug: writing straight into store.relationship_edges without
        # also updating the live OntologyRegistry.relationships dict left
        # GET /v1/ontology (which reads the registry, not the store,
        # per OntologyRegistry.describe()) showing zero relationships for
        # a freshly cloned workspace even though the store itself had them.
        store, ontology, ws = self._seeded_store()
        rel_count_before = len(ontology.relationships)
        clone = store.clone_workspace(ws.workspace_id, "Lab Ops Copy", ontology=ontology)
        self.assertEqual(len(ontology.relationships), rel_count_before + 1)

        cloned_raws = [r for r in store.raw_objects.values() if r.workspace_id == clone.workspace_id]
        cloned_names = {r.source_system for r in cloned_raws}
        new_edges = [e for e in ontology.relationships.values() if e.source_a["source_system"] in cloned_names]
        self.assertEqual(len(new_edges), 1)

    def test_clone_without_ontology_still_updates_store_only(self) -> None:
        store, ontology, ws = self._seeded_store()
        store.clone_workspace(ws.workspace_id, "Lab Ops Copy")
        self.assertEqual(len(ontology.relationships), 1)  # unchanged -- no ontology handle passed

    def test_clone_copies_schema_layout(self) -> None:
        store, ontology, ws = self._seeded_store()
        clone = store.clone_workspace(ws.workspace_id, "Lab Ops Copy")
        cloned_raws = [r for r in store.raw_objects.values() if r.workspace_id == clone.workspace_id]
        orders_clone_name = next(r.source_system for r in cloned_raws if r.raw_payload.startswith("order_id"))
        self.assertIn(orders_clone_name, store.schema_layout)
        self.assertEqual(store.schema_layout[orders_clone_name]["x"], 10)
        self.assertEqual(store.schema_layout[orders_clone_name]["y"], 20)


if __name__ == "__main__":
    unittest.main()
