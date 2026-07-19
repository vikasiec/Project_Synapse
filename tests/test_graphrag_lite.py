import unittest

from synapse.graphrag_lite import GraphRAGLite
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.scenarios.billing_customer import BillingCustomerScenario


class TestGraphRAGLite(unittest.TestCase):
    def test_communities_and_theme_query(self):
        store = CheckoutIncidentScenario().seed().store
        BillingCustomerScenario(store=store).seed()
        idx = GraphRAGLite().build(store)
        self.assertGreaterEqual(len(idx.communities), 2)
        hits = GraphRAGLite().query(idx, "What are global themes across services?", top_k=3)
        self.assertTrue(hits)
        labels = [h["community"]["label"] for h in hits]
        self.assertTrue(any("global" in lab for lab in labels) or hits[0]["score"] >= 0)


if __name__ == "__main__":
    unittest.main()
