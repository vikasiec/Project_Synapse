"""H8: ontology load-bearing at extract + conflict ranking."""

from __future__ import annotations

import unittest

from synapse.control_plane import ControlPlane
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.resolution import ConflictResolver
from synapse.scenarios.billing_customer import BillingCustomerScenario
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.session import open_session
from synapse.store import SemanticStore


class TestOntologyLoadBearing(unittest.TestCase):
    def test_govern_extract_domain_l1(self):
        ont = OntologyRegistry.default()
        g = ont.govern_extract("Service", domain="infra_ops")
        self.assertEqual(g.storage_type, "Service")
        self.assertEqual(g.ontology_type, "InfraService")
        self.assertEqual(g.ontology_layer, "L1")

        g2 = ont.govern_extract("Customer", domain="revenue")
        self.assertEqual(g2.ontology_type, "BillingAccount")

        g3 = ont.govern_extract("Person", domain="identity")
        self.assertEqual(g3.ontology_type, "IdentityPrincipal")

    def test_extract_tags_ontology_on_entity(self):
        store = SemanticStore()
        ont = OntologyRegistry.default()
        ex = RuleExtractor(store, ontology=ont)
        ing = IngestionService(store, domain="infra_ops")
        r = ing.land(
            "K8s-Cluster-Alpha",
            "ALERT: checkout-service-pod state CrashLoopBackOff pinned v2.4.0.",
            ["domain:sre", "clearance:l2"],
        )
        res = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(res)
        self.assertEqual(res.entity.entity_type, "Service")
        self.assertEqual(res.entity.ontology_type, "InfraService")
        self.assertEqual(res.entity.ontology_layer, "L1")

    def test_conflict_ranking_ontology_boost(self):
        store = SemanticStore()
        BillingCustomerScenario(store=store).seed()
        ent = store.get_entity_by_name("Acme Corp")
        self.assertIsNotNone(ent)
        # Ensure ontology tag (scenario may use plain ER without domain)
        if not ent.ontology_type:
            ent.ontology_type = "BillingAccount"
            ent.ontology_layer = "L1"
            store.put_entity(ent)

        auth = {
            "CRM-Salesforce": 0.75,
            "Billing-Zuora": 0.75,  # equal Ar — boost should tip Billing
            "Support-Zendesk": 0.6,
        }
        cp = ControlPlane(auth)
        ont = OntologyRegistry.default()
        views = ConflictResolver(store, cp, ontology=ont).detect_scalar_conflicts(
            ent.entity_id
        )
        rev = next(v for v in views if v.conflict.predicate == "annual_revenue")
        preferred = rev.preferred.fact.source_system if rev.preferred else None
        self.assertEqual(preferred, "Billing-Zuora")
        # Ontology boost present on ranked facts
        boosts = {r.fact.source_system: r.ontology_boost for r in rev.ranked}
        self.assertGreater(boosts.get("Billing-Zuora", 0), boosts.get("CRM-Salesforce", 0))

    def test_session_checkout_ontology(self):
        session = open_session()
        try:
            CheckoutIncidentScenario(store=session.store).seed()
            # Re-extract isn't automatic on scenario; scenario uses own extractor
            # Session-built entities from seed may lack tags if scenario doesn't use ontology
            # Seed uses RuleExtractor without ontology — re-land one payload through session
            session.ingestion.domain = "infra_ops"
            r = session.ingestion.land(
                "GitHub-CI",
                "BUILD SUCCESSFUL: payments-service deployed image tag v3.0.0 automatically.",
                ["domain:sre", "clearance:l2"],
            )
            out = session.dual_path.extract(r.episode, r.raw)
            ent = session.store.get_entity_by_name("payments-service")
            self.assertIsNotNone(ent)
            self.assertEqual(ent.ontology_type, "InfraService")
            self.assertTrue(out.entity_name)
        finally:
            session.close()

    def test_predicate_source_boost_map(self):
        ont = OntologyRegistry.default()
        self.assertGreater(
            ont.predicate_source_boost("account_status", "IdP-Okta"),
            ont.predicate_source_boost("account_status", "HR-Workday"),
        )


if __name__ == "__main__":
    unittest.main()
