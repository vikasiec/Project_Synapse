"""
Sense board Step 1's "what's actually loaded" card (synapse/api.py::
_dynamic_story) -- a user flagged that after loading real clinical data,
Step 1 still advertised the original canned "Checkout outage" / "Billing
revenue conflict" demo scenarios regardless of what was actually in the
store. This must reflect real ingested data, and fall back to nothing
(letting the canned cards stand) when the store is genuinely empty.
"""

from __future__ import annotations

import unittest

from synapse.api import _dynamic_story
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore


class TestDynamicStory(unittest.TestCase):
    def test_empty_store_returns_none(self):
        store = SemanticStore()
        self.assertIsNone(_dynamic_story(store))

    def test_single_source_clinical_data(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")
        row = (
            "PatientID: PAT-001\nFullName: Jane Doe\nGenderCode: F\n"
            "DOB: 1980-01-01\nContactNumber: 555-0100\n"
        )
        r = ing.land("LIS-PatientMaster", row, ["domain:clinical", "clearance:l2"])
        ex.extract_from_episode(r.episode, r.raw)

        story = _dynamic_story(store)
        self.assertIsNotNone(story)
        self.assertEqual(story["domain"], "domain:clinical")
        self.assertIn("Clinical", story["title"])
        self.assertEqual(story["entity_count"], 1)
        self.assertEqual(story["source_count"], 1)
        self.assertIn("LIS-PatientMaster", story["sources"])
        self.assertNotIn("conflict", story["subtitle"].lower())

    def test_multi_source_convergence_reflected_in_subtitle(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")

        row = (
            "PatientID: PAT-002\nFullName: John Roe\nGenderCode: M\n"
            "DOB: 1975-05-05\nContactNumber: 555-0200\n"
        )
        r1 = ing.land("LIS-PatientMaster", row, ["domain:clinical", "clearance:l2"])
        ex.extract_from_episode(r1.episode, r1.raw)

        msg = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20260101083000||ORU^R01|MSG1|P|2.5.1\n"
            "PID|1||PAT-002^^^HIS^MR||Roe^John||19750505|M|||1 Elm St||5550200\n"
            "OBR|1|ORD1|LAB1|HGB^Hemoglobin^L|||20260101080000\n"
            "OBX|1|NM|HGB^Hemoglobin^L||14.0|g/dL|13.5-17.5|N|||F\n"
        )
        r2 = ing.land("HL7-Interface", msg, ["domain:clinical", "clearance:l2"])
        ex.extract_from_episode(r2.episode, r2.raw)

        story = _dynamic_story(store)
        self.assertEqual(story["source_count"], 2)
        self.assertIn("2 sources converging", story["subtitle"])
        self.assertIn("LIS-PatientMaster", story["subtitle"])
        self.assertIn("HL7-Interface", story["subtitle"])

    def test_most_landed_domain_wins_in_mixed_store(self):
        store = SemanticStore()
        ing = IngestionService(store, domain="infra_ops")
        for i in range(3):
            ing.land(
                "GitHub-CI",
                f"BUILD SUCCESSFUL: checkout-service deployed image tag v{i}.0.0.\n",
                ["domain:sre", "clearance:l2"],
            )
        ing.land(
            "LIS-PatientMaster",
            "PatientID: PAT-003\nFullName: Ana Kim\n",
            ["domain:clinical", "clearance:l2"],
        )

        story = _dynamic_story(store)
        self.assertEqual(story["domain"], "domain:sre")
        self.assertIn("Incident", story["title"])

    def test_unlabeled_domain_falls_back_to_readable_title(self):
        store = SemanticStore()
        ing = IngestionService(store, domain="whatever")
        r = ing.land(
            "SomeSource",
            "widget_id: W-1\nwidget_name: Sprocket\nwidget_status: active\n",
            ["domain:widgets", "clearance:l2"],
        )
        self.assertFalse(r.dropped, "fixture payload must actually land for this test to mean anything")
        story = _dynamic_story(store)
        self.assertEqual(story["title"], "widgets data loaded")


if __name__ == "__main__":
    unittest.main()
