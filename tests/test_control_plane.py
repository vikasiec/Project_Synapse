import unittest
from datetime import datetime, timedelta, timezone

from synapse.control_plane import ControlPlane, RouteTarget


class TestControlPlane(unittest.TestCase):
    def test_idf_and_routes(self):
        cp = ControlPlane({"sys": 0.9})
        self.assertEqual(cp.calculate_idf(8, 24), 8 / 24)
        self.assertEqual(cp.route(20, 20).route, RouteTarget.LOCAL_CROSS_ENCODER)
        self.assertEqual(cp.route(8, 24).route, RouteTarget.HYBRID_RETRIEVAL)
        self.assertEqual(cp.route(1, 100).route, RouteTarget.PAGEINDEX_LEAF)
        self.assertEqual(cp.route(1, 10, intent="themes").route, RouteTarget.GRAPHRAG_COMMUNITY)

    def test_validity_weight_authority_and_decay(self):
        cp = ControlPlane({"high": 0.95, "low": 0.5}, lambda_decay=0.01)
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        recent = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        old = (now - timedelta(minutes=200)).isoformat().replace("+00:00", "Z")

        w_high = cp.validity_weight("high", 0.05, recent, now=now)
        w_low = cp.validity_weight("low", 0.05, recent, now=now)
        w_old = cp.validity_weight("high", 0.05, old, now=now)

        self.assertGreater(w_high, w_low)
        self.assertGreater(w_high, w_old)


if __name__ == "__main__":
    unittest.main()
