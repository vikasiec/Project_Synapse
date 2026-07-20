"""
RC-01 (Active_File.md row 30): API routes previously bypassed ABAC entirely
-- GET routes resolved no principal at all, and mutation routes had no
role/capability gate. Fixed for the confirmed target (trusted-local POC,
not authenticated/multi-tenant): every route now resolves a principal and
applies the existing, already-tested filter_raw_objects/filter_facts/
filter_episodes/filter_entities/filter_conflicts helpers on reads, and a
minimal role:operator/role:admin gate on the mutation/export/audit routes
RC-01 named. This does not add real authentication (verifying who's
calling) -- it makes the *stated* principal's ACL actually matter, which
it previously did not on these routes at all.
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


class TestApiAbac(unittest.TestCase):
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
        try:
            with urllib.request.urlopen(self._url(path)) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

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

    def test_default_l2_still_sees_seeded_data_on_every_read_route(self):
        """Positive: existing l1/l2 demo presets must keep working exactly
        as before this row -- no regression to the Sense board UI flow."""
        status, _ = self._post("/v1/seed", {"scenario": "checkout"})
        self.assertEqual(status, 200)

        status, raw = self._get("/v1/raw?limit=10")
        self.assertEqual(status, 200)
        self.assertGreater(raw["count"], 0)

        status, eps = self._get("/v1/episodes?limit=10")
        self.assertEqual(status, 200)
        self.assertGreater(eps["count"], 0)

        status, facts = self._get("/v1/facts?limit=10")
        self.assertEqual(status, 200)
        self.assertGreater(facts["count"], 0)

        status, entities = self._get("/v1/entities")
        self.assertEqual(status, 200)
        self.assertTrue(entities)

        status, conflicts = self._get("/v1/conflicts")
        self.assertEqual(status, 200)
        self.assertTrue(conflicts)

    def test_unrelated_domain_principal_sees_nothing(self):
        """Negative: a principal whose ACL attributes share no domain with
        the landed data must see filtered/empty results, not the full
        store -- this is the actual RC-01 gap, now closed."""
        self._post("/v1/seed", {"scenario": "checkout"})
        blocked = 'domain:nonexistent,clearance:l2'

        status, raw = self._get(f"/v1/raw?limit=50&principal={blocked}")
        self.assertEqual(status, 200)
        self.assertEqual(raw["count"], 0)
        self.assertEqual(raw["items"], [])

        status, facts = self._get(f"/v1/facts?limit=50&principal={blocked}")
        self.assertEqual(status, 200)
        self.assertEqual(facts["count"], 0)

        status, entities = self._get(f"/v1/entities?principal={blocked}")
        self.assertEqual(status, 200)
        self.assertEqual(entities, [])

        status, conflicts = self._get(f"/v1/conflicts?principal={blocked}")
        self.assertEqual(status, 200)
        self.assertEqual(conflicts, [])

    def test_history_denies_for_unrelated_domain_principal(self):
        self._post("/v1/seed", {"scenario": "checkout"})
        status, resp = self._post(
            "/v1/history", {"entity": "checkout-service", "principal": "l2"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(resp["timeline"])

        status, denied = self._post(
            "/v1/history",
            {
                "entity": "checkout-service",
                "principal": "domain:nonexistent,clearance:l2",
            },
        )
        self.assertEqual(status, 404)

    def test_export_and_audit_require_admin_role(self):
        """Negative: l1/l2 demo presets do NOT get role:admin -- export and
        audit are more restricted by default than before this row, a
        deliberate tightening."""
        status, _ = self._get("/v1/export?principal=l2")
        self.assertEqual(status, 403)

        status, _ = self._get("/v1/audit?principal=l2")
        self.assertEqual(status, 403)

        status, _ = self._get("/v1/export?principal=domain:sre,clearance:l2,role:admin")
        self.assertEqual(status, 200)

    def test_export_and_materialize_are_acl_scoped_not_just_role_gated(self):
        """Row 36 (RC-08): role:admin/role:operator only grant the
        capability to call these routes -- they must not bypass ACL
        visibility. A privileged-but-wrong-domain principal must still see
        nothing, matching every other read route's behavior."""
        self._post("/v1/seed", {"scenario": "checkout"})

        status, admin_wrong_domain = self._get(
            "/v1/export?principal=domain:nonexistent,clearance:l2,role:admin"
        )
        self.assertEqual(status, 200)
        self.assertEqual(admin_wrong_domain["entities"], [])
        self.assertEqual(admin_wrong_domain["facts"], [])

        status, admin_right_domain = self._get(
            "/v1/export?principal=domain:sre,clearance:l2,channel:incidents,role:admin"
        )
        self.assertEqual(status, 200)
        self.assertTrue(admin_right_domain["entities"])
        self.assertTrue(admin_right_domain["facts"])

        status, mat_wrong_domain = self._post(
            "/v1/materialize",
            {"principal": "domain:nonexistent,clearance:l2,role:operator"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(mat_wrong_domain["view"]["row_count"], 0)

        status, mat_right_domain = self._post(
            "/v1/materialize",
            {"principal": "domain:sre,clearance:l2,channel:incidents,role:operator"},
        )
        self.assertEqual(status, 200)
        self.assertGreater(mat_right_domain["view"]["row_count"], 0)

    def test_mutation_routes_require_operator_role(self):
        """Negative: a principal without role:operator cannot merge
        entities, pin a conflict, reprocess, materialize, or land data via
        sense/drop -- previously none of these routes checked anything."""
        self._post("/v1/seed", {"scenario": "checkout"})
        no_role = "domain:sre,clearance:l2"

        status, _ = self._post(
            "/v1/entities/merge",
            {"survivor_id": "x", "loser_id": "y", "principal": no_role},
        )
        self.assertEqual(status, 403)

        status, _ = self._post(
            "/v1/conflicts/whatever/pin",
            {"chosen_fact_id": "x", "principal": no_role},
        )
        self.assertEqual(status, 403)

        status, _ = self._post("/v1/reprocess", {"principal": no_role})
        self.assertEqual(status, 403)

        status, _ = self._post("/v1/materialize", {"principal": no_role})
        self.assertEqual(status, 403)

        status, _ = self._post(
            "/v1/sense/drop",
            {"kind": "json", "payload": "x", "principal": no_role},
        )
        self.assertEqual(status, 403)

    def test_default_l2_still_passes_mutation_gate(self):
        """Positive: default principal (no `principal` key at all, matching
        every pre-existing caller in the codebase) keeps working."""
        self._post("/v1/seed", {"scenario": "checkout"})
        status, body = self._post(
            "/v1/sense/drop", {"kind": "json", "payload": "some free text"}
        )
        self.assertEqual(status, 200)
        self.assertIn("object_id", body)


if __name__ == "__main__":
    unittest.main()
