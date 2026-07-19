import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from synapse.api import make_handler
from synapse.session import open_session


class TestAPI(unittest.TestCase):
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

    def test_health_seed_query_pin(self):
        status, body = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

        status, body = self._post("/v1/seed", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["raw_objects"], 3)

        status, body = self._post(
            "/v1/query",
            {"entity": "checkout-service", "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["allowed"])
        conflicts = body["conflicts"]
        self.assertTrue(conflicts)
        cid = conflicts[0]["conflict"]["conflict_id"]
        fact_id = conflicts[0]["ranked_facts"][0]["fact_id"]

        status, body = self._post(
            f"/v1/conflicts/{cid}/pin",
            {
                "chosen_fact_id": fact_id,
                "adjudicator": "api-test",
                "reason": "unit test pin",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "resolved")

        status, denied = self._post(
            "/v1/query",
            {"entity": "checkout-service", "principal": "l1"},
        )
        self.assertEqual(status, 403)
        self.assertFalse(denied["allowed"])


if __name__ == "__main__":
    unittest.main()
