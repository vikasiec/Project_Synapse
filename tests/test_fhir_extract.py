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
    def test_distinct_fhir_observation_instances_stay_distinct(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        first = _bundle("P777", "Patel", "Asha", "718-7", "Hemoglobin", 13.2, "g/dL", 12, 16, "N").replace(
            "obs-p777", "obs-p777-draw-a"
        )
        second = _bundle("P777", "Patel", "Asha", "718-7", "Hemoglobin", 9.1, "g/dL", 12, 16, "L").replace(
            "obs-p777", "obs-p777-draw-b"
        )
        for source, text in (("FHIR-Lab-A", first), ("FHIR-Lab-B", second)):
            landed = ing.land(source, text, ["domain:clinical", "clearance:l2"])
            ex.extract_from_episode(landed.episode, landed.raw)
        hgb = [e for e in store.entities.values() if e.canonical_name == "Hemoglobin"]
        self.assertEqual(len(hgb), 2)
        self.assertEqual(
            sorted(
                f.object for e in hgb for f in store.facts_for_entity(e.entity_id)
                if f.predicate == "result"
            ),
            [9.1, 13.2],
        )

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

    def test_same_bare_identifier_different_system_stays_distinct(self):
        """FHIR analogue of the PID-3 namespace-collision case (row 23):
        two different facilities can independently issue the same bare
        identifier value ("P001") under two genuinely different
        Identifier.system URIs, for two different real people."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")

        general = json.dumps(
            {
                "resourceType": "Bundle",
                "type": "message",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "p001-general",
                            "identifier": [{"system": "urn:oid:HIS", "value": "P001"}],
                            "name": [{"family": "Williams", "given": ["David"]}],
                            "birthDate": "1955-06-04",
                            "gender": "male",
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "obs-general",
                            "status": "final",
                            "code": {"coding": [{"code": "777-3", "display": "Platelet Count"}]},
                            "subject": {"reference": "Patient/p001-general"},
                            "valueQuantity": {"value": 245, "unit": "10*3/uL"},
                        }
                    },
                ],
            }
        )
        stmary = json.dumps(
            {
                "resourceType": "Bundle",
                "type": "message",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "p001-stmary",
                            "identifier": [{"system": "urn:oid:STMARY", "value": "P001"}],
                            "name": [{"family": "Sharma", "given": ["Priya"]}],
                            "birthDate": "1988-07-12",
                            "gender": "female",
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "obs-stmary",
                            "status": "final",
                            "code": {"coding": [{"code": "777-3", "display": "Platelet Count"}]},
                            "subject": {"reference": "Patient/p001-stmary"},
                            "valueQuantity": {"value": 132, "unit": "10*3/uL"},
                        }
                    },
                ],
            }
        )
        r1 = ing.land("FHIR-Interface", general, ["domain:clinical", "clearance:l2"])
        out_a = ex.extract_from_episode(r1.episode, r1.raw)
        r2 = ing.land("FHIR-Interface", stmary, ["domain:clinical", "clearance:l2"])
        out_b = ex.extract_from_episode(r2.episode, r2.raw)

        self.assertNotEqual(out_a.entity.entity_id, out_b.entity.entity_id)
        self.assertEqual(out_a.entity.canonical_name, "David Williams")
        self.assertEqual(out_b.entity.canonical_name, "Priya Sharma")

        plt_entities = [
            e for e in store.entities.values() if e.canonical_name == "Platelet Count"
        ]
        self.assertEqual(len(plt_entities), 2, "same bare identifier, different system, must not merge LabResults either")

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

    def test_observation_with_malformed_reference_skipped(self):
        """An Observation with no usable subject reference at all -- not
        "/"-shaped, or missing entirely -- must not be silently attributed
        to whichever Patient happens to be present in the bundle."""
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
                            "subject": {"display": "no reference, just a name"},
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

    def test_observation_for_external_reference_creates_stub_patient(self):
        """An Observation whose subject is a bare "Patient/<id>" reference
        with NO inline resource anywhere in the bundle -- the common shape
        for real bulk Observation exports, and the shape this proof
        originally refused to extract at all (Claude_Instructions.md Step
        3.2) -- must get its own lightweight stub Patient, not be dropped
        and not be misattributed to an unrelated Patient resource that
        happens to be present."""
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
                            "subject": {
                                "reference": "Patient/someone-else",
                                "display": "Someone Else",
                            },
                            "valueQuantity": {"value": 245, "unit": "10*3/uL"},
                        }
                    },
                ],
            }
        )
        r = ing.land("FHIR-Interface", bundle, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)

        plt = store.get_entity_by_name("Platelet Count")
        self.assertIsNotNone(plt)
        preds = {f.predicate: f.object for f in store.facts_for_entity(plt.entity_id)}
        self.assertEqual(preds["result"], 245)

        stub = store.get_entity_by_name("Someone Else")
        self.assertIsNotNone(stub)
        self.assertEqual(stub.entity_type, "Patient")
        self.assertLess(stub.trust_score, 0.85)  # lower confidence than a resolved record
        self.assertEqual(preds["patient_entity_id"], stub.entity_id)

        # Not attributed to the unrelated embedded Patient.
        david = store.get_entity_by_name("David Williams")
        self.assertIsNotNone(david)
        self.assertNotEqual(david.entity_id, stub.entity_id)

    def test_observation_only_bundle_no_embedded_patient_extracts(self):
        """The real bulk-export shape this proof could not handle at all
        before: a Bundle containing ONLY Observation resources, each
        referencing its patient externally, with zero embedded Patient
        resources anywhere. Must extract every observation against its
        own correctly-distinguished stub patient."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        bundle = json.dumps(
            {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "obs-1",
                            "status": "final",
                            "code": {
                                "coding": [
                                    {"system": "http://loinc.org", "code": "3016-3", "display": "TSH"}
                                ]
                            },
                            "subject": {"reference": "Patient/PAT-1", "display": "Alpha Patient"},
                            "valueQuantity": {"value": 2.1, "unit": "uIU/mL"},
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "id": "obs-2",
                            "status": "final",
                            "code": {
                                "coding": [
                                    {"system": "http://loinc.org", "code": "3016-3", "display": "TSH"}
                                ]
                            },
                            "subject": {"reference": "Patient/PAT-2", "display": "Beta Patient"},
                            "valueQuantity": {"value": 3.4, "unit": "uIU/mL"},
                        }
                    },
                ],
            }
        )
        r = ing.land("FHIR-Interface", bundle, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)

        alpha = store.get_entity_by_name("Alpha Patient")
        beta = store.get_entity_by_name("Beta Patient")
        self.assertIsNotNone(alpha)
        self.assertIsNotNone(beta)
        self.assertNotEqual(alpha.entity_id, beta.entity_id)

        tsh_entities = [e for e in store.entities.values() if e.canonical_name == "TSH"]
        self.assertEqual(len(tsh_entities), 2, "two patients' TSH must stay distinct")

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

            # The fixture directory also carries the two same-authority conflict
            # bundles used by the Sense conflict proof (bundle004/005).
            self.assertEqual(poll.events, 5)
            self.assertEqual(poll.extracted, 5)

            post_id = session.store.get_entity_by_name("David Williams").entity_id
            self.assertEqual(csv_id, post_id)

            lab_results = [
                e for e in session.store.entities.values() if e.entity_type == "LabResult"
            ]
            # bundle001: 1 + bundle002: 2 + bundle003: 1 + bundle004/005:
            # one shared Observation.id = 1 distinct instance, total 5.
            self.assertEqual(len(lab_results), 5)

            plt_entities = [e for e in lab_results if e.canonical_name == "Platelet Count"]
            self.assertEqual(len(plt_entities), 2)  # P001's and P904's stay distinct
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
