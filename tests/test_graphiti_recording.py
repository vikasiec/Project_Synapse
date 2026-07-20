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

    def test_pushed_episodes_carry_acl_derived_group_id(self):
        """Active_File.md row 31 (RC-03): every pushed episode must carry a
        group_id derived from its own ACL tags, not the domain-only
        `source_description` that carried no ACL/tenant info at all before
        this row."""
        from synapse.graph_memory import derive_group_id
        from synapse.ingestion import IngestionService
        from synapse.store import SemanticStore

        store = SemanticStore()
        ing = IngestionService(store)
        r1 = ing.land("Source-A", "payload one", ["domain:sre", "clearance:l2"])
        r2 = ing.land("Source-B", "payload two", ["domain:banking", "clearance:l1"])

        client = RecordingGraphitiClient()
        adapter = OptionalGraphitiAdapter(client=client)
        adapter.sync_from_store(store)

        self.assertEqual(len(client.episodes), 2)
        group_ids = {ep.meta.get("group_id") for ep in client.episodes}
        self.assertEqual(
            group_ids,
            {
                derive_group_id(["domain:sre", "clearance:l2"]),
                derive_group_id(["domain:banking", "clearance:l1"]),
            },
        )
        # Genuinely different ACL sets must not collide onto one group_id.
        self.assertEqual(len(group_ids), 2)

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
