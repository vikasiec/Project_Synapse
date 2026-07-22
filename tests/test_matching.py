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

from synapse.matching import score_pair
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


if __name__ == "__main__":
    unittest.main()
