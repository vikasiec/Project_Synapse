"""SaaS stub connectors + orchestrator early-exit / as_of."""

from __future__ import annotations

import unittest

from synapse.connectors.saas_stub import (
    CrmStubConnector,
    MetricsStubConnector,
    SlackStubConnector,
)
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.security import Principal
from synapse.session import open_session


class TestSaasStubs(unittest.TestCase):
    def test_crm_poll_once(self):
        c = CrmStubConnector()
        ev = c.poll(None)
        self.assertGreaterEqual(len(ev), 1)
        wm = c.advance(ev)
        self.assertEqual(c.poll(wm), [])

    def test_slack_and_metrics(self):
        s = SlackStubConnector()
        m = MetricsStubConnector()
        self.assertTrue(s.poll(None))
        self.assertTrue(m.poll(None))

    def test_session_has_stubs_and_poll(self):
        session = open_session()
        try:
            ids = {c["connector_id"] for c in session.connectors.list()}
            self.assertIn("crm-stub", ids)
            self.assertIn("slack-stub", ids)
            self.assertIn("metrics-stub", ids)
            pr = session.connector_runner.poll_one("crm-stub")
            self.assertGreaterEqual(pr.events, 1)
        finally:
            session.close()

    def test_orchestrator_early_exit_path(self):
        session = open_session()
        try:
            # High-confidence pin path: seed + pin then interactive ask
            CheckoutIncidentScenario(store=session.store).seed()
            principal = Principal.from_tags(
                "t",
                ["domain:sre", "clearance:l2", "channel:incidents"],
            )
            # Force hybrid themes would not early exit; entity_lookup interactive may
            ans = session.orchestrator.ask(
                principal,
                "What is checkout-service?",
                entity_name="checkout-service",
                intent="entity_lookup",
                budget_class="interactive",
                early_exit_confidence=0.99,  # unlikely to hit with open conflicts
            )
            self.assertTrue(ans.allowed)
            self.assertIn("semantic_query", ans.engine_hits)
            # With open conflicts, early_exit should NOT fire
            self.assertNotIn("early_exit", ans.engine_hits)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
