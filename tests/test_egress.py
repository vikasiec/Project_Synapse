"""Canonical CSV/HL7/FHIR egress converters: instrument data format
support (docs/Instrument_Data_Format.md section 5). Built on top of an
already-materialized star-schema warehouse."""

from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from synapse.egress import export_csv_tables, export_fhir_bundle, export_hl7
from synapse.hl7_semantics import auto_link_structure, extract_hl7_by_segment
from synapse.models import RawObject
from synapse.ontology import OntologyRegistry
from synapse.profiling import SchemaProfiler
from synapse.star_schema import execute_star_schema
from synapse.store import SemanticStore
from synapse.workspace import Workspace

# Two messages, each testing a DIFFERENT analyte (unique test_code per
# message) -- deliberately avoiding the duplicate-test_code natural-key
# ambiguity documented in synapse/egress.py's _resolve_patient_row
# docstring (a pre-existing star_schema.py FK-resolution limitation when
# two different real-world orders share the same natural-key value, not
# something this egress work introduces or is meant to fix).
HL7_PAYLOAD = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG00001|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F\n"
    "ORC|RE|ORD9001|||||^^^20230810083000\n"
    "OBR|1|ORD9001|LAB9001|HGB^Hemoglobin^L|||20230810080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N\n"
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810091500||ORU^R01|MSG00002|P|2.5.1\n"
    "PID|1||P002^^^HIS^MR||Chen^Amy||19620311|F\n"
    "ORC|RE|ORD9002|||||^^^20230810091500\n"
    "OBR|1|ORD9002|LAB9002|WBC^White Blood Cell Count^L|||20230810090000\n"
    "OBX|1|NM|WBC^White Blood Cell Count^L||13.1|10*3/uL|4.5-11.0|H\n"
)


def _materialize(tmp_dir: str) -> str:
    store = SemanticStore()
    ontology = OntologyRegistry.default()
    ontology.store = store
    ws = Workspace.create("Egress Test")
    store.put_workspace(ws)
    store.put_raw(
        RawObject.create(source_system="HL7", payload=HL7_PAYLOAD, acl_tags=["domain:sre", "clearance:l2"], workspace_id=ws.workspace_id)
    )
    auto_link_structure(store, ontology, "HL7")
    profiler = SchemaProfiler(store)
    target = str(Path(tmp_dir) / "warehouse.db")
    execute_star_schema(store, ontology, profiler, [ws.workspace_id], target)
    return target


class TestCsvEgress(unittest.TestCase):
    def test_writes_one_csv_per_materialized_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            written = export_csv_tables(db_path, str(Path(tmp) / "csv_out"))
            self.assertIn("fact_obx", written)
            self.assertIn("dim_pid", written)

    def test_csv_content_matches_materialized_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            written = export_csv_tables(db_path, str(Path(tmp) / "csv_out"))
            with open(written["dim_pid"], newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual({r["patient_id"] for r in rows}, {"P001", "P002"})


class TestHl7Egress(unittest.TestCase):
    def test_produces_one_message_per_fact_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            hl7_text = export_hl7(db_path)
            self.assertEqual(hl7_text.count("MSH|"), 2)
            self.assertEqual(hl7_text.count("OBX|"), 2)

    def test_round_trips_through_our_own_extractor(self):
        # The strongest correctness check for an export path: what we
        # write out, our own parser must read back correctly.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            hl7_text = export_hl7(db_path)
            messages = [m for m in hl7_text.split("MSH|") if m.strip()]
            self.assertEqual(len(messages), 2)
            for m in messages:
                full = "MSH|" + m
                by_seg = extract_hl7_by_segment(full)
                self.assertIn(by_seg["OBX"]["observation_value"][0], ("14.2", "13.1"))
                self.assertIn(by_seg["PID"]["patient_id"][0], ("P001", "P002"))

    def test_correct_patient_attributed_to_correct_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            hl7_text = export_hl7(db_path)
            messages = ["MSH|" + m for m in hl7_text.split("MSH|") if m.strip()]
            by_patient = {}
            for full in messages:
                seg = extract_hl7_by_segment(full)
                by_patient[seg["PID"]["patient_id"][0]] = seg["OBX"]["observation_value"][0]
            self.assertEqual(by_patient["P001"], "14.2")
            self.assertEqual(by_patient["P002"], "13.1")


class TestFhirEgress(unittest.TestCase):
    def test_produces_patient_and_observation_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            bundle = export_fhir_bundle(db_path)
            self.assertEqual(bundle["resourceType"], "Bundle")
            types = [e["resource"]["resourceType"] for e in bundle["entry"]]
            self.assertEqual(types.count("Patient"), 2)
            self.assertEqual(types.count("Observation"), 2)

    def test_observation_subject_references_correct_patient(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            bundle = export_fhir_bundle(db_path)
            observations = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation"]
            values_by_patient = {
                o["subject"]["reference"].split("/")[-1]: o["valueQuantity"]["value"] for o in observations
            }
            self.assertEqual(values_by_patient["P001"], 14.2)
            self.assertEqual(values_by_patient["P002"], 13.1)

    def test_bundle_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            bundle = export_fhir_bundle(db_path)
            # round-trips through json.dumps/loads without error
            reparsed = json.loads(json.dumps(bundle))
            self.assertEqual(reparsed["resourceType"], "Bundle")


class TestNoClinicalFlagAsMeasure(unittest.TestCase):
    def test_set_id_not_exported_as_a_measure(self):
        # Real bug caught while building this: a naive "parses as float"
        # check alone would treat HL7's set_id (a sequence counter) as a
        # measurement. Must be excluded the same way star_schema.py's own
        # classification excludes it.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = _materialize(tmp)
            hl7_text = export_hl7(db_path)
            self.assertNotIn("set_id^set_id", hl7_text)


if __name__ == "__main__":
    unittest.main()
