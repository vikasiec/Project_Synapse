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

    def test_hl7_upload_lands_as_segment_sources_with_structural_relationships_confirmed(self):
        # The point of hl7_semantics.auto_link_structure() firing on
        # ingest: PID/ORC/OBR/OBX are true structural facts of the
        # message, not inferred guesses -- they should already be
        # confirmed in the Catalog with zero ACCEPT calls.
        hl7_content = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSGX001|P|2.5.1\n"
            "PID|1||PX001^^^HIS^MR||Doe^Jane||19800101|F\n"
            "ORC|RE|ORDX001|||||^^^20230810083000\n"
            "OBR|1|ORDX001|LABX001|CBC^Complete Blood Count^L|||20230810080000\n"
            "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N\n"
        )
        status, body = self._post(
            "/v1/explore/ingest",
            {"filename": "sample.hl7", "content": hl7_content, "source_system": "UploadedHL7", "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["objects_landed"], 1)

        with urllib.request.urlopen(self._url("/v1/explore?principal=l2")) as resp:
            data = json.loads(resp.read().decode())
        names = {s["source_system"] for s in data["sources"]}
        for seg in ("MSH", "PID", "ORC", "OBR", "OBX"):
            self.assertIn(f"UploadedHL7::{seg}", names)
        self.assertNotIn("UploadedHL7", names)  # replaced by its sub-sources, not also listed flat

        with urllib.request.urlopen(self._url("/v1/ontology")) as resp:
            ontology = json.loads(resp.read().decode())
        pairs = {
            frozenset({r["source_a"]["source_system"], r["source_b"]["source_system"]})
            for r in ontology["relationships"]
        }
        self.assertIn(frozenset({"UploadedHL7::OBR", "UploadedHL7::OBX"}), pairs)
        self.assertIn(frozenset({"UploadedHL7::ORC", "UploadedHL7::OBR"}), pairs)
        self.assertIn(frozenset({"UploadedHL7::PID", "UploadedHL7::MSH"}), pairs)


if __name__ == "__main__":
    unittest.main()
