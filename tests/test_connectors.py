import tempfile
import unittest
from pathlib import Path

from synapse.connectors.file_jsonl import JsonlFileConnector
from synapse.connectors.mock_cdc import MockCdcConnector
from synapse.connectors.registry import ConnectorRegistry
from synapse.connectors.runner import ConnectorRunner
from synapse.store import SemanticStore


class TestConnectors(unittest.TestCase):
    def test_mock_cdc_poll_land_extract(self):
        store = SemanticStore()
        reg = ConnectorRegistry()
        mock = MockCdcConnector(connector_id="mock-cdc", source_system="GitHub-CI")
        reg.register(mock)
        mock.emit(
            "BUILD SUCCESSFUL: checkout-service deployed image tag v9.0.0 automatically.",
            acl_tags=["domain:sre", "clearance:l2"],
        )
        runner = ConnectorRunner(store, reg)
        result = runner.poll_one("mock-cdc")
        self.assertEqual(result.events, 1)
        self.assertEqual(result.landed, 1)
        self.assertGreaterEqual(result.extracted, 1)
        self.assertIsNotNone(store.get_entity_by_name("checkout-service"))

        # second poll empty (watermark advanced)
        r2 = runner.poll_one("mock-cdc")
        self.assertEqual(r2.events, 0)

    def test_jsonl_connector(self):
        store = SemanticStore()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                '{"payload":"Customer: AcmeZ annual_revenue: 100","source_system":"CRM-X",'
                '"acl_tags":["domain:revenue","clearance:l2"]}\n',
                encoding="utf-8",
            )
            conn = JsonlFileConnector(path=path, connector_id="jl", source_system="CRM-X")
            reg = ConnectorRegistry()
            reg.register(conn)
            runner = ConnectorRunner(store, reg)
            result = runner.poll_one("jl")
            self.assertEqual(result.events, 1)
            self.assertEqual(result.landed, 1)


if __name__ == "__main__":
    unittest.main()
