"""Hospital ops vertical — Doctor + Appointment extraction & join (task 5)."""

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
from synapse.store import SemanticStore

DOCTOR_PAYLOAD = """Doctor_id: D001
First_name: David
Last_name: Taylor
Specialization: Dermatology
Phone_number: 8322010158
Years_experience: 17
Hospital_branch: Westside Clinic
Email: dr.david.taylor@hospital.com
"""

APPOINTMENT_PAYLOAD = """Appointment_id: A001
Patient_id: P001
Doctor_id: D001
Appointment_date: 2023-08-09
Appointment_time: 15:15:00
Reason_for_visit: Therapy
Status: Scheduled
"""

HOSPITAL_DIR = (
    Path(__file__).resolve().parents[1] / ".data" / "kaggle_raw" / "hospital_management"
)


class TestDoctorAppointmentExtract(unittest.TestCase):
    def test_ontology_doctor_and_appointment(self):
        ont = OntologyRegistry.default()
        self.assertIn("Doctor", ont.types)
        self.assertIn("Appointment", ont.types)
        gd = ont.govern_extract("Doctor", domain="hospital_ops")
        self.assertEqual(gd.ontology_type, "Doctor")
        self.assertEqual(gd.ontology_layer, "L1")
        ga = ont.govern_extract("Appointment", domain="hospital_ops")
        self.assertEqual(ga.ontology_type, "Appointment")

    def test_doctor_and_patient_never_share_er_family(self):
        ont = OntologyRegistry.default()
        self.assertFalse(ont.types_match("Doctor", "Patient"))
        self.assertFalse(ont.types_match("Doctor", "Person"))

    def test_path_a_doctor_row(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")
        r = ing.land("HIS-Doctors", DOCTOR_PAYLOAD, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Doctor")
        self.assertEqual(out.entity.canonical_name, "David Taylor")
        preds = {f.predicate: f.object for f in out.facts}
        self.assertEqual(preds.get("specialization"), "Dermatology")

    def test_appointment_row_without_prior_landing_still_lands_ids_unresolved(self):
        """Appointment lands with raw patient_id/doctor_id even if those
        entities haven't been extracted yet — honest partial link, not a
        failure (H6 reprocess can complete it later)."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")
        r = ing.land(
            "HIS-Scheduling", APPOINTMENT_PAYLOAD, ["domain:clinical", "clearance:l2"]
        )
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Appointment")
        preds = {f.predicate: f.object for f in out.facts}
        self.assertEqual(preds.get("patient_id"), "P001")
        self.assertEqual(preds.get("doctor_id"), "D001")
        self.assertNotIn("patient_entity_id", preds)
        self.assertNotIn("doctor_entity_id", preds)

    def test_appointment_resolves_links_when_patient_and_doctor_already_landed(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")

        patient_payload = (
            "Patient_id: P001\nFirst_name: David\nLast_name: Williams\n"
            "Insurance_provider: WellnessCorp\n"
        )
        rp = ing.land("HIS-Patients", patient_payload, ["domain:clinical", "clearance:l2"])
        patient_out = ex.extract_from_episode(rp.episode, rp.raw)

        rd = ing.land("HIS-Doctors", DOCTOR_PAYLOAD, ["domain:clinical", "clearance:l2"])
        doctor_out = ex.extract_from_episode(rd.episode, rd.raw)

        ra = ing.land(
            "HIS-Scheduling", APPOINTMENT_PAYLOAD, ["domain:clinical", "clearance:l2"]
        )
        appt_out = ex.extract_from_episode(ra.episode, ra.raw)

        preds = {f.predicate: f.object for f in appt_out.facts}
        self.assertEqual(preds.get("patient_entity_id"), patient_out.entity.entity_id)
        self.assertEqual(preds.get("doctor_entity_id"), doctor_out.entity.entity_id)

    @unittest.skipUnless(
        (HOSPITAL_DIR / "doctors.csv").is_file()
        and (HOSPITAL_DIR / "appointments.csv").is_file(),
        "hospital_management CSVs not present",
    )
    def test_real_appointments_csv_fully_joins(self):
        store = SemanticStore()
        reg = ConnectorRegistry()
        ingestion = IngestionService(store, domain="hospital_ops")
        dual_path = DualPathExtractor(store, residual=HeuristicResidualExtractor())
        runner = ConnectorRunner(
            store, reg, ingestion=ingestion, dual_path=dual_path,
            domain="hospital_ops", use_dual_path=True,
        )
        for fname, source_system, cid in (
            ("patients.csv", "HIS-Patients", "hosp-patients"),
            ("doctors.csv", "HIS-Doctors", "hosp-doctors"),
            ("appointments.csv", "HIS-Scheduling", "hosp-appointments"),
        ):
            conn = CsvDropConnector(
                path=str(HOSPITAL_DIR / fname),
                connector_id=cid,
                source_system=source_system,
                default_acl=["domain:clinical", "clearance:l2"],
            )
            reg.register(conn)
            runner.poll_one(cid)

        appts = [e for e in store.entities.values() if e.entity_type == "Appointment"]
        self.assertEqual(len(appts), 200)
        for ent in appts:
            preds = {f.predicate for f in store.facts_for_entity(ent.entity_id)}
            self.assertIn("patient_entity_id", preds)
            self.assertIn("doctor_entity_id", preds)


if __name__ == "__main__":
    unittest.main()
