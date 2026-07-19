import unittest

from synapse.connectors.mock_cdc import MockCdcConnector
from synapse.connectors.registry import ConnectorRegistry
from synapse.connectors.runner import ConnectorRunner
from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
from synapse.store import SemanticStore


class TestRunnerDualPath(unittest.TestCase):
    def test_poll_uses_dual_path_residual(self):
        store = SemanticStore()
        reg = ConnectorRegistry()
        mock = MockCdcConnector(connector_id="mock-cdc", source_system="GitHub-CI")
        reg.register(mock)
        mock.emit(
            "BUILD SUCCESSFUL: checkout-service deployed image tag v7.0.0 automatically.\n"
            "note: watch weekend freeze window\n",
            acl_tags=["domain:sre", "clearance:l2"],
        )
        dual = DualPathExtractor(store, residual=HeuristicResidualExtractor())
        runner = ConnectorRunner(store, reg, dual_path=dual)
        result = runner.poll_one("mock-cdc")
        self.assertEqual(result.extracted, 1)
        self.assertGreaterEqual(result.residual_facts, 1)
        notes = [
            f
            for f in store.facts.values()
            if f.predicate == "free_text_note"
        ]
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
