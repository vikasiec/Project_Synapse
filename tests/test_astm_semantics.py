"""ASTM E1394/E1381 pipe-delimited record semantics: instrument data
format support (docs/Instrument_Data_Format.md item 1, Roche Cobas 8000
and similar). Real field names, not positional codes, and auto-confirmed
positional structural links (Patient -> Order -> Result), same discipline
as hl7_semantics.py."""

from __future__ import annotations

import os
import unittest

from synapse.astm_semantics import (
    STRUCTURAL_LINKS,
    auto_link_structure,
    extract_astm_by_record,
    extract_astm_rows,
    list_astm_record_types,
    looks_like_astm,
)
from synapse.models import RawObject
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore

_REAL_FILE = os.path.join("Instrument Data", "instrument_roche_cobas_8000.txt")

# Two patient blocks -- proves the positional patient/specimen correlation
# resets correctly at each new P record, not just accumulates forever.
PAYLOAD = (
    "H|\\^&|||Roche Diagnostics^Cobas 8000^v5.02|||||||P|1|20260722080000\n"
    "P|1|PAT-ROCHE-5001|||Hernandez^Thomas||20001201|M\n"
    "O|1|BC-ROCHE-10001||^^^CREP2\\^^^TSH3|R|20260722080200|||||N||||SERUM|||||||F\n"
    "R|1|^^^CREP2|0.98|mg/dL|0.6^1.3|N||F|||20260722080200|DEV-COBAS8000-c702\n"
    "R|2|^^^TSH3|3.32|uIU/mL|0.4^4.2|N||F|||20260722080200|DEV-COBAS8000-c702\n"
    "P|2|PAT-ROCHE-5002|||Chen^Amy||19900821|F\n"
    "O|1|BC-ROCHE-10002||^^^ASTL|R|20260722080400|||||N||||SERUM|||||||F\n"
    "R|1|^^^ASTL|71.38|U/L|10.0^40.0|H||F|||20260722080400|DEV-COBAS8000-c702\n"
    "L|1|N\n"
)


class TestAstmDetection(unittest.TestCase):
    def test_looks_like_astm_true(self):
        self.assertTrue(looks_like_astm(PAYLOAD))

    def test_looks_like_astm_false_for_hl7(self):
        self.assertFalse(looks_like_astm("MSH|^~\\&|LIS|CityLab||GeneralHospital|202601\n"))

    def test_looks_like_astm_false_for_beckman(self):
        self.assertFalse(looks_like_astm("[STX]|BC-1|RK001|P1|CH1|UA|ABS:1.0|VAL:5.0|mg/dL|FLAG:OK|[ETX]\n"))

    def test_looks_like_astm_false_for_empty(self):
        self.assertFalse(looks_like_astm(""))


class TestAstmRecordExtraction(unittest.TestCase):
    def test_record_types_present(self):
        self.assertEqual(set(list_astm_record_types(PAYLOAD)), {"H", "P", "O", "R", "L"})

    def test_real_field_names_not_positional_codes(self):
        by_record = extract_astm_by_record(PAYLOAD)
        self.assertIn("patient_id", by_record["P"])
        self.assertIn("test_code", by_record["R"])
        self.assertIn("result_value", by_record["R"])
        self.assertNotIn("P.2", by_record["P"])

    def test_patient_name_split_into_last_first(self):
        by_record = extract_astm_by_record(PAYLOAD)
        self.assertIn("Hernandez", by_record["P"]["patient_last_name"])
        self.assertIn("Thomas", by_record["P"]["patient_first_name"])

    def test_reference_range_split_into_low_high(self):
        by_record = extract_astm_by_record(PAYLOAD)
        self.assertIn("0.6", by_record["R"]["reference_range_low"])
        self.assertIn("1.3", by_record["R"]["reference_range_high"])

    def test_repeating_r_within_one_order_all_counted(self):
        by_record = extract_astm_by_record(PAYLOAD)
        self.assertEqual(len(by_record["R"]["test_code"]), 3)  # CREP2, TSH3, ASTL

    def test_order_captures_all_ordered_test_codes(self):
        by_record = extract_astm_by_record(PAYLOAD)
        self.assertIn("CREP2, TSH3", by_record["O"]["ordered_test_codes"])

    def test_unknown_record_type_produces_no_fields(self):
        # A stray, non-ASTM-record-type line is simply skipped, not errored.
        payload = PAYLOAD + "X|garbage|line\n"
        by_record = extract_astm_by_record(payload)
        self.assertNotIn("X", by_record)


class TestAstmPositionalCorrelation(unittest.TestCase):
    def test_result_carries_its_own_patient_and_specimen_id(self):
        rows = extract_astm_rows(PAYLOAD)
        r_rows = rows["R"]
        self.assertEqual(r_rows[0]["astm_patient_id"], "PAT-ROCHE-5001")
        self.assertEqual(r_rows[0]["astm_specimen_id"], "BC-ROCHE-10001")
        self.assertEqual(r_rows[2]["astm_patient_id"], "PAT-ROCHE-5002")
        self.assertEqual(r_rows[2]["astm_specimen_id"], "BC-ROCHE-10002")

    def test_order_carries_its_own_patient_id(self):
        rows = extract_astm_rows(PAYLOAD)
        self.assertEqual(rows["O"][0]["astm_patient_id"], "PAT-ROCHE-5001")
        self.assertEqual(rows["O"][1]["astm_patient_id"], "PAT-ROCHE-5002")

    def test_correlation_resets_at_each_new_patient_block(self):
        # Second patient's results must never carry the first patient's ids.
        rows = extract_astm_rows(PAYLOAD)
        for r in rows["R"][2:]:
            self.assertNotEqual(r["astm_patient_id"], "PAT-ROCHE-5001")


class TestAstmStructuralAutoLink(unittest.TestCase):
    def _seeded(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        store.put_raw(
            RawObject.create(source_system="Roche", payload=PAYLOAD, acl_tags=["domain:sre", "clearance:l2"])
        )
        return store, ontology

    def test_every_structural_link_rule_produces_a_confirmed_edge(self):
        store, ontology = self._seeded()
        edges = auto_link_structure(store, ontology, "Roche")
        self.assertEqual(len(edges), len(STRUCTURAL_LINKS))
        for edge in edges:
            self.assertEqual(edge.tier, "L1")
            self.assertIsNotNone(edge.accepted_at)

    def test_re_running_is_idempotent_no_duplicates(self):
        store, ontology = self._seeded()
        auto_link_structure(store, ontology, "Roche")
        before = len(ontology.relationships)
        auto_link_structure(store, ontology, "Roche")
        self.assertEqual(len(ontology.relationships), before)


@unittest.skipUnless(os.path.exists(_REAL_FILE), "Instrument Data/ is a local, untracked upload -- not present in every checkout")
class TestAstmRealFile(unittest.TestCase):
    def test_real_sample_file_fully_parses(self):
        with open(_REAL_FILE, encoding="utf-8") as f:
            content = f.read()
        rows = extract_astm_rows(content)
        self.assertEqual(len(rows["P"]), 104)
        self.assertEqual(len(rows["O"]), 104)
        self.assertEqual(len(rows["R"]), 421)
        for r in rows["R"]:
            self.assertIn("astm_patient_id", r)
            self.assertIn("astm_specimen_id", r)


if __name__ == "__main__":
    unittest.main()
