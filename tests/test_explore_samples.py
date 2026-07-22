"""GET /v1/explore/samples -- bounded, on-demand sample values for a
field, to support human curation review (node/edge double-click)."""

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


class TestExploreSamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = open_session()
        handler = make_handler(cls.session)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

        acl = ["domain:sre", "clearance:l2"]
        for val in ("84920112", "10293847", "55512309", "84920112"):  # one dup
            cls.session.store.put_raw(
                RawObject.create(source_system="TableA", payload=f"cust_id: {val}", acl_tags=acl)
            )

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.session.close()

    def _get(self, path: str):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_returns_distinct_bounded_samples(self):
        status, body = self._get("/v1/explore/samples?source=TableA&field=cust_id&principal=l2&limit=2")
        self.assertEqual(status, 200)
        self.assertLessEqual(len(body["values"]), 2)
        self.assertEqual(len(body["values"]), len(set(body["values"])))

    def test_missing_field_is_400(self):
        status, body = self._get("/v1/explore/samples?source=TableA&principal=l2")
        self.assertEqual(status, 400)

    def test_acl_hides_samples_from_unrelated_domain(self):
        status, body = self._get(
            "/v1/explore/samples?source=TableA&field=cust_id&principal=domain:banking,clearance:l2"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["values"], [])


if __name__ == "__main__":
    unittest.main()
