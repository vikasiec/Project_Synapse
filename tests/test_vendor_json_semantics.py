"""Generic vendor JSON with a nested repeating group: instrument data
format support (docs/Instrument_Data_Format.md item 5, Abbott Alinity and
similar). Splits envelope (primary record) from content (nested child
records) instead of silently merging every child's fields into one shared
bucket, same treatment _flatten_fhir_bundle_by_type gives Bundle+Observation."""

from __future__ import annotations

import json
import os
import unittest

from synapse.vendor_json_semantics import (
    auto_link_structure,
    detect_nested_vendor_json,
    extract_nested_vendor_json_rows,
    flatten_nested_vendor_json_by_type,
    looks_like_nested_vendor_json,
)
from synapse.models import RawObject
from synapse.ontology import OntologyRegistry
from synapse.profiling import _extract_field_values, list_virtual_sources
from synapse.store import SemanticStore

_REAL_FILE = os.path.join("Instrument Data", "instrument_abbott_alinity_raw.json")

SAMPLE = {
    "alinityBatchExport": [
        {
            "specimenBarcode": "BC-1",
            "patientIdentifier": "PAT-1",
            "results": [
                {"assayCode": "GLU", "assayName": "Glucose", "resultValue": 100.0},
                {"assayCode": "TRIG", "assayName": "Triglycerides", "resultValue": 150.0},
            ],
        },
        {
            "specimenBarcode": "BC-2",
            "patientIdentifier": "PAT-2",
            "results": [
                {"assayCode": "GLU", "assayName": "Glucose", "resultValue": 95.0},
            ],
        },
    ]
}


class TestNestedVendorJsonDetection(unittest.TestCase):
    def test_detects_real_shape(self):
        detected = detect_nested_vendor_json(SAMPLE)
        self.assertIsNotNone(detected)
        primary_name, records, child_name = detected
        self.assertEqual(primary_name, "alinityBatchExport")
        self.assertEqual(len(records), 2)
        self.assertEqual(child_name, "results")

    def test_does_not_misfire_on_plain_json(self):
        self.assertFalse(looks_like_nested_vendor_json({"a": 1, "b": "text"}))

    def test_does_not_misfire_on_simple_scalar_list(self):
        self.assertFalse(looks_like_nested_vendor_json({"items": [1, 2, 3]}))

    def test_does_not_misfire_on_flat_list_of_dicts_no_nesting(self):
        # A plain list of records with no nested repeating child group --
        # ordinary JSON, must not be treated as this shape.
        self.assertFalse(looks_like_nested_vendor_json({"records": [{"a": 1}, {"a": 2}]}))

    def test_does_not_misfire_on_multi_key_top_level_dict(self):
        # Detection requires exactly one top-level key -- a multi-key dict
        # even with a nested-list field somewhere isn't this shape.
        shape = {"meta": {}, "alinityBatchExport": SAMPLE["alinityBatchExport"]}
        self.assertFalse(looks_like_nested_vendor_json(shape))

    def test_does_not_misfire_on_fhir_bundle_shape(self):
        bundle = {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": "Observation"}}]}
        self.assertFalse(looks_like_nested_vendor_json(bundle))


class TestNestedVendorJsonColumnExtraction(unittest.TestCase):
    def test_splits_into_two_virtual_sources(self):
        by_type = flatten_nested_vendor_json_by_type(SAMPLE)
        self.assertEqual(set(by_type.keys()), {"alinityBatchExport", "results"})

    def test_child_field_values_not_merged_across_different_assay_types(self):
        by_type = flatten_nested_vendor_json_by_type(SAMPLE)
        results = by_type["results"]
        self.assertEqual(len(results["resultValue"]), 3)  # 2 + 1, correctly all present
        self.assertEqual(results["assayCode"], ["GLU", "TRIG", "GLU"])

    def test_child_carries_natural_join_key_back_to_specimen(self):
        by_type = flatten_nested_vendor_json_by_type(SAMPLE)
        results = by_type["results"]
        self.assertIn("alinityBatchExport_id", results)
        self.assertEqual(results["alinityBatchExport_id"], ["BC-1", "BC-1", "BC-2"])

    def test_via_extract_field_values_dispatch_with_type_filter(self):
        payload = json.dumps(SAMPLE)
        primary = _extract_field_values(payload, type_filter="alinityBatchExport")
        self.assertIn("specimenBarcode", primary)
        child = _extract_field_values(payload, type_filter="results")
        self.assertIn("resultValue", child)

    def test_no_type_filter_returns_empty_same_rule_as_fhir_bundle(self):
        payload = json.dumps(SAMPLE)
        self.assertEqual(_extract_field_values(payload), {})

    def test_list_virtual_sources_reports_both(self):
        payload = json.dumps(SAMPLE)
        self.assertEqual(set(list_virtual_sources(payload)), {"alinityBatchExport", "results"})


class TestNestedVendorJsonRowExtraction(unittest.TestCase):
    def test_one_row_per_child_record_with_correct_pairing(self):
        rows = extract_nested_vendor_json_rows(SAMPLE)
        results = rows["results"]
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["assayCode"], "GLU")
        self.assertEqual(results[0]["resultValue"], "100.0")
        self.assertEqual(results[1]["assayCode"], "TRIG")
        self.assertEqual(results[1]["resultValue"], "150.0")

    def test_row_carries_join_keys_back_to_its_own_specimen(self):
        rows = extract_nested_vendor_json_rows(SAMPLE)
        results = rows["results"]
        self.assertEqual(results[0]["alinityBatchExport_id"], "BC-1")
        self.assertEqual(results[2]["alinityBatchExport_id"], "BC-2")

    def test_primary_rows_one_per_specimen(self):
        rows = extract_nested_vendor_json_rows(SAMPLE)
        self.assertEqual(len(rows["alinityBatchExport"]), 2)


