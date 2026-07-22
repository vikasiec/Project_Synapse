"""Schema View: GET/POST /v1/schema/layout."""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from synapse.api import make_handler
from synapse.session import open_session


class TestSchemaLayoutApi(unittest.TestCase):
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

    def test_empty_layout_returns_empty_list(self):
        status, body = self._get("/v1/schema/layout")
        self.assertEqual(status, 200)
        self.assertEqual(body["positions"], [])

    def test_save_and_read_back_position(self):
        status, body = self._post(
            "/v1/schema/layout", {"source_system": "TableA", "x": 10, "y": 20, "principal": "l2"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["source_system"], "TableA")
        self.assertEqual(body["x"], 10.0)
        self.assertEqual(body["y"], 20.0)

        status, body = self._get("/v1/schema/layout")
        self.assertEqual(status, 200)
        entries = {p["source_system"]: p for p in body["positions"]}
        self.assertIn("TableA", entries)
        self.assertEqual(entries["TableA"]["x"], 10.0)

    def test_missing_fields_is_400(self):
        status, body = self._post("/v1/schema/layout", {"source_system": "TableA", "principal": "l2"})
        self.assertEqual(status, 400)

    def test_non_operator_principal_is_403(self):
        status, body = self._post(
            "/v1/schema/layout",
            {"source_system": "TableA", "x": 1, "y": 2, "principal": {"id": "anon", "attributes": []}},
        )
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
