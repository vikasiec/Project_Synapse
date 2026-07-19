"""FHIR Bundle extraction (Active_File.md task 15) — second real
interoperability format. Applies task 13/Codex's lesson proactively: verify
LabResult identity stays patient-scoped from the start, not after a repro."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from synapse.connectors.fhir_file import FhirDirectoryConnector
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.session import open_session
from synapse.store import SemanticStore

FHIR_DIR = Path(__file__).resolve().parents[1] / ".data" / "synthetic_fhir"


def _bundle(patient_id, family, given, obs_code, obs_display, value, unit, low, high, flag):
    return json.dumps(
        {
            "resourceType": "Bundle",
            "type": "message",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": patient_id.lower(),
                        "identifier": [{"system": "urn:oid:HIS", "value": patient_id}],
                        "name": [{"family": family, "given": [given]}],
                        "birthDate": "1970-01-01",
                        "gender": "female",
                    }
                },
                {
                    "resource": {
                        "resourceType": "Observation",
                        "id": f"obs-{patient_id.lower()}",
                        "status": "final",
                        "code": {"coding": [{"code": obs_code, "display": obs_display}]},
                        "subject": {"reference": f"Patient/{patient_id.lower()}"},
                        "valueQuantity": {"value": value, "unit": unit},
                        "referenceRange": [{"low": {"value": low}, "high": {"value": high}}],
                        "interpretation": [{"coding": [{"code": flag}]}],
                    }
                },
            ],
        }
    )


class TestFhirExtract(unittest.TestCase):
    def test_bundle_produces_patient_and_labresult(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        text = _bundle("P001", "Williams", "David", "777-3", "Platelet Count", 245, "10*3/uL", 150, 400, "N")
        r = ing.land("FHIR-Interface", text, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)

        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Patient")
        self.assertEqual(out.entity.canonical_name, "David Williams")

        plt = store.get_entity_by_name("Platelet Count")
        self.assertIsNotNone(plt)
        preds = {f.predicate: f.object for f in store.facts_for_entity(plt.entity_id)}
        self.assertEqual(preds["result"], 245)
        self.assertEqual(preds["reference_range"], "150-400")
        self.assertEqual(preds["patient_entity_id"], out.entity.entity_id)

    def test_two_different_patients_same_test_stay_distinct(self):
        """Applying task 13's lesson proactively: two different patients'
        results for the same test must never converge into one entity."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")

        a = _bundle("P001", "Williams", "David", "777-3", "Platelet Count", 245, "10*3/uL", 150, 400, "N")
        b = _bundle("P904", "Andersen", "Lars", "777-3", "Platelet Count", 132, "10*3/uL", 150, 400, "L")
        r1 = ing.land("FHIR-Interface", a, ["domain:clinical", "clearance:l2"])
        out_a = ex.extract_from_episode(r1.episode, r1.raw)
        r2 = ing.land("FHIR-Interface", b, ["domain:clinical", "clearance:l2"])
        out_b = ex.extract_from_episode(r2.episode, r2.raw)

        plt_entities = [
            e for e in store.entities.values() if e.canonical_name == "Platelet Count"
        ]
        self.assertEqual(len(plt_entities), 2)
        for ent in plt_entities:
            values = {
                f.object for f in store.facts_for_entity(ent.entity_id) if f.predicate == "result"
            }
            self.assertEqual(len(values), 1)
        self.assertNotEqual(out_a.entity.entity_id, out_b.entity.entity_id)

    def test_non_bundle_resource_not_extracted(self):
        """Scoped to Bundle only -- a standalone resource falls through
        honestly rather than being guessed at."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        standalone = json.dumps({"resourceType": "Patient", "id": "p1"})
        r = ing.land("FHIR-Interface", standalone, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNone(out)

    def test_malformed_json_falls_through_honestly(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land("FHIR-Interface", '{"resourceType": "Bundle", oops', ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNone(out)

    def test_observation_for_unresolvable_subject_skipped(self):
        """An Observation referencing a subject not in this bundle must not
        be silently attributed to whichever Patient happens to be present."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        bundle = json.dumps(
            {
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "p001",
                            "identifier": [{"value": "P001"}],
                            "name": [{"family": "Williams", "given": ["David"]}],
                            "birthDate": "1955-06-04",
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "status": "final",
                            "code": {"coding": [{"code": "777-3", "display": "Platelet Count"}]},
                            "subject": {"reference": "Patient/someone-else"},
                            "valueQuantity": {"value": 245, "unit": "10*3/uL"},
                        }
                    },
                ],
            }
        )
        r = ing.land("FHIR-Interface", bundle, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)  # Patient's own birthDate still extracts
        self.assertIsNone(store.get_entity_by_name("Platelet Count"))

    @unittest.skipUnless(FHIR_DIR.is_dir(), "synthetic FHIR data not present")
    def test_real_directory_cross_format_with_csv_and_hl7(self):
        """The real proof: patient P001 must converge to ONE entity across
        THREE structurally unrelated formats -- CSV, HL7v2, and now FHIR."""
        session = open_session()
        try:
            session.ingestion.domain = "hospital_ops"
            r = session.ingestion.land(
                "HIS-Patients",
                "Patient_id: P001\nFirst_name: David\nLast_name: Williams\n"
                "Insurance_provider: WellnessCorp\n",
                ["domain:clinical", "clearance:l2"],
            )
            session.dual_path.extract(r.episode, r.raw)
            csv_id = session.store.get_entity_by_name("David Williams").entity_id

            conn = FhirDirectoryConnector(path=str(FHIR_DIR), connector_id="fhir-test")
            session.connectors.register(conn)
            poll = session.connector_runner.poll_one("fhir-test")

            self.assertEqual(poll.events, 3)
            self.assertEqual(poll.extracted, 3)

            post_id = session.store.get_entity_by_name("David Williams").entity_id
            self.assertEqual(csv_id, post_id)

            lab_results = [
                e for e in session.store.entities.values() if e.entity_type == "LabResult"
            ]
            # bundle001: 1 (Glucose, new patient) + bundle002: 2 (Platelet, Creatinine,
            # existing P001) + bundle003: 1 (Platelet, different patient) = 4
            self.assertEqual(len(lab_results), 4)

            plt_entities = [e for e in lab_results if e.canonical_name == "Platelet Count"]
            self.assertEqual(len(plt_entities), 2)  # P001's and P904's stay distinct
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
