"""HL7v2 ORU^R01 extraction (Active_File.md task 11) — real invention, not
another CSV pack. Proves cross-format entity resolution: the same patient
must resolve to one entity whether landed via CSV or HL7."""

from __future__ import annotations

import unittest
from pathlib import Path

from synapse.connectors.hl7_file import Hl7DirectoryConnector
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.session import open_session
from synapse.store import SemanticStore

MSG = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG00002|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd^^^^^^||6939585183\n"
    "OBR|1|ORD9002|LAB9002|CBC^Complete Blood Count^L|||20230810080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
    "OBX|2|NM|WBC^White Blood Cell Count^L||11.8|10*3/uL|4.5-11.0|H|||F\n"
)

HL7_DIR = Path(__file__).resolve().parents[1] / ".data" / "synthetic_hl7"


class TestHl7Extract(unittest.TestCase):
    def test_hl7_message_produces_patient_and_labresults(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land("LIS-ORU", MSG, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)

        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Patient")
        self.assertEqual(out.entity.canonical_name, "David Williams")

        hgb = store.get_entity_by_name("Hemoglobin")
        self.assertIsNotNone(hgb)
        self.assertEqual(hgb.entity_type, "LabResult")
        preds = {f.predicate: f.object for f in store.facts_for_entity(hgb.entity_id)}
        self.assertEqual(preds["result"], 14.2)
        self.assertEqual(preds["unit"], "g/dL")
        self.assertEqual(preds["abnormal_flag"], "N")
        self.assertEqual(preds["patient_entity_id"], out.entity.entity_id)

        wbc = store.get_entity_by_name("White Blood Cell Count")
        wbc_preds = {f.predicate: f.object for f in store.facts_for_entity(wbc.entity_id)}
        self.assertEqual(wbc_preds["abnormal_flag"], "H")

    def test_same_patient_resolves_across_csv_and_hl7(self):
        """The core proof: patient_id P001 landed via a CSV row and again
        via an HL7 PID segment must resolve to ONE entity, not two."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="hospital_ops")

        csv_payload = "Patient_id: P001\nFirst_name: David\nLast_name: Williams\nInsurance_provider: WellnessCorp\n"
        r1 = ing.land("HIS-Patients", csv_payload, ["domain:clinical", "clearance:l2"])
        csv_out = ex.extract_from_episode(r1.episode, r1.raw)

        r2 = ing.land("LIS-ORU", MSG, ["domain:clinical", "clearance:l2"])
        hl7_out = ex.extract_from_episode(r2.episode, r2.raw)

        self.assertEqual(csv_out.entity.entity_id, hl7_out.entity.entity_id)

    def test_non_oru_message_type_not_extracted(self):
        """Scoped to ORU^R01 — other message types (e.g. ADT) fall through
        honestly rather than being mis-parsed."""
        adt = MSG.replace("ORU^R01", "ADT^A01")
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land("LIS-ORU", adt, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNone(out)

    def test_oru_r99_trigger_not_extracted(self):
        """Codex review finding 1: MSH-9.1 == 'ORU' alone is not enough —
        MSH-9.2 must also be 'R01'. An ORU^R99 must fall through, not be
        silently treated as ORU^R01."""
        oru_r99 = MSG.replace("ORU^R01", "ORU^R99")
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land("LIS-ORU", oru_r99, ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNone(out)

    def test_two_different_patients_same_test_name_stay_distinct(self):
        """Codex review finding 3: a bare test-name/code key would let two
        different real patients' results converge into one shared entity —
        clinically wrong, and it would fabricate a false conflict between
        two unrelated people's values."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")

        msg_a = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG1|P|2.5.1\n"
            "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd||6939585183\n"
            "OBR|1|ORD1|LAB1|CBC^Complete Blood Count^L|||20230810080000\n"
            "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
        )
        msg_b = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230811090000||ORU^R01|MSG2|P|2.5.1\n"
            "PID|1||P099^^^HIS^MR||Rossi^Sofia||19800419|F|||14 Oak Dr||5550108\n"
            "OBR|1|ORD2|LAB2|CBC^Complete Blood Count^L|||20230811085000\n"
            "OBX|1|NM|HGB^Hemoglobin^L||9.1|g/dL|13.5-17.5|L|||F\n"
        )
        r1 = ing.land("LIS-ORU", msg_a, ["domain:clinical", "clearance:l2"])
        out_a = ex.extract_from_episode(r1.episode, r1.raw)
        r2 = ing.land("LIS-ORU", msg_b, ["domain:clinical", "clearance:l2"])
        out_b = ex.extract_from_episode(r2.episode, r2.raw)

        hgb_entities = [
            e for e in store.entities.values() if e.canonical_name == "Hemoglobin"
        ]
        self.assertEqual(len(hgb_entities), 2, "two patients' Hemoglobin must not merge")

        # Each entity must carry exactly one patient's result, not both.
        for ent in hgb_entities:
            values = {
                f.object for f in store.facts_for_entity(ent.entity_id) if f.predicate == "result"
            }
            self.assertEqual(len(values), 1)

        self.assertNotEqual(out_a.entity.entity_id, out_b.entity.entity_id)

    def test_malformed_hl7_falls_through_honestly(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land("LIS-ORU", "MSH|short", ["domain:clinical", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNone(out)

    @unittest.skipUnless(HL7_DIR.is_dir(), "synthetic HL7 data not present")
    def test_real_directory_full_session(self):
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
            pre_id = session.store.get_entity_by_name("David Williams").entity_id

            conn = Hl7DirectoryConnector(path=str(HL7_DIR), connector_id="hl7-test")
            session.connectors.register(conn)
            poll = session.connector_runner.poll_one("hl7-test")

            self.assertEqual(poll.events, 3)
            self.assertEqual(poll.extracted, 3)

            post = session.store.get_entity_by_name("David Williams")
            self.assertEqual(post.entity_id, pre_id)

            lab_results = [
                e for e in session.store.entities.values() if e.entity_type == "LabResult"
            ]
            self.assertEqual(len(lab_results), 6)  # 1 + 3 + 2 across the 3 messages
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