class TestVendorJsonStructuralAutoLink(unittest.TestCase):
    """Real gap this covers: the envelope<->content join key was injected
    into every row (test_row_carries_join_keys_back_to_its_own_specimen
    above), but nothing was ever auto-confirming it as a real relationship
    the way HL7/FHIR/ASTM's own structural facts are -- caught live via
    "why do alinityBatchExport and results show no relationship at all,"
    same class of gap as everywhere else in this session where a fact
    about a file's own structure was silently left as a candidate."""

    def _seeded(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        store.put_raw(
            RawObject.create(source_system="Abbott", payload=json.dumps(SAMPLE), acl_tags=["domain:sre", "clearance:l2"])
        )
        return store, ontology

    def test_confirms_envelope_to_content_link(self):
        store, ontology = self._seeded()
        edges = auto_link_structure(store, ontology, "Abbott")
        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual(edge.predicate, "FOREIGN_KEY_TO")
        systems = {edge.source_a["source_system"], edge.source_b["source_system"]}
        self.assertEqual(systems, {"Abbott::alinityBatchExport", "Abbott::results"})

    def test_idempotent_no_duplicate_on_second_run(self):
        store, ontology = self._seeded()
        auto_link_structure(store, ontology, "Abbott")
        before = len(ontology.relationships)
        auto_link_structure(store, ontology, "Abbott")
        self.assertEqual(len(ontology.relationships), before)

    def test_no_op_for_a_non_nested_source(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        store.put_raw(
            RawObject.create(source_system="PlainJson", payload=json.dumps({"a": 1, "b": 2}), acl_tags=["domain:sre", "clearance:l2"])
        )
        edges = auto_link_structure(store, ontology, "PlainJson")
        self.assertEqual(edges, [])


@unittest.skipUnless(os.path.exists(_REAL_FILE), "Instrument Data/ is a local, untracked upload -- not present in every checkout")
class TestNestedVendorJsonRealFile(unittest.TestCase):
    def test_real_sample_file_splits_correctly(self):
        with open(_REAL_FILE, encoding="utf-8") as f:
            parsed = json.load(f)
        by_type = flatten_nested_vendor_json_by_type(parsed)
        self.assertEqual(len(by_type["alinityBatchExport"]["specimenBarcode"]), 124)
        self.assertEqual(len(by_type["results"]["resultValue"]), 370)
        rows = extract_nested_vendor_json_rows(parsed)
        for row in rows["results"]:
            self.assertIn("alinityBatchExport_id", row)


if __name__ == "__main__":
    unittest.main()
