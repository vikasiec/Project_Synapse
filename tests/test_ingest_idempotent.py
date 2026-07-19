import unittest

from synapse.ingestion import IngestionService
from synapse.store import SemanticStore


class TestIngestIdempotent(unittest.TestCase):
    def test_duplicate_payload_dedups(self):
        store = SemanticStore()
        ing = IngestionService(store)
        a = ing.land("sys", "same payload text", ["domain:sre", "clearance:l2"])
        b = ing.land("sys", "same payload text", ["domain:sre", "clearance:l2"])
        self.assertFalse(a.deduplicated)
        self.assertTrue(b.deduplicated)
        self.assertEqual(a.raw.object_id, b.raw.object_id)
        self.assertEqual(len(store.raw_objects), 1)
        self.assertEqual(len(store.audit.by_type("ingest.dedup")), 1)
        self.assertEqual(len(store.audit.by_type("ingest.land")), 1)


if __name__ == "__main__":
    unittest.main()
