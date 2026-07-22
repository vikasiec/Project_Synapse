"""Explore journey step 1 (real ingestion): POST /v1/explore/ingest.

Lets the browser hand over a picked file's raw text content (no server
filesystem path required, unlike /v1/sense/drop's csv|jsonl "kind") so a
user can select files/folders in the UI and have SYNAPSE profile/score
them directly, rather than only being able to pick from sources some
prior demo/connector already landed.
"""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from synapse.api import make_handler
from synapse.session import open_session


class TestExploreIngest(unittest.TestCase):
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

    def _post(self, path: str, body: dict):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self._url(path), data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_csv_upload_lands_one_raw_object_per_row(self):
        csv_content = "cust_id,name\n84920112,Alice\n10293847,Bob\n55512309,Carol\n"
        status, body = self._post(
            "/v1/explore/ingest",
            {"filename": "customers.csv", "content": csv_content, "source_system": "UploadedCustomers", "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["objects_landed"], 3)
        self.assertEqual(body["source_system"], "UploadedCustomers")

        # Confirm it's actually profileable afterward (the point of landing it).
        status, profile = self._post(
            "/v1/explore/analyze", {"source_a": "UploadedCustomers", "source_b": "UploadedCustomers", "principal": "l2"}
        )
        self.assertEqual(status, 200)

    def test_json_upload_lands_one_raw_object(self):
        payload = json.dumps({"resourceType": "Patient", "identifier": [{"value": "999"}]})
        status, body = self._post(
            "/v1/explore/ingest",
            {"filename": "patient.json", "content": payload, "source_system": "UploadedFHIR", "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["objects_landed"], 1)

    def test_missing_content_is_400(self):
        status, body = self._post("/v1/explore/ingest", {"filename": "x.csv", "principal": "l2"})
        self.assertEqual(status, 400)

    def test_landed_source_appears_in_explore_sources_list(self):
        self._post(
            "/v1/explore/ingest",
            {"filename": "orders.csv", "content": "order_id\n1\n2\n", "source_system": "UploadedOrders", "principal": "l2"},
        )
        with urllib.request.urlopen(self._url("/v1/explore?principal=l2")) as resp:
            data = json.loads(resp.read().decode())
        names = [s["source_system"] for s in data["sources"]]
        self.assertIn("UploadedOrders", names)


if __name__ == "__main__":
    unittest.main()
