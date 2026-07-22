"""Row-oriented extraction: a record's fields must stay correlated (same
row), unlike profiling's column-oriented "field -> every observed value"
shape, which discards which values belonged to the same source record."""

from __future__ import annotations

import json
import unittest

from synapse.hl7_semantics import extract_hl7_rows
from synapse.models import RawObject
from synapse.profiling import extract_fhir_rows_by_type
from synapse.row_extraction import extract_rows

HL7_PAYLOAD = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG00001|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F\n"
    "OBR|1|ORD9001|LAB9001|CBC^Complete Blood Count^L|||20230810080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N\n"
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810091500||ORU^R01|MSG00002|P|2.5.1\n"
    "PID|1||P002^^^HIS^MR||Chen^Amy||19620311|F\n"
    "OBR|1|ORD9002|LAB9002|CBC^Complete Blood Count^L|||20230810090000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||13.1|g/dL|13.5-17.5|L\n"
    "OBX|2|NM|WBC^White Blood Cell Count^L||11.8|10*3/uL|4.5-11.0|H\n"
)

FHIR_BUNDLE = json.dumps(
    {
        "resourceType": "Bundle",
        "id": "bundle-1",
        "type": "collection",
        "entry": [
            {
                "fullUrl": "urn:1",
                "resource": {
                    "resourceType": "Observation",
                    "id": "O1",
                    "status": "final",
                    "valueQuantity": {"value": 5.0, "unit": "mg/dL"},
                },
            },
            {
                "fullUrl": "urn:2",
                "resource": {
                    "resourceType": "Observation",
                    "id": "O2",
                    "status": "final",
                    "valueQuantity": {"value": 7.5, "unit": "mg/dL"},
                },
            },
        ],
    }
)


class TestHl7RowExtraction(unittest.TestCase):
    def test_obx_row_keeps_its_own_fields_together(self):
        rows = extract_hl7_rows(HL7_PAYLOAD)
        self.assertEqual(len(rows["OBX"]), 3)  # 1 + 2 repeats
        first = rows["OBX"][0]
        self.assertEqual(first["observation_value"], "14.2")
        self.assertEqual(first["units"], "g/dL")
        self.assertEqual(first["hl7_message_id"], "MSG00001")

    def test_repeating_obx_rows_not_cross_contaminated(self):
        rows = extract_hl7_rows(HL7_PAYLOAD)
        # MSG00002 has two OBX (HGB then WBC) -- each must keep its OWN
        # value/units, not another repeat's, and both share MSG00002.
        hgb, wbc = rows["OBX"][1], rows["OBX"][2]
        self.assertEqual(hgb["test_code"], "HGB")
        self.assertEqual(hgb["observation_value"], "13.1")
        self.assertEqual(wbc["test_code"], "WBC")
        self.assertEqual(wbc["observation_value"], "11.8")
        self.assertEqual(hgb["hl7_message_id"], "MSG00002")
        self.assertEqual(wbc["hl7_message_id"], "MSG00002")

    def test_pid_rows_one_per_message(self):
        rows = extract_hl7_rows(HL7_PAYLOAD)
        self.assertEqual(len(rows["PID"]), 2)
        self.assertEqual(rows["PID"][0]["patient_id"], "P001")
        self.assertEqual(rows["PID"][1]["patient_id"], "P002")

    def test_column_and_row_extraction_agree_on_values(self):
        # Same underlying data, different shape -- values must match.
        from synapse.hl7_semantics import extract_hl7_by_segment

        columns = extract_hl7_by_segment(HL7_PAYLOAD)
        rows = extract_hl7_rows(HL7_PAYLOAD)
        self.assertEqual(
            sorted(r["observation_value"] for r in rows["OBX"]),
            sorted(columns["OBX"]["observation_value"]),
        )


class TestFhirRowExtraction(unittest.TestCase):
    def test_each_resource_is_its_own_row(self):
        rows = extract_fhir_rows_by_type(FHIR_BUNDLE)
        self.assertEqual(len(rows["Observation"]), 2)
        first, second = rows["Observation"]
        self.assertEqual(first["id"], "O1")
        self.assertEqual(first["valueQuantity.value"], "5.0")
        self.assertEqual(second["id"], "O2")
        self.assertEqual(second["valueQuantity.value"], "7.5")

    def test_bundle_id_present_on_every_resource_row(self):
        rows = extract_fhir_rows_by_type(FHIR_BUNDLE)
        for row in rows["Observation"]:
            self.assertEqual(row["bundle_id"], "bundle-1")

    def test_non_bundle_json_returns_empty(self):
        self.assertEqual(extract_fhir_rows_by_type(json.dumps({"resourceType": "Patient", "id": "P1"})), {})


class TestExtractRowsDispatch(unittest.TestCase):
    def test_hl7_dispatch_scoped_to_segment(self):
        raws = [RawObject.create(source_system="HL7", payload=HL7_PAYLOAD, acl_tags=[])]
        rows = extract_rows(raws, type_filter="OBX")
        self.assertEqual(len(rows), 3)

    def test_fhir_dispatch_scoped_to_resource_type(self):
        raws = [RawObject.create(source_system="FHIR", payload=FHIR_BUNDLE, acl_tags=[])]
        rows = extract_rows(raws, type_filter="Observation")
        self.assertEqual(len(rows), 2)

    def test_csv_row_per_raw_object_no_type_filter(self):
        # Mirrors how POST /v1/explore/ingest lands CSV: one RawObject
        # per row, "key: value" text payload.
        raws = [
            RawObject.create(source_system="Orders", payload="order_id: 1\nstatus: OPEN", acl_tags=[]),
            RawObject.create(source_system="Orders", payload="order_id: 2\nstatus: CLOSED", acl_tags=[]),
        ]
        rows = extract_rows(raws)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["order_id"] for r in rows}, {"1", "2"})

    def test_decomposable_source_with_no_type_filter_yields_nothing(self):
        # Consistent with _extract_field_values: requesting decomposable
        # content with no scope returns nothing rather than a silently
        # collided merge.
        raws = [RawObject.create(source_system="HL7", payload=HL7_PAYLOAD, acl_tags=[])]
        self.assertEqual(extract_rows(raws), [])


if __name__ == "__main__":
    unittest.main()
