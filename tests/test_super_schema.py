"""Super schema: combining 2+ workspaces -- union their sources +
already-confirmed relationships, discover NEW candidate relationships
between sources that live in different workspaces, and flag conflicts
where two workspaces define the same canonical field with a different
data_type."""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from synapse.api import make_handler
from synapse.session import open_session


class TestSuperSchema(unittest.TestCase):
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

    def _make_workspace(self, name: str) -> str:
        status, body = self._post("/v1/workspaces", {"name": name})
        self.assertEqual(status, 200)
        return body["workspace_id"]

    def test_cross_workspace_candidate_discovered_not_auto_confirmed(self):
        ws_a = self._make_workspace("SS Workspace A")
        ws_b = self._make_workspace("SS Workspace B")
        shared_ids = ("84920112", "10293847", "55512309")
        for val in shared_ids:
            self._post(
                "/v1/explore/ingest",
                {
                    "filename": "a.csv",
                    "content": f"cust_id\n{val}\n",
                    "source_system": "SSTableA",
                    "workspace_id": ws_a,
                    "principal": "l2",
                },
            )
        for val in shared_ids:
            self._post(
                "/v1/explore/ingest",
                {
                    "filename": "b.csv",
                    "content": f"client_num\n{val}\n",
                    "source_system": "SSTableB",
                    "workspace_id": ws_b,
                    "principal": "l2",
                },
            )

        status, result = self._post("/v1/super-schema", {"workspace_ids": [ws_a, ws_b], "principal": "l2"})
        self.assertEqual(status, 200)
        names = {s["source_system"] for s in result["sources"]}
        self.assertIn("SSTableA", names)
        self.assertIn("SSTableB", names)

        pairs = {
            frozenset({c["source_a"]["source_system"], c["source_b"]["source_system"]})
            for c in result["cross_workspace_candidates"]
        }
        self.assertIn(frozenset({"SSTableA", "SSTableB"}), pairs)

        # Not auto-confirmed -- no relationship exists yet for this pair.
        with urllib.request.urlopen(self._url("/v1/ontology")) as resp:
            ontology = json.loads(resp.read().decode())
        confirmed_pairs = {
            frozenset({r["source_a"]["source_system"], r["source_b"]["source_system"]})
            for r in ontology["relationships"]
        }
        self.assertNotIn(frozenset({"SSTableA", "SSTableB"}), confirmed_pairs)

    def test_conflict_flagged_for_mismatched_data_type_same_canonical_field(self):
        ws_a = self._make_workspace("SS Conflict A")
        ws_b = self._make_workspace("SS Conflict B")
        # Both canonicalize to the same token ("customer identifier") but
        # one is numeric, the other alphanumeric -- a real definitional
        # disagreement between the two workspaces.
        self._post(
            "/v1/explore/ingest",
            {
                "filename": "a.csv",
                "content": "cust_id\n12345678\n",
                "source_system": "ConflictA",
                "workspace_id": ws_a,
                "principal": "l2",
            },
        )
        self._post(
            "/v1/explore/ingest",
            {
                "filename": "b.csv",
                "content": "cust_id\nABC-XYZ-NOTNUM\n",
                "source_system": "ConflictB",
                "workspace_id": ws_b,
                "principal": "l2",
            },
        )

        status, result = self._post("/v1/super-schema", {"workspace_ids": [ws_a, ws_b], "principal": "l2"})
        self.assertEqual(status, 200)
        canon_fields = {c["canonical_field"] for c in result["conflicts"]}
        self.assertTrue(any("identifier" in c for c in canon_fields))

    def test_requires_at_least_two_workspaces(self):
        ws_a = self._make_workspace("SS Solo")
        status, body = self._post("/v1/super-schema", {"workspace_ids": [ws_a], "principal": "l2"})
        self.assertEqual(status, 400)

    def test_unknown_workspace_id_is_400(self):
        ws_a = self._make_workspace("SS Known")
        status, body = self._post("/v1/super-schema", {"workspace_ids": [ws_a, "not-a-real-id"], "principal": "l2"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
