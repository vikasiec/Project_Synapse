import tempfile
import unittest
from pathlib import Path

from synapse.export_import import export_store_to_file, import_store_from_file
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.store import SemanticStore


class TestExportImport(unittest.TestCase):
    def test_roundtrip(self):
        scenario = CheckoutIncidentScenario()
        bundle = scenario.seed()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.json"
            export_store_to_file(bundle.store, path)
            loaded = import_store_from_file(path)
            self.assertEqual(len(loaded.raw_objects), 3)
            self.assertIsNotNone(loaded.get_entity_by_name("checkout-service"))
            self.assertEqual(len(loaded.facts), len(bundle.store.facts))


if __name__ == "__main__":
    unittest.main()
