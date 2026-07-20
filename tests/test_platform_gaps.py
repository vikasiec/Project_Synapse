"""H5/H6/H15/H16 + cache + cost + webhook coverage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synapse.action_bus import ActionBus
from synapse.claim_cache import ClaimCache
from synapse.cost_model import describe_cost_model, estimate_query_cost
from synapse.drift import DriftDetector
from synapse.materialize import Materializer
from synapse.reprocess import ReprocessService
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.security import Principal
from synapse.session import open_session
from synapse.store import SemanticStore


class TestPlatformGaps(unittest.TestCase):
    def test_reprocess(self):
        store = SemanticStore()
        CheckoutIncidentScenario(store=store).seed()
        before = len(store.facts)
        report = ReprocessService(store).run(limit=10)
        self.assertGreaterEqual(report.episodes_reprocessed, 1)
        self.assertGreaterEqual(len(store.facts), before)
        self.assertTrue(report.finished_at)

    def test_materialize_and_write(self):
        store = SemanticStore()
        CheckoutIncidentScenario(store=store).seed()
        mat = Materializer(store)
        view = mat.entity_fact_table()
        self.assertGreaterEqual(len(view.rows), 1)
        with tempfile.TemporaryDirectory() as td:
            paths = mat.write(view, td)
            self.assertTrue(Path(paths["json"]).is_file())
            self.assertTrue(Path(paths["csv"]).is_file())

    def test_materialize_respects_principal_acl(self):
        """Active_File.md row 36 (RC-08): entity_fact_table/conflict_table
        must not dump the whole store regardless of who's asking --
        `principal=None` preserves prior unrestricted behavior for
        existing full-access callers (CLI, this same test's own baseline
        call above), but a scoped principal must only see its own domain."""
        store = SemanticStore()
        CheckoutIncidentScenario(store=store).seed()
        mat = Materializer(store)

        unrestricted = mat.entity_fact_table()
        self.assertGreaterEqual(len(unrestricted.rows), 1)

        blocked = Principal.from_tags("t-blocked", ["domain:nonexistent", "clearance:l2"])
        scoped = mat.entity_fact_table(principal=blocked)
        self.assertEqual(scoped.rows, [])

        allowed = Principal.from_tags(
            "t-allowed", ["domain:sre", "clearance:l2", "channel:incidents"]
        )
        scoped_visible = mat.entity_fact_table(principal=allowed)
        self.assertEqual(len(scoped_visible.rows), len(unrestricted.rows))

        conflicts_unrestricted = mat.conflict_table()
        conflicts_blocked = mat.conflict_table(principal=blocked)
        self.assertEqual(conflicts_blocked.rows, [])
        if conflicts_unrestricted.rows:
            conflicts_allowed = mat.conflict_table(principal=allowed)
            self.assertEqual(len(conflicts_allowed.rows), len(conflicts_unrestricted.rows))

    def test_action_bus_approval(self):
        store = SemanticStore()
        bus = ActionBus(store)
        a = bus.propose(
            "create_ticket",
            {"title": "checkout down"},
            proposed_by="sre",
            risk="high",
        )
        self.assertEqual(a.status.value, "proposed")
        with self.assertRaises(ValueError):
            bus.execute(a.action_id)
        bus.approve(a.action_id, by="mgr", reason="ok")
        done = bus.execute(a.action_id)
        self.assertEqual(done.status.value, "executed_sim")
        self.assertEqual(done.execution_result["mode"], "simulated")

    def test_claim_cache_acl_bound(self):
        cache = ClaimCache(default_ttl=60)
        k1 = ClaimCache.make_key("q", principal_attrs=["a"], intent="entity_lookup")
        k2 = ClaimCache.make_key("q", principal_attrs=["b"], intent="entity_lookup")
        self.assertNotEqual(k1, k2)
        cache.put(k1, {"statement": "x"}, principal_attrs=["a"])
        self.assertIsNotNone(cache.get(k1))
        self.assertIsNone(cache.get(k2))

    def test_drift_baseline(self):
        store = SemanticStore()
        CheckoutIncidentScenario(store=store).seed()
        d = DriftDetector(store)
        d.observe_all()
        self.assertTrue(d.baselines)
        # second observe without change → no new events
        ev = d.observe_all()
        self.assertEqual(ev, [])

    def test_cost_model(self):
        m = describe_cost_model()
        self.assertIn("interactive", m["envelopes"])
        est = estimate_query_cost("deep", qps=0.1)
        self.assertIn("monthly_usd_paid_est", est)

    def test_session_orchestrator_cache_hit(self):
        session = open_session()
        try:
            CheckoutIncidentScenario(store=session.store).seed()
            p = Principal.from_tags(
                "t",
                ["domain:sre", "clearance:l2", "channel:incidents"],
            )
            a1 = session.orchestrator.ask(
                p, "What is checkout-service?", entity_name="checkout-service"
            )
            a2 = session.orchestrator.ask(
                p, "What is checkout-service?", entity_name="checkout-service"
            )
            self.assertTrue(a1.allowed)
            self.assertTrue(a2.cache_hit)
        finally:
            session.close()

    def test_cache_revision_changes_after_new_ingest(self):
        session = open_session()
        try:
            CheckoutIncidentScenario(store=session.store).seed()
            p = Principal.from_tags(
                "t-revision",
                ["domain:sre", "clearance:l2", "channel:incidents"],
            )
            a1 = session.orchestrator.ask(
                p, "What is checkout-service?", entity_name="checkout-service"
            )
            session.ingestion.land(
                "Monitor", "checkout-service status changed", ["domain:sre", "clearance:l2"]
            )
            a2 = session.orchestrator.ask(
                p, "What is checkout-service?", entity_name="checkout-service"
            )
            self.assertTrue(a1.allowed)
            self.assertFalse(a2.cache_hit)
        finally:
            session.close()

    def test_webhook_connector(self):
        from synapse.connectors.webhook_inbox import WebhookInboxConnector

        c = WebhookInboxConnector(connector_id="wh-test")
        c.enqueue("checkout-service deployed image tag v9.9.9")
        events = c.poll(None)
        self.assertEqual(len(events), 1)
        wm = c.advance(events)
        self.assertEqual(wm.position, "1")
        self.assertEqual(c.poll(wm), [])


if __name__ == "__main__":
    unittest.main()
