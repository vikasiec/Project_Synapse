"""Major Goal 2 scoring — direct unit coverage of synapse/matching.py.

Complements tests/test_explore_analyze.py's HTTP-level VnV2 test with a
faster, lower-level check of a specific risk Grok's review flagged (F-021):
the synonym canonicalization table in synapse/profiling.py is aggressive
(account/acct -> customer, id/num/number -> identifier), which pushes
VectorSim toward 1.0 for many differently-named ID columns even when
they're actually unrelated. This test proves ValueOverlap/GraphProximity
still gate candidate emission -- a strong name match alone, with disjoint
values and no graph evidence, must NOT clear the 0.50 strict-drop floor.
"""

from __future__ import annotations

import unittest

from synapse.matching import VALUE_OVERLAP_OVERRIDE_THRESHOLD, score_pair, value_overlap, vector_sim
from synapse.models import RawObject
from synapse.ontology import OntologyRegistry
from synapse.profiling import SchemaProfiler
from synapse.store import SemanticStore


class TestMatchingNegative(unittest.TestCase):
    def test_synonym_matched_names_with_disjoint_values_stay_below_threshold(self) -> None:
        # account_id / customer_number both canonicalize to "customer
        # identifier" (VectorSim ~1.0), but these are two genuinely
        # unrelated ID spaces in real data -- no shared values, no
        # extracted-entity graph evidence.
        store = SemanticStore()
        acl = ["domain:sre", "clearance:l2"]
        for val in ("A1001", "A1002", "A1003"):
            store.put_raw(RawObject.create(source_system="Orders", payload=f"account_id: {val}", acl_tags=acl))
        for val in ("Z9001", "Z9002", "Z9003"):
            store.put_raw(RawObject.create(source_system="Loyalty", payload=f"customer_number: {val}", acl_tags=acl))

        profiler = SchemaProfiler(store)
        profile_a = profiler.profile_source("Orders")["account_id"]
        profile_b = profiler.profile_source("Loyalty")["customer_number"]

        edge = score_pair(store, OntologyRegistry.default(), profile_a, profile_b)
        self.assertIsNone(edge, f"expected strict-drop (None), got {edge}")

    def test_force_true_returns_manual_candidate_below_threshold(self) -> None:
        # Schema View: user drew a connection between two fields the
        # scorer alone would strict-drop. force=True must still return a
        # real CandidateEdge (not None) so the curation drawer has
        # something to show, tagged status="manual" with an explicit
        # below-threshold reason rather than silently pretending it
        # scored normally.
        store = SemanticStore()
        acl = ["domain:sre", "clearance:l2"]
        for val in ("A1001", "A1002", "A1003"):
            store.put_raw(RawObject.create(source_system="Orders", payload=f"account_id: {val}", acl_tags=acl))
        for val in ("Z9001", "Z9002", "Z9003"):
            store.put_raw(RawObject.create(source_system="Loyalty", payload=f"customer_number: {val}", acl_tags=acl))

        profiler = SchemaProfiler(store)
        profile_a = profiler.profile_source("Orders")["account_id"]
        profile_b = profiler.profile_source("Loyalty")["customer_number"]

        edge = score_pair(store, OntologyRegistry.default(), profile_a, profile_b, force=True)
        self.assertIsNotNone(edge)
        self.assertEqual(edge.status, "manual")
        self.assertTrue(any("Manually connected" in r for r in edge.match_reasons))

    def test_value_overlap_override_promotes_low_name_similarity_pair_to_candidate(self) -> None:
        # VectorSim leans on field *names* (char-trigrams + an English-only
        # synonym table) -- a genuinely related field in a differently-
        # languaged or differently-named source can score near-zero on
        # name alone. Real, strong value overlap should still be able to
        # clear the candidate bar on its own, without force=True.
        store = SemanticStore()
        acl = ["domain:sre", "clearance:l2"]
        shared_ids = ("84920112", "10293847", "55512309")
        for val in shared_ids:
            store.put_raw(RawObject.create(source_system="TableA", payload=f"customer_id: {val}", acl_tags=acl))
        # "codigo_referencia_unica_zzqx" shares no meaningful trigrams or
        # synonym-canon overlap with "customer_id" -- deliberately
        # name-dissimilar, same underlying identifier values.
        for val in shared_ids:
            store.put_raw(
                RawObject.create(source_system="TableB", payload=f"codigo_referencia_unica_zzqx: {val}", acl_tags=acl)
            )

        profiler = SchemaProfiler(store)
        profile_a = profiler.profile_source("TableA")["customer_id"]
        profile_b = profiler.profile_source("TableB")["codigo_referencia_unica_zzqx"]

        # Confirm the premise: name similarity alone contributes almost
        # nothing here (VECTOR_WEIGHT=0.45, so a near-zero vsim alone
        # cannot reach CANDIDATE_THRESHOLD=0.50 without real value overlap).
        self.assertLess(vector_sim(profile_a, profile_b), 0.3)
        self.assertGreaterEqual(value_overlap(profile_a, profile_b), VALUE_OVERLAP_OVERRIDE_THRESHOLD)

        edge = score_pair(store, OntologyRegistry.default(), profile_a, profile_b)
        self.assertIsNotNone(edge)
        self.assertEqual(edge.status, "candidate")
        self.assertTrue(any("different naming convention or language" in r for r in edge.match_reasons))

    def test_force_true_above_threshold_keeps_normal_status(self) -> None:
        # force=True must not change the status for a pair that would
        # have cleared the threshold anyway -- only the below-threshold
        # path gets the "manual" treatment.
        store = SemanticStore()
        acl = ["domain:sre", "clearance:l2"]
        shared_ids = ("84920112", "10293847", "55512309")
        for val in shared_ids:
            store.put_raw(RawObject.create(source_system="TableA", payload=f"cust_id: {val}", acl_tags=acl))
        for val in shared_ids:
            store.put_raw(RawObject.create(source_system="TableB", payload=f"client_num: {val}", acl_tags=acl))

        profiler = SchemaProfiler(store)
        profile_a = profiler.profile_source("TableA")["cust_id"]
        profile_b = profiler.profile_source("TableB")["client_num"]

        edge = score_pair(store, OntologyRegistry.default(), profile_a, profile_b, force=True)
        self.assertIsNotNone(edge)
        self.assertIn(edge.status, ("candidate", "high_confidence"))
        self.assertFalse(any("Manually connected" in r for r in edge.match_reasons))


if __name__ == "__main__":
    unittest.main()
