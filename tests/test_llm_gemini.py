import json
import unittest

from synapse.dual_path import DualPathExtractor
from synapse.ingestion import IngestionService
from synapse.llm_gemini import (
    GeminiResidualExtractor,
    RateLimitState,
    _parse_facts_json,
    create_residual_extractor,
    gemini_configured,
)
from synapse.store import SemanticStore


class TestGeminiResidual(unittest.TestCase):
    def test_parse_facts_json(self):
        raw = json.dumps(
            {
                "facts": [
                    {"predicate": "free_text_note", "object": "hello", "confidence": 0.7}
                ]
            }
        )
        items = _parse_facts_json(raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["predicate"], "free_text_note")

    def test_gemini_extractor_with_mock_http(self):
        def fake_post(url, data, headers):
            self.assertIn("generateContent", url)
            return json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "facts": [
                                                    {
                                                        "predicate": "risk_flag",
                                                        "object": "eu_rollback_risk",
                                                        "confidence": 0.8,
                                                    }
                                                ]
                                            }
                                        )
                                    }
                                ]
                            }
                        }
                    ]
                }
            )

        store = SemanticStore()
        rate = RateLimitState(max_rpm=60, max_rpd=1000)
        residual = GeminiResidualExtractor(
            api_key="test-key",
            model="gemini-test",
            rate=rate,
            http_post=fake_post,
            strict=True,
        )
        dual = DualPathExtractor(store, residual=residual)
        ing = IngestionService(store)
        landed = ing.land(
            "GitHub-CI",
            "BUILD SUCCESSFUL: checkout-service deployed image tag v1.2.3 automatically.\n"
            "Operators worried about EU region rollback risk overnight.\n",
            ["domain:sre", "clearance:l2"],
        )
        out = dual.extract(landed.episode, landed.raw)
        self.assertEqual(out.path_b_backend, "gemini_residual")
        self.assertTrue(out.path_b_used)
        self.assertTrue(any(f.predicate == "risk_flag" for f in out.residual_facts))

    def test_rate_limit_daily(self):
        rate = RateLimitState(max_rpm=100, max_rpd=1)
        rate.day_key = __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime())
        rate.day_count = 1
        ok, reason = rate.allow()
        self.assertFalse(ok)
        self.assertIn("daily", reason or "")

    def test_factory_without_key_is_heuristic(self):
        import os

        old = os.environ.pop("GEMINI_API_KEY", None)
        old2 = os.environ.pop("GOOGLE_API_KEY", None)
        old3 = os.environ.pop("SYNAPSE_LLM_BACKEND", None)
        try:
            ext = create_residual_extractor("auto")
            self.assertEqual(ext.name, "heuristic_residual")
        finally:
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old
            if old2 is not None:
                os.environ["GOOGLE_API_KEY"] = old2
            if old3 is not None:
                os.environ["SYNAPSE_LLM_BACKEND"] = old3


if __name__ == "__main__":
    unittest.main()
