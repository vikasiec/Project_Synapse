"""HL7v2 segment/field semantics for profiling -- real field names, not
positional codes, and auto-confirmed structural relationships between
segments (Patient -> Order -> Observation), not one flat source."""

from __future__ import annotations

import unittest

from synapse.hl7_semantics import (
    STRUCTURAL_LINKS,
    auto_link_structure,
    extract_hl7_by_segment,
    list_hl7_segments,
    migrate_legacy_field_names,
)
from synapse.models import RawObject
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore

# Two messages, the second with a repeating OBX (two results in one order)
# -- proves repetition within a message still accumulates onto the same
# columnar field, and the hl7_message_id join key is correctly shared
# across every segment of that one message.
MSG1 = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG00001|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F\n"
    "ORC|RE|ORD9001|||||^^^20230810083000\n"
    "OBR|1|ORD9001|LAB9001|CBC^Complete Blood Count^L|||20230810080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N\n"
)
MSG2 = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810091500||ORU^R01|MSG00002|P|2.5.1\n"
    "PID|1||P002^^^HIS^MR||Chen^Amy||19620311|F\n"
    "ORC|RE|ORD9002|||||^^^20230810091500\n"
    "OBR|1|ORD9002|LAB9002|CBC^Complete Blood Count^L|||20230810090000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||13.1|g/dL|13.5-17.5|L\n"
    "OBX|2|NM|WBC^White Blood Cell Count^L||11.8|10*3/uL|4.5-11.0|H\n"
)
PAYLOAD = MSG1 + MSG2


class TestHl7SegmentExtraction(unittest.TestCase):
    def test_segments_present(self):
        self.assertEqual(list_hl7_segments(PAYLOAD), ["MSH", "OBR", "OBX", "ORC", "PID"])

    def test_non_hl7_payload_returns_no_segments(self):
        self.assertEqual(list_hl7_segments("cust_id: 123\nname: bob\n"), [])

    def test_msh_fields_get_real_names_not_positional_codes(self):
        by_segment = extract_hl7_by_segment(PAYLOAD)
        msh = by_segment["MSH"]
        self.assertIn("message_type", msh)
        self.assertIn("message_control_id", msh)
        self.assertIn("version_id", msh)
        self.assertEqual(msh["message_control_id"], ["MSG00001", "MSG00002"])
        # No raw positional field survives under the old "MSH.9"/"MSH.10" naming.
        self.assertNotIn("9", msh)
        self.assertNotIn("10", msh)

    def test_pid_composite_fields_split_into_real_subcolumns(self):
        by_segment = extract_hl7_by_segment(PAYLOAD)
        pid = by_segment["PID"]
        # patient_id is the bare id (component 1), not the full
        # "P001^^^HIS^MR" composite blob -- this is what lets it actually
        # value-match a plain patientid/pid column from another source.
        self.assertEqual(pid["patient_id"], ["P001", "P002"])
        self.assertEqual(pid["patient_id_authority"], ["HIS", "HIS"])
        self.assertEqual(pid["patient_last_name"], ["Williams", "Chen"])
        self.assertEqual(pid["patient_first_name"], ["David", "Amy"])

    def test_obx_ce_field_splits_into_code_text_system(self):
        by_segment = extract_hl7_by_segment(PAYLOAD)
        obx = by_segment["OBX"]
        self.assertEqual(obx["test_code"], ["HGB", "HGB", "WBC"])
        self.assertEqual(obx["test_name"], ["Hemoglobin", "Hemoglobin", "White Blood Cell Count"])
        self.assertEqual(obx["test_coding_system"], ["L", "L", "L"])

    def test_repeating_obx_within_one_message_all_counted(self):
        # MSG2 has two OBX segments -- both must contribute, not just the first.
        by_segment = extract_hl7_by_segment(PAYLOAD)
        self.assertEqual(len(by_segment["OBX"]["observation_value"]), 3)
        self.assertEqual(by_segment["OBX"]["observation_value"], ["14.2", "13.1", "11.8"])

    def test_hl7_message_id_shared_across_segments_of_same_message(self):
        by_segment = extract_hl7_by_segment(PAYLOAD)
        # Every non-MSH segment instance carries its own message's MSH-10,
        # letting normal value-overlap matching discover "same message"
        # without any new relationship machinery.
        self.assertEqual(by_segment["PID"]["hl7_message_id"], ["MSG00001", "MSG00002"])
        self.assertEqual(by_segment["ORC"]["hl7_message_id"], ["MSG00001", "MSG00002"])
        self.assertEqual(by_segment["OBR"]["hl7_message_id"], ["MSG00001", "MSG00002"])
        # 3 OBX total (1 + 2 repeats) -> 3 hl7_message_id entries.
        self.assertEqual(by_segment["OBX"]["hl7_message_id"], ["MSG00001", "MSG00002", "MSG00002"])
        self.assertNotIn("hl7_message_id", by_segment["MSH"])

    def test_unknown_segment_field_falls_back_to_positional_naming(self):
        # NTE is known but a field index beyond what's mapped still isn't
        # silently dropped -- falls back to "N", same guarantee as before.
        payload = MSG1 + "NTE|1|L|A free-text comment|RE\n"
        by_segment = extract_hl7_by_segment(payload)
        self.assertIn("comment", by_segment["NTE"])
        self.assertIn("4", by_segment["NTE"])  # comment_type has no canonical name mapped


