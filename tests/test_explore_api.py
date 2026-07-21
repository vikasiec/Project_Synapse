"""
Active_File.md row 37: the platform's only "explore an ocean of unknown
data" entry point was entity-name-keyed (/v1/ask, /v1/query, /v1/history),
inverting schema-on-read's own premise -- a user must already know a name
to get an answer. /v1/explore (synapse/api.py::_explore_summary) is a
query-free, pure-aggregation view: entity types/counts/samples, sources
with observed field vocabulary, fields shared across sources, populated
predicate vocabulary, and open-issue counts. No LLM in the path -- see
the function's own docstring for why that's deliberate.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from synapse.api import _explore_summary, make_handler
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.security import Principal
from synapse.session import open_session
from synapse.store import SemanticStore


class TestExploreSummaryDirect(unittest.TestCase):
    """Unit-level tests against _explore_summary itself, mirroring the
    existing test_dynamic_story.py pattern for the sibling aggregation."""

    def test_empty_store_returns_well_formed_empty_payload(self):
        session = open_session()
        try:
            principal = Principal.from_tags("p", ["domain:clinical", "clearance:l2"])
            summary = _explore_summary(session, principal)
            self.assertEqual(summary["entity_types"], [])
            self.assertEqual(summary["sources"], [])
            self.assertEqual(summary["shared_fields_across_sources"], [])
            self.assertEqual(summary["predicate_vocabulary"], [])
            self.assertEqual(summary["open_issues"]["conflict_count"], 0)
            self.assertEqual(summary["open_issues"]["duplicate_name_group_count"], 0)
        finally:
            session.close()

    def test_entity_types_counted_and_sampled(self):
        session = open_session(domain="hospital_ops")
        try:
            ex = RuleExtractor(session.store, ontology=OntologyRegistry.default())
            for i in range(3):
                row = (
                    f"PatientID: PAT-{i}\nFullName: Patient {i}\nGenderCode: F\n"
                    f"DOB: 1980-01-0{i + 1}\nContactNumber: 555-010{i}\n"
                )
                r = session.ingestion.land(
                    "LIS-PatientMaster", row, ["domain:clinical", "clearance:l2"]
                )
                ex.extract_from_episode(r.episode, r.raw)

            principal = Principal.from_tags("p", ["domain:clinical", "clearance:l2"])
            summary = _explore_summary(session, principal)
            types = {t["type"]: t for t in summary["entity_types"]}
            self.assertIn("Patient", types)
            self.assertEqual(types["Patient"]["count"], 3)
            self.assertEqual(len(types["Patient"]["samples"]), 3)
        finally:
            session.close()

    def test_shared_fields_computed_across_two_sources(self):
        session = open_session(domain="hospital_ops")
        try:
            session.ingestion.land(
                "LIS-PatientMaster",
                "PatientID: PAT-1\nFullName: Jane Doe\n",
                ["domain:clinical", "clearance:l2"],
            )
            session.ingestion.land(
                "Middleware-RawResults",
                "PatientID: PAT-1\nInstrumentID: INST-9\n",
                ["domain:clinical", "clearance:l2"],
            )

            principal = Principal.from_tags("p", ["domain:clinical", "clearance:l2"])
            summary = _explore_summary(session, principal)

            source_names = {s["source_system"] for s in summary["sources"]}
            self.assertEqual(source_names, {"LIS-PatientMaster", "Middleware-RawResults"})

            shared = {f["field"]: set(f["sources"]) for f in summary["shared_fields_across_sources"]}
            self.assertIn("patientid", shared)
            self.assertEqual(shared["patientid"], {"LIS-PatientMaster", "Middleware-RawResults"})
            # fullname/instrumentid only appear in one source each -- must
            # not be reported as "shared".
            self.assertNotIn("fullname", shared)
            self.assertNotIn("instrumentid", shared)
        finally:
            session.close()

    def test_drift_synthetic_pattern_tags_excluded_from_observed_fields(self):
        """DriftDetector.observe_all() tags a source with synthetic
        "has_revenue"/"has_person"/etc markers alongside real observed
        field keys (synapse/drift.py's _KEY_RE pattern-trip heuristics).
        Those are drift-alert signals, not real fields -- Explore must not
        assert they're part of the schema."""
        session = open_session(domain="hospital_ops")
        try:
            session.ingestion.land(
                "LIS-PatientMaster",
                "PatientID: PAT-1\nFullName: Jane Doe\nAnnualRevenue: 100000\n",
                ["domain:clinical", "clearance:l2"],
            )
            principal = Principal.from_tags("p", ["domain:clinical", "clearance:l2"])
            summary = _explore_summary(session, principal)
            fields = summary["sources"][0]["observed_fields"]
            self.assertIn("patientid", fields)
            self.assertNotIn("has_revenue", fields)
        finally:
            session.close()

    def test_duplicate_name_group_count_does_not_explode_combinatorially(self):
        """Same real-world shape that produced a 24598-count live probe on
        New Data (Active_File.md row 37, Grok watch finding D16): a name
        that legitimately recurs across many entities of the same type
        (e.g. the same LOINC-coded LabResult name landing once per
        patient) must not turn into a huge pairwise "suggestion" count.
        open_issues reports distinct duplicate-name *groups*, not pairs --
        5 same-named entities is 1 group, not C(5,2)=10."""
        session = open_session(domain="hospital_ops")
        try:
            ex = RuleExtractor(session.store, ontology=OntologyRegistry.default())
            for i in range(5):
                row = f"PatientID: PAT-{i}\nFullName: Repeated Name\n"
                r = session.ingestion.land(
                    "LIS-PatientMaster", row, ["domain:clinical", "clearance:l2"]
                )
                ex.extract_from_episode(r.episode, r.raw)

            principal = Principal.from_tags("p", ["domain:clinical", "clearance:l2"])
            summary = _explore_summary(session, principal)
            self.assertEqual(summary["open_issues"]["duplicate_name_group_count"], 1)
        finally:
            session.close()

    def test_field_vocabulary_isolated_per_acl_domain_even_with_shared_source_name(self):
        """Field vocabulary is computed from ACL-visible raw payloads only
        (not a store-wide DriftDetector baseline keyed only by source
        name) -- if the same source_system string is ever landed under two
        different ACL domains, a principal scoped to one domain must not
        see field names that only ever appeared in the other domain's
        payloads under that same source name (Grok watch finding D3)."""
        session = open_session(domain="hospital_ops")
        try:
            session.ingestion.land(
                "SharedSourceName",
                "PatientID: PAT-1\nFullName: Jane Doe\n",
                ["domain:clinical", "clearance:l2"],
            )
            session.ingestion.land(
                "SharedSourceName",
                "AccountHolderID: ACC-1\nAnnualIncome: 90000\n",
                ["domain:banking", "clearance:l2"],
            )

            clinical = Principal.from_tags("p", ["domain:clinical", "clearance:l2"])
            summary = _explore_summary(session, clinical)
            src = next(s for s in summary["sources"] if s["source_system"] == "SharedSourceName")
            self.assertIn("patientid", src["observed_fields"])
            self.assertNotIn("accountholderid", src["observed_fields"])
        finally:
            session.close()

    def test_acl_scoping_hides_other_domains_entirely(self):
        session = open_session(domain="hospital_ops")
        try:
            ex = RuleExtractor(session.store, ontology=OntologyRegistry.default())
            r = session.ingestion.land(
                "LIS-PatientMaster",
                "PatientID: PAT-1\nFullName: Jane Doe\n",
                ["domain:clinical", "clearance:l2"],
            )
            ex.extract_from_episode(r.episode, r.raw)

            outsider = Principal.from_tags("p", ["domain:banking", "clearance:l2"])
            summary = _explore_summary(session, outsider)
            self.assertEqual(summary["entity_types"], [])
            self.assertEqual(summary["sources"], [])
            self.assertEqual(summary["shared_fields_across_sources"], [])
        finally:
            session.close()


class TestExploreApiHttp(unittest.TestCase):
    """HTTP-level smoke test through the real route, same harness as the
    other Sense-board API tests (tests/test_sense_api.py)."""

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

    def test_explore_endpoint_reachable_and_well_formed(self):
        status, body = self._get("/v1/explore")
        self.assertEqual(status, 200)
        for key in (
            "entity_types",
            "sources",
            "shared_fields_across_sources",
            "predicate_vocabulary",
            "open_issues",
        ):
            self.assertIn(key, body)

    def test_explore_reflects_data_landed_via_sense_drop(self):
        self._post(
            "/v1/sense/drop",
            {
                "kind": "json",
                "payload": "widget_id: W-1\nwidget_name: Sprocket\n",
                "source_system": "WidgetSource",
                "acl_tags": ["domain:widgets", "clearance:l2"],
            },
        )
        status, body = self._get(
            "/v1/explore?principal=domain:widgets,clearance:l2"
        )
        self.assertEqual(status, 200)
        source_names = {s["source_system"] for s in body["sources"]}
        self.assertIn("WidgetSource", source_names)


if __name__ == "__main__":
    unittest.main()
