"""as_of temporal queries + fact verifier."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from synapse.control_plane import ControlPlane
from synapse.extraction import RuleExtractor
from synapse.models import Episode, Fact, RawObject
from synapse.query import QueryService
from synapse.resolution import ConflictResolver
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.store import SemanticStore
from synapse.temporal import TemporalService
from synapse.verifier import FactVerifier


class TestAsOf(unittest.TestCase):
    def test_facts_as_of_and_timeline(self):
        store = SemanticStore()
        ex = RuleExtractor(store)
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(hours=2)

        r1 = RawObject.create(
            "GitHub-CI",
            "BUILD SUCCESSFUL: checkout-service deployed image tag v1.0.0 automatically.",
            ["domain:sre", "clearance:l2"],
            ingested_at=t0.isoformat().replace("+00:00", "Z"),
        )
        store.put_raw(r1)
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
        ts = TemporalService(store)
        mid = (t0 + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        asof = ts.facts_as_of(ent.entity_id, mid, predicate="current_version")
        vals = {str(f.object) for f in asof}
        self.assertIn("v1.0.0", vals)
        self.assertNotIn("v1.1.0", vals)

        tl = ts.timeline(ent.entity_id, predicate="current_version")
        self.assertGreaterEqual(len(tl), 2)

        cp = ControlPlane({"GitHub-CI": 0.9})
        q = QueryService(store, cp, ConflictResolver(store, cp))
        res = q.ask(
            CheckoutIncidentScenario.principal_l2(),
            entity_name="checkout-service",
            as_of=mid,
        )
        self.assertTrue(res.allowed)
        self.assertEqual(res.as_of, mid)
        self.assertIn("v1.0.0", res.claim.statement if res.claim else "")


class TestVerifier(unittest.TestCase):
    def test_version_and_revenue(self):
        v = FactVerifier()
        good = Fact.create(
            "e1",
            "current_version",
            "v2.4.1",
            confidence=0.9,
            evidence_refs=[],
            source_system="x",
            acl_tags=[],
        )
        r = v.verify_fact(good)
        self.assertTrue(r.ok)

        bad = Fact.create(
            "e1",
            "current_version",
            "not-a-version",
            confidence=0.9,
            evidence_refs=[],
            source_system="x",
            acl_tags=[],
        )
        r2 = v.verify_fact(bad)
        self.assertFalse(r2.ok)
        self.assertLess(r2.adjusted_confidence, 0.5)

        money = Fact.create(
            "e1",
            "annual_revenue",
            "950000",
            confidence=0.9,
            evidence_refs=[],
            source_system="Billing-Zuora",
            acl_tags=[],
        )
        self.assertTrue(v.verify_fact(money).ok)


if __name__ == "__main__":
    unittest.main()
