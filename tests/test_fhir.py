"""FHIR parser unit tests (Active_File.md task 15)."""

from __future__ import annotations

import json
import unittest

from synapse.fhir import (
    FhirParseError,
    bundle_resources,
    coding_display_and_code,
    first_identifier_value,
    human_name,
    looks_like_fhir,
    parse_fhir_resource,
    reference_range_string,
    resolve_local_reference,
)

BUNDLE = {
    "resourceType": "Bundle",
    "type": "message",
    "entry": [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "p001",
                "identifier": [{"system": "urn:oid:HIS", "value": "P001"}],
                "name": [{"family": "Williams", "given": ["David"]}],
                "birthDate": "1955-06-04",
                "gender": "male",
            }
        },
        {
            "resource": {
                "resourceType": "Observation",
                "id": "obs1",
                "status": "final",
                "code": {
                    "coding": [
                        {"system": "http://loinc.org", "code": "777-3", "display": "Platelet Count"}
                    ]
                },
                "subject": {"reference": "Patient/p001"},
                "valueQuantity": {"value": 245, "unit": "10*3/uL"},
                "referenceRange": [{"low": {"value": 150}, "high": {"value": 400}}],
                "interpretation": [{"coding": [{"code": "N", "display": "Normal"}]}],
            }
        },
    ],
}


class TestFhirParser(unittest.TestCase):
    def test_looks_like_fhir(self):
        self.assertTrue(looks_like_fhir(json.dumps(BUNDLE)))
        self.assertFalse(looks_like_fhir("patient_id: P001\nfirst_name: David\n"))
        self.assertFalse(looks_like_fhir("{}"))  # JSON but no resourceType

    def test_parse_valid_bundle(self):
        data = parse_fhir_resource(json.dumps(BUNDLE))
        self.assertEqual(data["resourceType"], "Bundle")

    def test_parse_invalid_json_raises(self):
        with self.assertRaises(FhirParseError):
            parse_fhir_resource("not json at all {")

    def test_parse_json_without_resource_type_raises(self):
        with self.assertRaises(FhirParseError):
            parse_fhir_resource(json.dumps({"foo": "bar"}))

    def test_bundle_resources_extracts_both(self):
        resources = bundle_resources(BUNDLE)
        self.assertEqual(len(resources), 2)
        self.assertEqual(resources[0]["resourceType"], "Patient")
        self.assertEqual(resources[1]["resourceType"], "Observation")

    def test_resolve_local_reference(self):
        resources = bundle_resources(BUNDLE)
        patient = resolve_local_reference(resources, "Patient/p001")
        self.assertIsNotNone(patient)
        self.assertEqual(patient["id"], "p001")
        self.assertIsNone(resolve_local_reference(resources, "Patient/nonexistent"))
        self.assertIsNone(resolve_local_reference(resources, None))
        self.assertIsNone(resolve_local_reference(resources, "malformed"))

    def test_first_identifier_value(self):
        patient = bundle_resources(BUNDLE)[0]
        self.assertEqual(first_identifier_value(patient), "P001")

    def test_human_name(self):
        patient = bundle_resources(BUNDLE)[0]
        family, given = human_name(patient)
        self.assertEqual(family, "Williams")
        self.assertEqual(given, "David")

    def test_coding_display_and_code(self):
        obs = bundle_resources(BUNDLE)[1]
        display, code = coding_display_and_code(obs["code"])
        self.assertEqual(display, "Platelet Count")
        self.assertEqual(code, "777-3")
        self.assertEqual(coding_display_and_code(None), ("", ""))

    def test_reference_range_string(self):
        obs = bundle_resources(BUNDLE)[1]
        self.assertEqual(reference_range_string(obs), "150-400")
        self.assertEqual(reference_range_string({}), "")


if __name__ == "__main__":
    unittest.main()
