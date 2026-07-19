import unittest

from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
from synapse.ingestion import IngestionService
from synapse.store import SemanticStore


class TestDualPath(unittest.TestCase):
    def test_path_a_and_residual_note(self):
        store = SemanticStore()
        ing = IngestionService(store)
        dual = DualPathExtractor(store, residual=HeuristicResidualExtractor())
        result = ing.land(
            "GitHub-CI",
            "BUILD SUCCESSFUL: checkout-service deployed image tag v3.0.0 automatically.\n"
            "note: rollback risk high for EU region\n",
            ["domain:sre", "clearance:l2"],
        )
        out = dual.extract(result.episode, result.raw)
        self.assertEqual(out.entity_name, "checkout-service")
        self.assertTrue(out.deterministic_facts)
        self.assertTrue(out.path_b_used)
        self.assertTrue(any(f.predicate == "free_text_note" for f in out.residual_facts))


if __name__ == "__main__":
    unittest.main()