class TestHl7StructuralAutoLink(unittest.TestCase):
    def setUp(self):
        self.store = SemanticStore()
        self.store.put_raw(
            RawObject.create(source_system="HL7", payload=PAYLOAD, acl_tags=["domain:clinical", "clearance:l2"])
        )
        self.ontology = OntologyRegistry.default()
        self.ontology.store = self.store

    def test_every_structural_link_rule_produces_a_confirmed_edge(self):
        created = auto_link_structure(self.store, self.ontology, "HL7")
        self.assertEqual(len(created), len(STRUCTURAL_LINKS))
        for edge in created:
            self.assertEqual(edge.predicate, "FOREIGN_KEY_TO")
            self.assertIn("Structural HL7 message linkage", " ".join(edge.match_reasons))

    def test_structural_links_are_immediately_confirmed_not_candidates(self):
        auto_link_structure(self.store, self.ontology, "HL7")
        pid_msh = self.ontology.find_relationship_by_pair(
            {"source_system": "HL7::PID", "field_name": "hl7_message_id"},
            {"source_system": "HL7::MSH", "field_name": "message_control_id"},
        )
        self.assertIsNotNone(pid_msh)
        obr_obx = self.ontology.find_relationship_by_pair(
            {"source_system": "HL7::OBR", "field_name": "test_code"},
            {"source_system": "HL7::OBX", "field_name": "test_code"},
        )
        self.assertIsNotNone(obr_obx)

    def test_re_running_is_idempotent_no_duplicates(self):
        first = auto_link_structure(self.store, self.ontology, "HL7")
        second = auto_link_structure(self.store, self.ontology, "HL7")
        self.assertEqual(len(second), 0)
        self.assertEqual(len(self.ontology.relationships), len(first))

    def test_missing_segment_skips_its_rules_gracefully(self):
        # A source with only MSH+PID (no order/result segments) shouldn't
        # error -- just produces fewer links.
        store = SemanticStore()
        store.put_raw(
            RawObject.create(
                source_system="HL7Partial",
                payload="MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG1|P|2.5.1\nPID|1||P001^^^HIS^MR||Williams^David\n",
                acl_tags=["domain:clinical", "clearance:l2"],
            )
        )
        ontology = OntologyRegistry.default()
        ontology.store = store
        created = auto_link_structure(store, ontology, "HL7Partial")
        self.assertEqual(len(created), 1)  # only PID<->MSH
        self.assertEqual(created[0].source_a["source_system"], "HL7Partial::PID")


class TestLegacyFieldMigration(unittest.TestCase):
    def test_old_flat_hl7_edge_is_rewritten_in_place(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        edge = ontology.accept_relationship(
            candidate_id="cand-1",
            source_a={"source_system": "new_data_hl7_v2_oru_r01", "field_name": "OBX.5"},
            source_b={"source_system": "new_data_mw_results", "field_name": "numericvalue"},
            predicate="SAME_ENTITY_AS",
        )
        rewritten = migrate_legacy_field_names(store, ontology)
        self.assertEqual(rewritten, 1)
        updated = ontology.relationships[edge.relationship_id]
        self.assertEqual(updated.source_a, {"source_system": "new_data_hl7_v2_oru_r01::OBX", "field_name": "observation_value"})
        self.assertEqual(updated.source_b, {"source_system": "new_data_mw_results", "field_name": "numericvalue"})
        self.assertEqual(updated.relationship_id, edge.relationship_id)

    def test_second_run_is_a_no_op(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ontology.accept_relationship(
            candidate_id="cand-1",
            source_a={"source_system": "new_data_hl7_v2_oru_r01", "field_name": "ORC.2"},
            source_b={"source_system": "new_data_lis_orders", "field_name": "ord_no"},
            predicate="SAME_ENTITY_AS",
        )
        migrate_legacy_field_names(store, ontology)
        second_pass = migrate_legacy_field_names(store, ontology)
        self.assertEqual(second_pass, 0)

    def test_unaffected_edge_is_left_alone(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        edge = ontology.accept_relationship(
            candidate_id="cand-1",
            source_a={"source_system": "SourceA", "field_name": "id"},
            source_b={"source_system": "SourceB", "field_name": "id"},
            predicate="SAME_ENTITY_AS",
        )
        migrate_legacy_field_names(store, ontology)
        self.assertEqual(ontology.relationships[edge.relationship_id].source_a, {"source_system": "SourceA", "field_name": "id"})


if __name__ == "__main__":
    unittest.main()
