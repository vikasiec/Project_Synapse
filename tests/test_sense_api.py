import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from synapse.api import make_handler
from synapse.session import open_session


class TestSenseAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = open_session()
        handler = make_handler(cls.session)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.session.close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path: str):
        with urllib.request.urlopen(self._url(path)) as resp:
            return resp.status, json.loads(resp.read().decode())

    def _post(self, path: str, body: dict):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self._url(path),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_summary_empty_store(self):
        status, body = self._get("/v1/sense/summary")
        self.assertEqual(status, 200)
        for key in ("raw_objects", "episodes", "entities", "facts", "conflicts_open"):
            self.assertIn(key, body)

    def test_raw_episodes_facts_after_seed(self):
        status, body = self._post("/v1/seed", {"scenario": "checkout"})
        self.assertEqual(status, 200)

        status, raw = self._get("/v1/raw?limit=10")
        self.assertEqual(status, 200)
        self.assertGreater(raw["count"], 0)
        self.assertTrue(raw["items"])
        first = raw["items"][0]
        for key in ("object_id", "source", "received_at", "preview"):
            self.assertIn(key, first)

        status, eps = self._get("/v1/episodes?limit=10")
        self.assertEqual(status, 200)
        self.assertGreater(eps["count"], 0)

        status, facts = self._get("/v1/facts?limit=10")
        self.assertEqual(status, 200)
        self.assertGreater(facts["count"], 0)
        f0 = facts["items"][0]
        for key in ("fact_id", "entity_id", "predicate", "value", "source", "confidence", "path"):
            self.assertIn(key, f0)
        self.assertIn(f0["path"], ("rules", "residual", "other"))

        status, summary = self._get("/v1/sense/summary")
        self.assertEqual(status, 200)
        self.assertGreater(summary["raw_objects"], 0)
        self.assertGreater(summary["facts"], 0)

    def test_sense_drop_json_unknown_shape_is_honest(self):
        status, body = self._post(
            "/v1/sense/drop",
            {"kind": "json", "payload": "some free-form text with no key: value pattern"},
        )
        self.assertEqual(status, 200)
        self.assertIn("object_id", body)
        self.assertIsNone(body["entity"])

        status, raw = self._get("/v1/raw?limit=50")
        self.assertEqual(status, 200)
        self.assertTrue(any(r["object_id"] == body["object_id"] for r in raw["items"]))

    def test_sense_drop_missing_payload_400(self):
        status, body = self._post("/v1/sense/drop", {"kind": "json"})
        self.assertEqual(status, 400)

    def test_sense_drop_bad_path_404(self):
        status, body = self._post(
            "/v1/sense/drop", {"kind": "csv", "path": ".data/does_not_exist.csv"}
        )
        self.assertEqual(status, 404)

    def test_sense_drop_csv_honors_acl_tags(self):
        """`/v1/sense/drop` accepted an `acl_tags` body param for kind=csv
        but never actually passed it to the connector -- every CSV drop
        silently landed as domain:sre regardless of what the caller asked
        for. Land a row tagged domain:clinical and confirm it's visible
        to a domain:clinical-scoped principal but not domain:revenue."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "acl_check.csv"
            path.write_text("widget_id,widget_name\nW-1,Sprocket\n", encoding="utf-8")
            status, body = self._post(
                "/v1/sense/drop",
                {
                    "kind": "csv",
                    "path": str(path),
                    "connector_id": "acl-check",
                    "acl_tags": ["domain:clinical", "clearance:l2"],
                },
            )
            self.assertEqual(status, 200)

            status, raw = self._get(
                "/v1/raw?limit=500&principal=domain:clinical,clearance:l2"
            )
            self.assertEqual(status, 200)
            self.assertTrue(any(r["source"] == "Spreadsheet" for r in raw["items"]))

    def test_sense_summary_dynamic_story_reflects_loaded_domain(self):
        status, body = self._post(
            "/v1/sense/drop",
            {
                "kind": "json",
                "payload": "widget_id: W-9\nwidget_name: Sprocket\nwidget_status: active\n",
                "source_system": "WidgetSource",
                "acl_tags": ["domain:widgets", "clearance:l2"],
            },
        )
        self.assertEqual(status, 200)

        status, summary = self._get("/v1/sense/summary")
        self.assertEqual(status, 200)
        self.assertIsNotNone(summary.get("dynamic_story"))
        self.assertIn("title", summary["dynamic_story"])
        self.assertIn("subtitle", summary["dynamic_story"])


if __name__ == "__main__":
    unittest.main()
