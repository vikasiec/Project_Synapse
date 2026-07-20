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

    def test_identical_payloads_from_different_sources_keep_provenance(self):
        store = SemanticStore()
        ing = IngestionService(store)
        a = ing.land("sys-a", "same payload text", ["domain:a"])
        b = ing.land("sys-b", "same payload text", ["domain:b"])
        self.assertFalse(b.deduplicated)
        self.assertNotEqual(a.raw.object_id, b.raw.object_id)
        self.assertEqual(len(store.raw_objects), 2)
        self.assertEqual(b.raw.source_system, "sys-b")
        self.assertEqual(b.raw.acl_tags, ["domain:b"])


if __name__ == "__main__":
    unittest.main()
