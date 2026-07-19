"""Tests for blueprint package adapters (real prefer + lite fallback)."""

from __future__ import annotations

import unittest

from synapse.integrations.availability import engine_availability
from synapse.integrations.data_juicer_adapter import create_prep_adapter
from synapse.integrations.graphrag_adapter import create_graphrag_adapter
from synapse.integrations.pageindex_adapter import create_pageindex_adapter
from synapse.scenarios.billing_customer import BillingCustomerScenario
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.session import open_session


class TestIntegrations(unittest.TestCase):
    def test_engine_availability_shape(self):
        av = engine_availability()
        for key in ("graphiti", "graphrag", "data_juicer", "pageindex"):
            self.assertIn(key, av)
            self.assertIn("installed", av[key])
            self.assertIn("importable", av[key])
            self.assertIn("role", av[key])
            self.assertIn("repo", av[key])
        self.assertIn("all_installed", av)
        self.assertIn("all_importable", av)

    def test_data_juicer_adapter_runs(self):
        prep = create_prep_adapter()
        ctx = prep.run("  Hello user@example.com api_key=sk-abcdefghijklmnop  ")
        self.assertFalse(ctx.dropped)
        self.assertIn("[REDACTED_EMAIL]", ctx.text)
        desc = prep.describe()
        self.assertIn("backend", desc)
        self.assertTrue(desc["lite_operators"])

    def test_graphrag_adapter_communities(self):
        store = CheckoutIncidentScenario().seed().store
        BillingCustomerScenario(store=store).seed()
        gr = create_graphrag_adapter()
        idx = gr.build(store)
        self.assertGreaterEqual(len(idx.communities), 2)
        self.assertTrue(idx.backend)
        hits = gr.query(idx, "What are global themes?", top_k=2)
        self.assertTrue(hits)
        self.assertIn("engine_backend", hits[0])

    def test_pageindex_adapter_route(self):
        text = """# Overview
Intro.

## Failure Modes
CrashLoopBackOff after bad canary.
"""
        pi = create_pageindex_adapter()
        tree = pi.build(text, title="runbook")
        self.assertTrue(tree.backend)
        hits = pi.route(tree, "CrashLoopBackOff failure", top_k=2)
        self.assertTrue(hits)
        blob = (
            hits[0]["node"]["title"].lower()
            + " "
            + hits[0]["node"].get("preview", "").lower()
        )
        self.assertIn("failure", blob)

    def test_session_engines_describe(self):
        session = open_session()
        try:
            CheckoutIncidentScenario(store=session.store).seed()
            session.engines.rebuild_communities()
            session.engines.index_document(
                "# A\nHello\n## B\nWorld failure modes\n", title="t"
            )
            desc = session.engines.describe()
            self.assertIn("blueprint_engines", desc)
            self.assertIn("graphrag", desc)
            self.assertIn("pageindex", desc)
            self.assertIn("data_juicer", desc)
            self.assertIn("graphiti", desc)
            themes = session.engines.route_query(
                "global themes", intent="themes"
            )
            self.assertEqual(themes["intent"], "global_themes")
            self.assertTrue(themes["hits"])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
