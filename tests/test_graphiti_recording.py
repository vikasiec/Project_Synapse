import unittest

from synapse.graph_memory import OptionalGraphitiAdapter
from synapse.graphiti_client import RecordingGraphitiClient
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario


class TestGraphitiRecording(unittest.TestCase):
    def test_injected_client_receives_episodes(self):
        client = RecordingGraphitiClient()
        adapter = OptionalGraphitiAdapter(client=client)
        self.assertEqual(adapter._mode, "client_injected")

        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()
        snap = adapter.sync_from_store(bundle.store)
        self.assertIn("optional_graphiti", snap.backend)
        self.assertEqual(len(client.episodes), len(bundle.store.episodes))
        self.assertTrue(all(ep.body for ep in client.episodes))

        # idempotent: second sync does not re-push
        adapter.sync_from_store(bundle.store)
        self.assertEqual(len(client.episodes), len(bundle.store.episodes))

    def test_push_failure_falls_back(self):
        client = RecordingGraphitiClient()
        client.fail_next = True
        adapter = OptionalGraphitiAdapter(client=client)
        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()
        snap = adapter.sync_from_store(bundle.store)
        # local graph still built
        self.assertGreaterEqual(len(snap.nodes), 1)
        self.assertIsNotNone(adapter.stats().get("last_error"))


if __name__ == "__main__":
    unittest.main()
