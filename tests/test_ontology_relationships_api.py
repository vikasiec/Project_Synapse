"""Major Goal 4 (Semantic Persistence & Auto-Classification) + VnV Layers 3 & 4."""

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


class TestOntologyRelationshipsApi(unittest.TestCase):
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

    def _seed_and_analyze(self):
        # Unique source names per test method -- the class shares one
        # session/server across all tests (setUpClass), and REJECT/ACCEPT
        # decisions now persist across analyze() calls within that shared
        # session (that's the point of F-026/F-029's fix), so reusing
        # "TableA"/"TableB" literally across tests would leak state between
        # otherwise-independent tests.
        suffix = self._testMethodName
        source_a, source_b = f"TableA_{suffix}", f"TableB_{suffix}"
        acl = ["domain:sre", "clearance:l2"]
        shared_ids = ("84920112", "10293847", "55512309")
        for val in shared_ids:
            self.session.store.put_raw(
                RawObject.create(source_system=source_a, payload=f"cust_id: {val}", acl_tags=acl)
            )
        for val in shared_ids:
            self.session.store.put_raw(
                RawObject.create(source_system=source_b, payload=f"client_num: {val}", acl_tags=acl)
            )
        status, body = self._post(
            "/v1/explore/analyze", {"source_a": source_a, "source_b": source_b, "principal": "l2"}
        )
        self.assertEqual(status, 200)
        return body["candidates"][0]

    def test_vnv_layer_3_accept_payload_shape_and_layer_4_registry_readback(self):
        top = self._seed_and_analyze()
        candidate_id = top["candidate_id"]

        # VnV Layer 3: exact payload shape {"action": "ACCEPT", "candidate_id": "<uuid>"}
        status, edge = self._post(
            "/v1/ontology/relationships",
            {"action": "ACCEPT", "candidate_id": candidate_id, "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(edge["predicate"], "SAME_ENTITY_AS")
        self.assertEqual(edge["source_a"]["field_name"], "cust_id")
        self.assertEqual(edge["source_b"]["field_name"], "client_num")

        # VnV Layer 4, target 1: querying the registry returns the committed edge.
        status, ontology = self._get("/v1/ontology")
        self.assertEqual(status, 200)
        ids = [r["relationship_id"] for r in ontology["relationships"]]
        self.assertIn(edge["relationship_id"], ids)

    def test_reject_logs_negative_feedback(self):
        top = self._seed_and_analyze()
        status, rejected = self._post(
            "/v1/ontology/relationships",
            {"action": "REJECT", "candidate_id": top["candidate_id"], "reason": "false positive", "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(rejected["reason"], "false positive")

    def test_reject_then_reanalyze_does_not_resurface_pair(self):
        top = self._seed_and_analyze()
        status, _ = self._post(
            "/v1/ontology/relationships",
            {"action": "REJECT", "candidate_id": top["candidate_id"], "principal": "l2"},
        )
        self.assertEqual(status, 200)
        status, body = self._post(
            "/v1/explore/analyze",
            {"source_a": top["source_a"]["source_system"], "source_b": top["source_b"]["source_system"], "principal": "l2"},
        )
        self.assertEqual(status, 200)
        pairs = [(c["source_a"]["field_name"], c["source_b"]["field_name"]) for c in body["candidates"]]
        self.assertNotIn((top["source_a"]["field_name"], top["source_b"]["field_name"]), pairs)

    def test_accept_updates_session_er_blocking_metadata(self):
        top = self._seed_and_analyze()
        status, edge = self._post(
            "/v1/ontology/relationships",
            {"action": "ACCEPT", "candidate_id": top["candidate_id"], "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertIn(
            (top["source_a"]["source_system"], "cust_id", top["source_b"]["source_system"], "client_num"),
            self.session.er.linked_schema_fields,
        )

    def test_accept_twice_does_not_duplicate_catalog_entry(self):
        top = self._seed_and_analyze()
        status1, edge1 = self._post(
            "/v1/ontology/relationships",
            {"action": "ACCEPT", "candidate_id": top["candidate_id"], "principal": "l2"},
        )
        status2, edge2 = self._post(
            "/v1/ontology/relationships",
            {"action": "ACCEPT", "candidate_id": top["candidate_id"], "principal": "l2"},
        )
        self.assertEqual(status1, 200)
        self.assertEqual(status2, 200)
        self.assertEqual(edge1["relationship_id"], edge2["relationship_id"])
        status, ontology = self._get("/v1/ontology")
        matching = [r for r in ontology["relationships"] if r["candidate_id"] == top["candidate_id"]]
        self.assertEqual(len(matching), 1)

    def test_relabel_changes_predicate(self):
        top = self._seed_and_analyze()
        status, edge = self._post(
            "/v1/ontology/relationships",
            {"action": "RELABEL", "candidate_id": top["candidate_id"], "predicate": "FOREIGN_KEY_TO", "principal": "l2"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(edge["predicate"], "FOREIGN_KEY_TO")

    def test_unknown_action_is_400(self):
        status, body = self._post(
            "/v1/ontology/relationships", {"action": "BOGUS", "candidate_id": "x", "principal": "l2"}
        )
        self.assertEqual(status, 400)

    def test_vnv_layer_4_target_2_transitive_candidate_to_source_a(self):
        top = self._seed_and_analyze()  # source_a.cust_id <-> source_b.client_num
        source_a_name = top["source_a"]["source_system"]
        source_b_name = top["source_b"]["source_system"]
        status, edge = self._post(
            "/v1/ontology/relationships",
            {"action": "ACCEPT", "candidate_id": top["candidate_id"], "principal": "l2"},
        )
        self.assertEqual(status, 200)

        # New Source C, containing customer_identifier, sharing source_b's values.
        source_c_name = f"TableC_{self._testMethodName}"
        acl = ["domain:sre", "clearance:l2"]
        shared_ids = ("84920112", "10293847", "55512309")
        for val in shared_ids:
            self.session.store.put_raw(
                RawObject.create(source_system=source_c_name, payload=f"customer_identifier: {val}", acl_tags=acl)
            )

        status, body = self._post(
            "/v1/explore/analyze", {"source_a": source_c_name, "principal": "l2"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["candidates"])
        # source_c's values overlap both already-linked sources, so both
        # directions are legitimately proposed; assert the specific
        # transitive edge (C -> source_a, via source_b) is present among them.
        to_a = [c for c in body["candidates"] if c["source_a"]["source_system"] == source_a_name]
        self.assertTrue(to_a, body["candidates"])
        joined_reasons = " ".join(to_a[0]["match_reasons"])
        self.assertIn(f"Transitive mapping via {source_b_name}", joined_reasons)

    def test_unauthenticated_default_principal_lacks_operator_role_is_403(self):
        # default principal (no explicit role) should be rejected by _require_role
        status, body = self._post(
            "/v1/ontology/relationships", {"action": "ACCEPT", "candidate_id": "x", "principal": {"id": "anon", "attributes": []}}
        )
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
