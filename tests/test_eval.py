import unittest

from synapse.eval_runner import evaluate_all, evaluate_pack, list_packs


class TestEval(unittest.TestCase):
    def test_checkout_pack_passes(self):
        report = evaluate_pack("checkout")
        failed = [c for c in report.checks if not c.passed]
        self.assertTrue(report.ok, msg=str([(c.name, c.detail) for c in failed]))
        self.assertGreaterEqual(report.passed, 10)

    def test_billing_pack_passes(self):
        report = evaluate_pack("billing")
        failed = [c for c in report.checks if not c.passed]
        self.assertTrue(report.ok, msg=str([(c.name, c.detail) for c in failed]))

    def test_identity_pack_passes(self):
        report = evaluate_pack("identity")
        failed = [c for c in report.checks if not c.passed]
        self.assertTrue(report.ok, msg=str([(c.name, c.detail) for c in failed]))

    def test_org_pack_passes(self):
        report = evaluate_pack("org")
        failed = [c for c in report.checks if not c.passed]
        self.assertTrue(report.ok, msg=str([(c.name, c.detail) for c in failed]))
        self.assertGreaterEqual(report.passed, 10)

    def test_suite_all_passes(self):
        suite = evaluate_all()
        self.assertTrue(suite.ok, msg=suite.to_dict())
        self.assertEqual(len(suite.reports), 4)

    def test_list_packs(self):
        packs = list_packs()
        self.assertIn("checkout", packs)
        self.assertIn("org", packs)
        self.assertIn("all", packs)


if __name__ == "__main__":
    unittest.main()
