"""GET /v1/er/merge-candidates -- Graph-First Discovery & Entity Resolution
(docs/Graph-First Discovery & Entity Resolution.pdf), Step 3/4."""

import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from synapse.api import make_handler
from synapse.models import Entity, Fact, RawObject
from synapse.session import open_session
from synapse.workspace import Workspace


class TestErMergeCandidatesApi(unittest.TestCase):
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
        crm = Entity.create("Person", "Justin Mason", acl_tags=acl)
        billing = Entity.create("Person", "J. Mason", acl_tags=acl)
        cls.session.store.put_entity(crm)
        cls.session.store.put_entity(billing)
        for ent, source in ((crm, "CRM-Salesforce"), (billing, "Billing-Zuora")):
            cls.session.store.put_fact(
                Fact(
                    fact_id=f"f-{ent.entity_id}",
                    subject_entity_id=ent.entity_id,
                    predicate="seen",
                    object="x",
                    confidence=0.9,
                    evidence_refs=[],
                    source_system=source,
                    acl_tags=acl,
                    valid_from="2026-01-01T00:00:00Z",
                )
            )

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.session.close()

    def _get(self, path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
            return resp.status, json.loads(resp.read().decode())

    def test_merge_candidate_surfaces_and_scored(self):
        status, body = self._get("/v1/er/merge-candidates?principal=l2")
        self.assertEqual(status, 200)
        self.assertTrue(body["candidates"])
        top = body["candidates"][0]
        names = {top["entity_a"]["canonical_name"], top["entity_b"]["canonical_name"]}
        self.assertEqual(names, {"Justin Mason", "J. Mason"})
        self.assertGreater(top["similarity_score"], 0.0)

    def test_acl_hides_candidates_from_unrelated_domain(self):
        status, body = self._get("/v1/er/merge-candidates?principal=domain:banking,clearance:l2")
        self.assertEqual(status, 200)
        self.assertEqual(body["candidates"], [])

    def test_workspace_id_scopes_candidates_to_that_workspaces_sources(self):
        # Real bug: without this, Resolve compared every entity ever
        # landed across every workspace against every other, since
        # entities carry no workspace of their own and the endpoint
        # ignored workspace boundaries entirely.
        acl = ["domain:sre", "clearance:l2"]
        ws_a = Workspace.create("WS A")
        ws_b = Workspace.create("WS B")
        self.session.store.put_workspace(ws_a)
        self.session.store.put_workspace(ws_b)
        self.session.store.put_raw(
            RawObject.create(source_system="CRM-Salesforce", payload="x", acl_tags=acl, workspace_id=ws_a.workspace_id)
        )
        self.session.store.put_raw(
            RawObject.create(source_system="Billing-Zuora", payload="x", acl_tags=acl, workspace_id=ws_a.workspace_id)
        )

        status, body = self._get(f"/v1/er/merge-candidates?principal=l2&workspace_id={ws_a.workspace_id}")
        self.assertEqual(status, 200)
        self.assertTrue(body["candidates"])

        status, body = self._get(f"/v1/er/merge-candidates?principal=l2&workspace_id={ws_b.workspace_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body["candidates"], [])

    def test_workspace_ids_finds_candidates_split_across_two_workspaces(self):
        # Cross-workspace entity resolution: the same real "Mason" pair
        # split across two separate workspaces (one source per workspace)
        # is invisible to either workspace alone, but the union
        # (workspace_ids=a,b) should surface it -- mirrors /v1/super-
        # schema's multi-workspace combine step, for entities. Uses its
        # own source_system names, distinct from other tests in this
        # class-shared session, since workspace_for_source resolves by
        # first-inserted raw object per source_system.
        acl = ["domain:sre", "clearance:l2"]
        ws_a = Workspace.create("Cross A")
        ws_b = Workspace.create("Cross B")
        self.session.store.put_workspace(ws_a)
        self.session.store.put_workspace(ws_b)
        self.session.store.put_raw(
            RawObject.create(source_system="CRM-X", payload="x", acl_tags=acl, workspace_id=ws_a.workspace_id)
        )
        self.session.store.put_raw(
            RawObject.create(source_system="Billing-X", payload="x", acl_tags=acl, workspace_id=ws_b.workspace_id)
        )
        crm = Entity.create("Person", "Alex Cross", acl_tags=acl)
        billing = Entity.create("Person", "A. Cross", acl_tags=acl)
        self.session.store.put_entity(crm)
        self.session.store.put_entity(billing)
        for ent, source in ((crm, "CRM-X"), (billing, "Billing-X")):
            self.session.store.put_fact(
                Fact(
                    fact_id=f"f-cross-{ent.entity_id}",
                    subject_entity_id=ent.entity_id,
                    predicate="seen",
                    object="x",
                    confidence=0.9,
                    evidence_refs=[],
                    source_system=source,
                    acl_tags=acl,
                    valid_from="2026-01-01T00:00:00Z",
                )
            )

        status, body = self._get(f"/v1/er/merge-candidates?principal=l2&workspace_id={ws_a.workspace_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body["candidates"], [])

        status, body = self._get(
            f"/v1/er/merge-candidates?principal=l2&workspace_ids={ws_a.workspace_id},{ws_b.workspace_id}"
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["candidates"])
        names = {body["candidates"][0]["entity_a"]["canonical_name"], body["candidates"][0]["entity_b"]["canonical_name"]}
        self.assertEqual(names, {"Alex Cross", "A. Cross"})


if __name__ == "__main__":
    unittest.main()
