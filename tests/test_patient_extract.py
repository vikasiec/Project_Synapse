"""Hospital ops vertical — Patient Path A extraction (Active_File.md task 1)."""

from __future__ import annotations

import unittest
from pathlib import Path

from synapse.connectors.csv_drop import CsvDropConnector
from synapse.connectors.registry import ConnectorRegistry
from synapse.connectors.runner import ConnectorRunner
from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.session import open_session
from synapse.store import SemanticStore

PATIENT_PAYLOAD = """Patient_id: P001
First_name: David
Last_name: Williams
Gender: F
Date_of_birth: 1955-06-04
Contact_number: 6939585183
Address: 789 Pine Rd
Registration_date: 2022-06-23
Insurance_provider: WellnessCorp
Insurance_number: INS840674
Email: david.williams@mail.com
"""

HOSPITAL_DIR = (
    Path(__file__).resolve().parents[1] / ".data" / "kaggle_raw" / "hospital_management"
)


class TestPatientExtract(unittest.TestCase):
    def test_lis_header_synonyms_extract_same_as_canonical_headers(self):
        """A patient-master export using LIS-style headers (`PatientID`,
        `FullName`, `GenderCode`, `DOB`, `ContactNumber` -- New Data/'s
        actual lis_patient_master.csv shape) must extract exactly like the
        canonical `Patient_id`/`First_name`/`Last_name` shape does, via
        schema-synonym resolution (synapse/coding_systems.py) rather than
        requiring an exact column-name allowlist per known file."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")
        row = (
            "PatientID: PAT-88301\n"
            "FullName: Johnathan Martin\n"
            "GenderCode: M\n"
            "DOB: 1974-09-04\n"
            "ContactNumber: +1-555-350-4657\n"
        )
        r = ing.land("LIS-PatientMaster", row, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Patient")
        self.assertEqual(out.entity.canonical_name, "Johnathan Martin")
        preds = {f.predicate: f.object for f in out.facts}
        self.assertEqual(preds.get("date_of_birth"), "1974-09-04")
        self.assertEqual(preds.get("gender"), "M")
        self.assertEqual(preds.get("contact_number"), "+1-555-350-4657")

    def test_ontology_patient(self):
        ont = OntologyRegistry.default()
        self.assertIn("Patient", ont.types)
        g = ont.govern_extract("Patient", domain="hospital_ops")
        self.assertEqual(g.ontology_type, "Patient")
        self.assertEqual(g.ontology_layer, "L1")
        self.assertEqual(g.domain, "hospital_ops")

    def test_patient_and_employee_never_share_er_family(self):
        ont = OntologyRegistry.default()
        self.assertFalse(ont.types_match("Patient", "Person"))
        self.assertFalse(ont.types_match("Patient", "IdentityPrincipal"))

    def test_same_name_different_patient_id_never_merges(self):
        """Two real patients sharing a name (e.g. two Michael Taylors) must
        stay distinct entities — a name match alone is not identity."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")

        p010 = (
            "Patient_id: P010\nFirst_name: Michael\nLast_name: Taylor\n"
            "Date_of_birth: 2001-10-13\nInsurance_provider: WellnessCorp\n"
        )
        p046 = (
            "Patient_id: P046\nFirst_name: Michael\nLast_name: Taylor\n"
            "Date_of_birth: 1986-09-01\nInsurance_provider: MedCare Plus\n"
        )
        r1 = ing.land("HIS-Patients", p010, ["domain:clinical", "clearance:l2"])
        out1 = ex.extract_from_episode(r1.episode, r1.raw)
        r2 = ing.land("HIS-Patients", p046, ["domain:clinical", "clearance:l2"])
        out2 = ex.extract_from_episode(r2.episode, r2.raw)

        self.assertIsNotNone(out1)
        self.assertIsNotNone(out2)
        self.assertNotEqual(out1.entity.entity_id, out2.entity.entity_id)

    def test_same_patient_id_across_sources_does_merge(self):
        """The same patient re-entered by a second source (same patient_id)
        must still merge into one entity — the fix must not break this."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")

        sor = (
            "Patient_id: P001\nFirst_name: David\nLast_name: Williams\n"
            "Insurance_provider: WellnessCorp\n"
        )
        frontdesk = (
            "Patient_id: P001\nFirst_name: David\nLast_name: Williams\n"
            "Insurance_provider: WellnessCorp Plus\n"
        )
        r1 = ing.land("HIS-Patients", sor, ["domain:clinical", "clearance:l2"])
        out1 = ex.extract_from_episode(r1.episode, r1.raw)
        r2 = ing.land("FrontDesk-Intake", frontdesk, ["domain:clinical", "clearance:l2"])
        out2 = ex.extract_from_episode(r2.episode, r2.raw)

        self.assertEqual(out1.entity.entity_id, out2.entity.entity_id)
        values = {
            str(f.object)
            for f in store.facts_for_entity(out1.entity.entity_id)
            if f.predicate == "insurance_provider"
        }
        self.assertEqual(values, {"WellnessCorp", "WellnessCorp Plus"})

    def test_path_a_patient_row(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")
        r = ing.land(
            "HIS-Patients", PATIENT_PAYLOAD, ["domain:clinical", "clearance:l2"]
        )
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Patient")
        self.assertEqual(out.entity.ontology_type, "Patient")
        self.assertEqual(out.entity.canonical_name, "David Williams")
        preds = {f.predicate: f.object for f in out.facts}
        self.assertEqual(preds.get("insurance_provider"), "WellnessCorp")
        self.assertEqual(preds.get("insurance_number"), "INS840674")
        self.assertIn("date_of_birth", preds)

    def test_appointment_row_does_not_falsely_become_a_patient(self):
        """patient_id alone (foreign key, no identity fields) must never be
        mistyped as a Patient — it's fine (expected, since task 5) for it to
        extract as its own Appointment entity instead."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")
        payload = (
            "Appointment_id: A001\nPatient_id: P034\nDoctor_id: D009\n"
            "Appointment_date: 2023-08-09\nReason_for_visit: Therapy\nStatus: Scheduled\n"
        )
        r = ing.land("HIS-Scheduling", payload, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Appointment")

    @unittest.skipUnless(
        (HOSPITAL_DIR / "patients.csv").is_file(), "hospital_management CSVs not present"
    )
    def test_real_patients_csv_all_rows_extract(self):
        store = SemanticStore()
        reg = ConnectorRegistry()
        conn = CsvDropConnector(
            path=str(HOSPITAL_DIR / "patients.csv"),
            connector_id="hosp-patients-test",
            source_system="HIS-Patients",
            default_acl=["domain:clinical", "clearance:l2"],
        )
        reg.register(conn)
        runner = ConnectorRunner(
            store,
            reg,
            ingestion=IngestionService(store, domain="hospital_ops"),
            dual_path=DualPathExtractor(store, residual=HeuristicResidualExtractor()),
            domain="hospital_ops",
            use_dual_path=True,
        )
        result = runner.poll_one("hosp-patients-test")
        self.assertEqual(result.events, 50)
        self.assertEqual(result.extracted, 50)
        self.assertIsNotNone(store.get_entity_by_name("David Williams"))

    def test_session_patient_seed_style(self):
        session = open_session()
        try:
            session.ingestion.domain = "hospital_ops"
            r = session.ingestion.land(
                "HIS-Patients", PATIENT_PAYLOAD, ["domain:clinical", "clearance:l2"]
            )
            out = session.dual_path.extract(r.episode, r.raw)
            self.assertEqual(out.entity_name, "David Williams")
            ent = session.store.get_entity_by_name("David Williams")
            self.assertEqual(ent.ontology_type, "Patient")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
