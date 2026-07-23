"""Graph-First Discovery & Entity Resolution (docs/Graph-First Discovery
& Entity Resolution.pdf) -- entity-level curation, second layer alongside
synapse/matching.py's schema-field discovery."""

from __future__ import annotations

import unittest

from synapse.entity_matching import generate_entity_merge_candidates, score_entity_pair
from synapse.models import Entity, Fact
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore


def _fact(store: SemanticStore, entity_id: str, source_system: str, predicate: str = "seen") -> None:
    store.put_fact(
        Fact(
            fact_id=f"f-{entity_id}-{source_system}",
            subject_entity_id=entity_id,
            predicate=predicate,
            object="x",
            confidence=0.9,
            evidence_refs=[],
            source_system=source_system,
            acl_tags=["domain:sre", "clearance:l2"],
            valid_from="2026-01-01T00:00:00Z",
        )
    )


class TestEntityMatching(unittest.TestCase):
    def test_doc_example_justin_mason_vs_j_mason_across_systems(self) -> None:
        store = SemanticStore()
        crm = Entity.create("Person", "Justin Mason", acl_tags=["domain:sre", "clearance:l2"])
        billing = Entity.create("Person", "J. Mason", acl_tags=["domain:sre", "clearance:l2"])
        store.put_entity(crm)
        store.put_entity(billing)
        _fact(store, crm.entity_id, "CRM-Salesforce")
        _fact(store, billing.entity_id, "Billing-Zuora")

        candidates = generate_entity_merge_candidates(store)
        self.assertTrue(candidates, "expected Justin Mason / J. Mason to surface as a candidate")
        top = candidates[0]
        names = {top.entity_a["canonical_name"], top.entity_b["canonical_name"]}
        self.assertEqual(names, {"Justin Mason", "J. Mason"})
        self.assertIn("different source systems", " ".join(top.match_reasons))

    def test_unrelated_names_do_not_match(self) -> None:
        store = SemanticStore()
        a = Entity.create("Person", "Alice Nguyen", acl_tags=["domain:sre", "clearance:l2"])
        b = Entity.create("Person", "Bob Costa", acl_tags=["domain:sre", "clearance:l2"])
        store.put_entity(a)
        store.put_entity(b)
        edge = score_entity_pair(store, a, b)
        self.assertIsNone(edge)

    def test_same_system_duplicate_scores_lower_than_cross_system(self) -> None:
        store = SemanticStore()
        a = Entity.create("Person", "Maria Santos", acl_tags=["domain:sre", "clearance:l2"])
        b = Entity.create("Person", "Maria Santos", acl_tags=["domain:sre", "clearance:l2"])
        store.put_entity(a)
        store.put_entity(b)
        _fact(store, a.entity_id, "CRM-Salesforce")
        _fact(store, b.entity_id, "CRM-Salesforce")
        edge = score_entity_pair(store, a, b)
        self.assertIsNotNone(edge)
        self.assertNotIn("different source systems", " ".join(edge.match_reasons))

    def test_large_identically_named_block_is_linear_not_quadratic(self) -> None:
        # Real bug: 86 separately-created "Glucose" LabResult entities (one
        # per occurrence, never deduped at landing time) produced C(86, 2)
        # = 3655 pairwise candidates from this one block alone, burying
        # Resolve under thousands of near-identical cards. Candidates
        # should scale with block size (n-1, anchored), not its square.
        store = SemanticStore()
        acl = ["domain:sre", "clearance:l2"]
        entities = [Entity.create("LabResult", "Glucose", acl_tags=acl) for _ in range(20)]
        for e in entities:
            store.put_entity(e)
            _fact(store, e.entity_id, "HL7Feed")

        candidates = generate_entity_merge_candidates(store)
        self.assertEqual(len(candidates), 19)  # n - 1, not C(20, 2) = 190

        # Every non-anchor entity is still reachable in some candidate --
        # nothing is silently dropped, just not exhaustively paired.
        touched = {c.entity_a["entity_id"] for c in candidates} | {c.entity_b["entity_id"] for c in candidates}
        self.assertEqual(touched, {e.entity_id for e in entities})

        # Every candidate shares the same anchor as entity_a, so accepting
        # them one at a time (survivor = entity_a, the UI's convention)
        # collapses the whole block into one surviving entity.
        anchors = {c.entity_a["entity_id"] for c in candidates}
        self.assertEqual(len(anchors), 1)

    def test_strict_identity_types_excluded_when_ontology_given(self) -> None:
        # Real bug: LabResult is marked strict_identity=True in the
        # ontology precisely because entity_resolution.py's own
        # get_or_create() refuses to merge same-named LabResults/Patients
        # on name alone (a shared display name like "Glucose" is expected
        # across many different patients' results, not evidence they're
        # the same record) -- but this module ignored that flag entirely
        # and proposed exactly the merges the rest of the system exists
        # to prevent.
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        acl = ["domain:sre", "clearance:l2"]
        results = [Entity.create("LabResult", "Glucose", acl_tags=acl) for _ in range(5)]
        for e in results:
            store.put_entity(e)
            _fact(store, e.entity_id, "HL7Feed")

        # Without an ontology handle, existing (pre-fix) behavior is
        # unchanged -- still generates candidates.
        self.assertTrue(generate_entity_merge_candidates(store))

        # With the ontology handle, strict_identity types are excluded.
        candidates = generate_entity_merge_candidates(store, ontology=ontology)
        self.assertEqual(candidates, [])

    def test_non_strict_identity_types_unaffected_by_ontology_filter(self) -> None:
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        acl = ["domain:sre", "clearance:l2"]
        crm = Entity.create("Person", "Justin Mason", acl_tags=acl)
        billing = Entity.create("Person", "J. Mason", acl_tags=acl)
        store.put_entity(crm)
        store.put_entity(billing)
        _fact(store, crm.entity_id, "CRM-Salesforce")
        _fact(store, billing.entity_id, "Billing-Zuora")

        candidates = generate_entity_merge_candidates(store, ontology=ontology)
        self.assertTrue(candidates)


if __name__ == "__main__":
    unittest.main()
