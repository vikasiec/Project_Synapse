"""Budgeted multi-engine orchestrator + ontology + org corpus."""

from __future__ import annotations

import unittest

from synapse.budget import BudgetClass, BudgetLedger
from synapse.ontology import OntologyRegistry
from synapse.scenarios.org_discrepancy import OrgDiscrepancyCorpus
from synapse.security import Principal
from synapse.session import open_session


class TestBudget(unittest.TestCase):
    def test_engine_cap_interactive(self):
        b = BudgetLedger.open(BudgetClass.INTERACTIVE)
        self.assertTrue(b.allow_engine("a"))
        self.assertFalse(b.allow_engine("b"))
        self.assertTrue(b.exhausted)


class TestOntology(unittest.TestCase):
    def test_layers_and_promote(self):
        ont = OntologyRegistry.default()
        self.assertIn("Person", ont.types)
        self.assertIn("InfraService", ont.types)
        t = ont.register_l2(
            "TeamWidget", parent="Service", domain="infra_ops", predicates=["widget_id"]
        )
        self.assertEqual(t.layer, "L2")
        self.assertTrue(ont.promote("TeamWidget"))
        self.assertEqual(ont.types["TeamWidget"].layer, "L1")


class TestOrgOrchestrator(unittest.TestCase):
    def test_org_corpus_and_ask(self):
        session = open_session()
        try:
            corpus = OrgDiscrepancyCorpus(store=session.store).seed()
            self.assertGreaterEqual(len(corpus.entity_names), 3)
            self.assertGreaterEqual(corpus.extra_ingested, 3)

            principal = Principal.from_tags(
                "t-orch",
                [
                    "domain:sre",
                    "domain:revenue",
                    "domain:identity",
                    "domain:support",
                    "clearance:l2",
                    "channel:incidents",
                    "channel:support",
                    "channel:itsm",
                ],
            )
            ans = session.orchestrator.ask(
                principal,
                "What is checkout-service status and global failure modes?",
                entity_name="checkout-service",
                budget_class="deep",
            )
            self.assertTrue(ans.allowed)
            self.assertIn("semantic_query", ans.engine_hits)
            self.assertIn("graphrag", ans.engine_hits)
            self.assertTrue(ans.statement)
            self.assertIsNotNone(ans.claim)
            self.assertGreater(ans.confidence, 0)

            themes = session.orchestrator.ask(
                principal,
                "What are global themes across the org?",
                intent="themes",
            )
            self.assertIn("graphrag", themes.engine_hits)

            doc = session.orchestrator.ask(
                principal,
                "section about CrashLoopBackOff failure",
                intent="document",
            )
            self.assertIn("pageindex", doc.engine_hits)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
