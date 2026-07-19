"""Hospital ops vertical — Treatment + Billing, completing the full chain
Patient <- Appointment <- Treatment <- Billing (task 6)."""

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

TREATMENT_PAYLOAD = """Treatment_id: T001
Appointment_id: A001
Treatment_type: Chemotherapy
Description: Basic screening
Cost: 3941.97
Treatment_date: 2023-08-09
"""

BILLING_PAYLOAD = """Bill_id: B001
Patient_id: P034
Treatment_id: T001
Bill_date: 2023-08-09
Amount: 3941.97
Payment_method: Insurance
Payment_status: Pending
"""

HOSPITAL_DIR = (
    Path(__file__).resolve().parents[1] / ".data" / "kaggle_raw" / "hospital_management"
)


class TestTreatmentBillingExtract(unittest.TestCase):
    def test_ontology_treatment_and_billing(self):
        ont = OntologyRegistry.default()
        self.assertIn("Treatment", ont.types)
        self.assertIn("Billing", ont.types)
        self.assertEqual(ont.govern_extract("Treatment", domain="hospital_ops").ontology_type, "Treatment")
        self.assertEqual(ont.govern_extract("Billing", domain="hospital_ops").ontology_type, "Billing")

    def test_billing_row_not_mistaken_for_treatment(self):
        """billing.csv rows carry treatment_id as a foreign key but lack
        appointment_id — must never be extracted as a Treatment."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")
        r = ing.land("HIS-Billing", BILLING_PAYLOAD, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Billing")

    def test_full_chain_resolves_when_landed_in_dependency_order(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")

        patient_payload = "Patient_id: P034\nFirst_name: Test\nLast_name: Patient\nInsurance_provider: X\n"
        doctor_payload = "Doctor_id: D009\nFirst_name: Test\nLast_name: Doctor\nSpecialization: X\n"
        appt_payload = (
            "Appointment_id: A001\nPatient_id: P034\nDoctor_id: D009\n"
            "Appointment_date: 2023-08-09\nReason_for_visit: Therapy\nStatus: Scheduled\n"
        )

        for source, payload in (
            ("HIS-Patients", patient_payload),
            ("HIS-Doctors", doctor_payload),
            ("HIS-Scheduling", appt_payload),
            ("HIS-Treatments", TREATMENT_PAYLOAD),
            ("HIS-Billing", BILLING_PAYLOAD),
        ):
            r = ing.land(source, payload, ["domain:clinical", "clearance:l2"])
            ex.extract_from_episode(r.episode, r.raw)

        bill = store.get_entity_by_name("B001")
        self.assertIsNotNone(bill)
        bf = {f.predicate: f.object for f in store.facts_for_entity(bill.entity_id)}
        self.assertIn("treatment_entity_id", bf)
        self.assertIn("patient_entity_id", bf)

        treatment = store.entities.get(bf["treatment_entity_id"])
        tf = {f.predicate: f.object for f in store.facts_for_entity(treatment.entity_id)}
        self.assertIn("appointment_entity_id", tf)

        appt = store.entities.get(tf["appointment_entity_id"])
        af = {f.predicate: f.object for f in store.facts_for_entity(appt.entity_id)}
        self.assertIn("patient_entity_id", af)
        self.assertIn("doctor_entity_id", af)

        # Bill's patient and appointment's patient must be the same entity
        self.assertEqual(bf["patient_entity_id"], af["patient_entity_id"])

    @unittest.skipUnless(
        (HOSPITAL_DIR / "billing.csv").is_file()
        and (HOSPITAL_DIR / "treatments.csv").is_file(),
        "hospital_management CSVs not present",
    )
    def test_real_billing_and_treatments_fully_join(self):
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
            ("treatments.csv", "HIS-Treatments", "hosp-treatments"),
            ("billing.csv", "HIS-Billing", "hosp-billing"),
        ):
            conn = CsvDropConnector(
                path=str(HOSPITAL_DIR / fname),
                connector_id=cid,
                source_system=source_system,
                default_acl=["domain:clinical", "clearance:l2"],
            )
            reg.register(conn)
            runner.poll_one(cid)

        treatments = [e for e in store.entities.values() if e.entity_type == "Treatment"]
        billings = [e for e in store.entities.values() if e.entity_type == "Billing"]
        self.assertEqual(len(treatments), 200)
        self.assertEqual(len(billings), 200)
        for ent in treatments:
            preds = {f.predicate for f in store.facts_for_entity(ent.entity_id)}
            self.assertIn("appointment_entity_id", preds)
        for ent in billings:
            preds = {f.predicate for f in store.facts_for_entity(ent.entity_id)}
            self.assertIn("patient_entity_id", preds)
            self.assertIn("treatment_entity_id", preds)


if __name__ == "__main__":
    unittest.main()
