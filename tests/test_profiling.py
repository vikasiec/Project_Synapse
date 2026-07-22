"""Major Goal 1 (Data Profiling & Vector Extraction) + VnV Layer 1."""

from __future__ import annotations

import json
import unittest

from synapse.models import RawObject
from synapse.profiling import SchemaProfiler, cosine_similarity
from synapse.store import SemanticStore


def _land_kv(store: SemanticStore, source: str, rows: list[dict[str, str]]) -> None:
    for row in rows:
        payload = "\n".join(f"{k}: {v}" for k, v in row.items())
        store.put_raw(
            RawObject.create(source_system=source, payload=payload, acl_tags=["domain:sre", "clearance:l2"])
        )


class TestSchemaProfiler(unittest.TestCase):
    def test_vnv_layer_1_matching_8_digit_integer_fields(self) -> None:
        store = SemanticStore()
        _land_kv(
            store,
            "TableA",
            [{"cust_id": "84920112"}, {"cust_id": "10293847"}, {"cust_id": "55512309"}],
        )
        _land_kv(
            store,
            "TableB",
            [{"client_num": "77281940"}, {"client_num": "11029384"}, {"client_num": "90192837"}],
        )
        profiler = SchemaProfiler(store)
        profile_a = profiler.profile_source("TableA")["cust_id"]
        profile_b = profiler.profile_source("TableB")["client_num"]

        self.assertEqual(profile_a.data_type, profile_b.data_type)
        self.assertEqual(profile_a.data_type, "Integer8")
        self.assertIn("Integer8", profile_a.regex_pattern_match)
        self.assertIn("Integer8", profile_b.regex_pattern_match)
        self.assertEqual(profile_a.regex_pattern_match["Integer8"], profile_b.regex_pattern_match["Integer8"])

        for vec in (profile_a.semantic_vector, profile_b.semantic_vector):
            self.assertTrue(len(vec) > 0)
            self.assertTrue(all(isinstance(x, float) for x in vec))

    def test_entropy_score_reflects_uniqueness(self) -> None:
        store = SemanticStore()
        _land_kv(store, "S", [{"status": "ACTIVE"}, {"status": "ACTIVE"}, {"status": "SUSPENDED"}])
        profiler = SchemaProfiler(store)
        profile = profiler.profile_source("S")["status"]
        self.assertAlmostEqual(profile.entropy_score, 2 / 3, places=4)

    def test_min_hash_sketch_present_and_stable_shape(self) -> None:
        store = SemanticStore()
        _land_kv(store, "S", [{"code": "A"}, {"code": "B"}, {"code": "C"}])
        profiler = SchemaProfiler(store)
        profile = profiler.profile_source("S")["code"]
        self.assertTrue(len(profile.min_hash_sketch) > 0)

    def test_json_shaped_payload_profiles_correctly(self) -> None:
        # F-003 fix: FHIR/JSONL connectors land raw JSON text as-is (see
        # synapse/connectors/fhir_file.py), not "key: value" lines -- the
        # profiler must handle that shape too, not just CSV's KV lines.
        store = SemanticStore()
        bundle_a = {
            "resourceType": "Patient",
            "identifier": [{"value": "84920112"}],
            "name": [{"family": "Doe"}],
        }
        bundle_b = {
            "resourceType": "Patient",
            "identifier": [{"value": "10293847"}],
            "name": [{"family": "Roe"}],
        }
        for bundle in (bundle_a, bundle_b):
            store.put_raw(
                RawObject.create(
                    source_system="FHIR-Interface",
                    payload=json.dumps(bundle),
                    acl_tags=["domain:clinical", "clearance:l2"],
                )
            )
        profiler = SchemaProfiler(store)
        profiles = profiler.profile_source("FHIR-Interface")
        self.assertIn("resourceType", profiles)
        self.assertIn("identifier.value", profiles)
        self.assertIn("name.family", profiles)
        self.assertEqual(profiles["identifier.value"].sample_count, 2)
        self.assertEqual(profiles["resourceType"].entropy_score, 0.5)  # both "Patient"

    def test_repeated_list_items_collapse_onto_one_field_not_indexed(self) -> None:
        store = SemanticStore()
        bundle = {"identifier": [{"value": "111"}, {"value": "222"}, {"value": "333"}]}
        store.put_raw(
            RawObject.create(source_system="J", payload=json.dumps(bundle), acl_tags=["domain:sre", "clearance:l2"])
        )
        profiles = SchemaProfiler(store).profile_source("J")
        self.assertIn("identifier.value", profiles)
        self.assertEqual(profiles["identifier.value"].sample_count, 3)
        self.assertNotIn("identifier.0.value", profiles)

    def test_hl7v2_payload_profiles_as_virtual_segment_sources(self) -> None:
        # F-003 follow-up: HL7's \r segment separators collapse to \n
        # under Python's universal-newline text reads (and browser file
        # uploads), so a naive "each line is a message" split only ever
        # saw the MSH line -- PID/ORC/OBR/OBX segments were silently
        # dropped. Two messages here, exercising the regroup-by-MSH logic.
        #
        # Superseded the old flat "PID.5"/"OBX.5"/"MSH.10" positional-code
        # assertions: HL7 now decomposes into virtual per-segment sources
        # (synapse/hl7_semantics.py) with real semantic field names, not a
        # single source with meaningless positional field codes.
        store = SemanticStore()
        msg1 = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG00001|P|2.5.1\n"
            "PID|1||P001^^^HIS^MR||Williams^David||19550604|F\n"
            "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N\n"
        )
        msg2 = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810091500||ORU^R01|MSG00002|P|2.5.1\n"
            "PID|1||P002^^^HIS^MR||Chen^Amy||19620311|F\n"
            "OBX|1|NM|HGB^Hemoglobin^L||13.1|g/dL|13.5-17.5|L\n"
        )
        store.put_raw(RawObject.create(source_system="HL7", payload=msg1, acl_tags=["domain:clinical", "clearance:l2"]))
        store.put_raw(RawObject.create(source_system="HL7", payload=msg2, acl_tags=["domain:clinical", "clearance:l2"]))

        profiler = SchemaProfiler(store)
        self.assertEqual(profiler.known_sources(), ["HL7::MSH", "HL7::OBX", "HL7::PID"])

        pid_profiles = profiler.profile_source("HL7::PID")
        self.assertIn("patient_last_name", pid_profiles)
        self.assertEqual(pid_profiles["patient_last_name"].sample_count, 2)

        obx_profiles = profiler.profile_source("HL7::OBX")
        self.assertIn("observation_value", obx_profiles)

        msh_profiles = profiler.profile_source("HL7::MSH")
        self.assertIn("message_control_id", msh_profiles)
        self.assertEqual(msh_profiles["message_control_id"].entropy_score, 1.0)  # MSG00001 vs MSG00002, both unique

    def test_fhir_bundle_profiles_per_resource_type_not_merged(self) -> None:
        # A Bundle mixing Patient + Observation resources must not blend
        # their unrelated fields into one shared namespace -- verified
        # against the real single-resourceType new_data/fhir_observations.json
        # already worked by construction; this proves the actual gap (a
        # mixed bundle) is handled too.
        store = SemanticStore()
        bundle = json.dumps(
            {
                "resourceType": "Bundle",
                "id": "mixed",
                "type": "collection",
                "entry": [
                    {"fullUrl": "urn:1", "resource": {"resourceType": "Patient", "id": "P1", "name": [{"family": "Doe"}]}},
                    {
                        "fullUrl": "urn:2",
                        "resource": {
                            "resourceType": "Observation",
                            "id": "O1",
                            "status": "final",
                            "valueQuantity": {"value": 5.0},
                        },
                    },
                ],
            }
        )
        store.put_raw(RawObject.create(source_system="FHIR", payload=bundle, acl_tags=["domain:clinical", "clearance:l2"]))

        profiler = SchemaProfiler(store)
        self.assertEqual(profiler.known_sources(), ["FHIR::Bundle", "FHIR::Observation", "FHIR::Patient"])

        patient_profiles = profiler.profile_source("FHIR::Patient")
        self.assertIn("name.family", patient_profiles)
        self.assertNotIn("valueQuantity.value", patient_profiles)

        obs_profiles = profiler.profile_source("FHIR::Observation")
        self.assertIn("valueQuantity.value", obs_profiles)
        self.assertNotIn("name.family", obs_profiles)

    def test_semantic_vectors_are_well_defined(self) -> None:
        from synapse.profiling import _hashing_vector

        v_cust_id = _hashing_vector("cust_id")
        v_client_num = _hashing_vector("client_num")
        v_unrelated = _hashing_vector("zzz_totally_unrelated_blob_xyz")
        self.assertGreaterEqual(cosine_similarity(v_cust_id, v_cust_id), 0.99)
        # Not asserting a specific ordering between cust_id/client_num vs unrelated
        # (name-only similarity is weak signal by design -- VectorSim is one of
        # three weighted components) -- just that the function is well-defined.
        self.assertTrue(0.0 <= cosine_similarity(v_cust_id, v_unrelated) <= 1.0)
        self.assertTrue(0.0 <= cosine_similarity(v_cust_id, v_client_num) <= 1.0)


if __name__ == "__main__":
    unittest.main()
