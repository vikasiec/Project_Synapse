"""Major Goal 2 (Hybrid Candidate Matching & Scoring) + VnV Layer 2."""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from synapse.api import make_handler
from synapse.models import RawObject
from synapse.session import open_session


class TestExploreAnalyze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = open_session()
        handler = make_handler(cls.session)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

        # Same real customers exist in both systems under a shared ID value
        # (cust_id / client_num) -- the realistic case a field-mapping tool
        # is meant to catch: same distribution AND meaningful value overlap.
        acl = ["domain:sre", "clearance:l2"]
        shared_ids = ("84920112", "10293847", "55512309")
        for val in shared_ids:
            cls.session.store.put_raw(
                RawObject.create(source_system="TableA", payload=f"cust_id: {val}", acl_tags=acl)
            )
        for val in shared_ids:
            cls.session.store.put_raw(
                RawObject.create(source_system="TableB", payload=f"client_num: {val}", acl_tags=acl)
            )

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.session.close()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

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

    def test_vnv_layer_2_high_scoring_candidate_with_expected_reasons(self):
        status, body = self._post(
            "/v1/explore/analyze",
            {"source_a": "TableA", "source_b": "TableB", "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["candidates"])
        top = body["candidates"][0]
        self.assertEqual(top["source_a"]["field_name"], "cust_id")
        self.assertEqual(top["source_b"]["field_name"], "client_num")
        self.assertGreater(top["similarity_score"], 0.80)
        joined_reasons = " ".join(top["match_reasons"])
        self.assertIn("Semantic Name Similarity", joined_reasons)
        self.assertIn("Value Distribution Overlap", joined_reasons)
        self.assertIn(top["status"], ("candidate", "high_confidence"))
        self.assertTrue(top["candidate_id"])

    def test_missing_source_a_returns_400(self):
        status, body = self._post("/v1/explore/analyze", {"source_b": "TableB"})
        self.assertEqual(status, 400)

    def test_omitted_source_b_is_transitive_mode_not_an_error(self):
        # Major Goal 4, task 3: omitting source_b switches to transitive
        # evaluation against the ontology registry (see
        # tests/test_ontology_relationships_api.py for the full scenario) --
        # it must not 400 just because no registry links exist yet.
        status, body = self._post("/v1/explore/analyze", {"source_a": "TableA"})
        self.assertEqual(status, 200)
        self.assertEqual(body["candidates"], [])


if __name__ == "__main__":
    unittest.main()
