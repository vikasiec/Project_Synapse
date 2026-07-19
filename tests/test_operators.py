import unittest

from synapse.operators import DropEmpty, OperatorPipeline, RedactEmails, RedactSecretsLite


class TestOperators(unittest.TestCase):
    def test_default_pipeline_redacts_and_tokens(self):
        pipe = OperatorPipeline()
        ctx = pipe.run("  Hello user@example.com api_key=sk-abcdefghijklmnop  ")
        self.assertFalse(ctx.dropped)
        self.assertIn("[REDACTED_EMAIL]", ctx.text)
        self.assertIn("[REDACTED]", ctx.text)
        self.assertGreaterEqual(ctx.meta.get("token_estimate", 0), 1)
        self.assertIn("strip_whitespace", ctx.meta.get("ops", []))

    def test_drop_empty(self):
        pipe = OperatorPipeline(ops=[DropEmpty()])
        ctx = pipe.run("   \n  ")
        self.assertTrue(ctx.dropped)


if __name__ == "__main__":
    unittest.main()
