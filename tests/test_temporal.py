import unittest
from datetime import datetime, timedelta, timezone

from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.store import SemanticStore
from synapse.temporal import TemporalService


class TestTemporal(unittest.TestCase):
    def test_same_source_supersession(self):
        store = SemanticStore()
        ing = IngestionService(store)
        ex = RuleExtractor(store)
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(hours=1)

        # Manually land with controlled timestamps via raw create
        from synapse.models import RawObject

        r1 = RawObject.create(
            "GitHub-CI",
            "BUILD SUCCESSFUL: checkout-service deployed image tag v1.0.0 automatically.",
            ["domain:sre", "clearance:l2"],
            ingested_at=t0.isoformat().replace("+00:00", "Z"),
        )
        store.put_raw(r1)
        from synapse.models import Episode

        ep1 = Episode.from_raw(r1, domain="infra_ops")
        store.put_episode(ep1)
        ex.extract_from_episode(ep1, r1)

        r2 = RawObject.create(
            "GitHub-CI",
            "BUILD SUCCESSFUL: checkout-service deployed image tag v1.1.0 automatically.",
            ["domain:sre", "clearance:l2"],
            ingested_at=t1.isoformat().replace("+00:00", "Z"),
        )
        store.put_raw(r2)
        ep2 = Episode.from_raw(r2, domain="infra_ops")
        store.put_episode(ep2)
        ex.extract_from_episode(ep2, r2)

        ent = store.get_entity_by_name("checkout-service")
        versions = store.facts_for_entity(ent.entity_id, "current_version")
        current = [f for f in versions if f.valid_to is None]
        closed = [f for f in versions if f.valid_to is not None]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].object, "v1.1.0")
        self.assertGreaterEqual(len(closed), 1)

        # No open conflict for same-source supersession alone
        from synapse.control_plane import ControlPlane
        from synapse.resolution import ConflictResolver

        views = ConflictResolver(store, ControlPlane({"GitHub-CI": 0.9})).detect_scalar_conflicts(
            ent.entity_id
        )
        version_views = [v for v in views if v.conflict.predicate == "current_version"]
        self.assertEqual(len(version_views), 0)


if __name__ == "__main__":
    unittest.main()
