import os
import unittest

from synapse.graph_memory import (
    LocalGraphitiStub,
    OptionalGraphitiAdapter,
    create_graph_adapter,
    graphiti_available,
)
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario


class TestGraphMemory(unittest.TestCase):
    def test_local_stub_builds_nodes_and_edges(self):
        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()
        g = LocalGraphitiStub()
        snap = g.sync_from_store(bundle.store)
        self.assertEqual(snap.backend, "local_graphiti_stub")
        self.assertGreaterEqual(len(snap.nodes), 1)
        self.assertGreaterEqual(len(snap.edges), 1)
        stats = g.stats()
        self.assertGreaterEqual(stats["current_edges"], 1)

        ent = bundle.store.get_entity_by_name("checkout-service")
        nb = g.neighborhood(ent.entity_id, depth=1)
        self.assertTrue(nb["nodes"])
        self.assertTrue(nb["edges"])

    def test_optional_adapter_degrades_without_graphiti(self):
        os.environ.pop("GRAPHITI_ENABLED", None)
        g = OptionalGraphitiAdapter()
        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()
        snap = g.sync_from_store(bundle.store)
        self.assertIn("optional_graphiti", snap.backend)
        self.assertGreaterEqual(len(snap.nodes), 1)
        st = g.stats()
        self.assertIn("local_mirror", st["backend"])

    def test_factory_local(self):
        g = create_graph_adapter("local")
        self.assertEqual(g.name, "local_graphiti_stub")

    def test_graphiti_available_diag(self):
        info = graphiti_available()
        self.assertIn("importable", info)


if __name__ == "__main__":
    unittest.main()

