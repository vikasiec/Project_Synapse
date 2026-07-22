"""Graph-First Discovery & Entity Resolution (docs/Graph-First Discovery
& Entity Resolution.pdf) -- entity-level curation, second layer alongside
synapse/matching.py's schema-field discovery."""

from __future__ import annotations

import unittest

from synapse.entity_matching import generate_entity_merge_candidates, score_entity_pair
from synapse.models import Entity, Fact
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


if __name__ == "__main__":
    unittest.main()
