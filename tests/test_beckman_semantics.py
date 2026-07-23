"""Beckman Coulter AU5800 RS-232 serial stream semantics: instrument data
format support (docs/Instrument_Data_Format.md item 6)."""

from __future__ import annotations

import os
import unittest

from synapse.beckman_semantics import extract_beckman_fields, extract_beckman_rows, looks_like_beckman
from synapse.profiling import _extract_field_values
from synapse.row_extraction import extract_rows
from synapse.models import RawObject

_REAL_FILE = os.path.join("Instrument Data", "instrument_beckman_au5800.txt")

SAMPLE_PAYLOAD = (
    "# BECKMAN COULTER AU5800 HIGH-THROUGHPUT CHEMISTRY ANALYZER - RAW RS232 STREAM LOG\n"
    "# FORMAT: [STX] | SAMPLE_ID | RACK_NO | TUBE_POS | CHANNEL_ID | ASSAY_ABBR "
    "| RAW_ABSORBANCE | CALCULATED_VAL | UNITS | REAGENT_FLAG | [ETX]\n"
    "[STX]|BC-AU58-50001|RK001|P1|CH006|UA|ABS:1.2450|VAL:5.08|mg/dL|FLAG:PROZONE_WARN|[ETX]\n"
    "[STX]|BC-AU58-50001|RK001|P1|CH005|ALP|ABS:0.6871|VAL:142.86|U/L|FLAG:OK|[ETX]\n"
    "[STX]|BC-AU58-50002|RK001|P2|CH006|UA|ABS:1.8180|VAL:4.98|mg/dL|FLAG:OK|[ETX]\n"
)


class TestBeckmanDetection(unittest.TestCase):
    def test_looks_like_beckman_true_for_real_payload(self):
        self.assertTrue(looks_like_beckman(SAMPLE_PAYLOAD))

    def test_looks_like_beckman_false_for_hl7(self):
        self.assertFalse(looks_like_beckman("MSH|^~\\&|LIS|CityLab||GeneralHospital|202601\n"))

    def test_looks_like_beckman_false_for_csv_style_kv(self):
        self.assertFalse(looks_like_beckman("sample_id: BC-1\nvalue: 5.0\n"))

    def test_looks_like_beckman_false_for_empty(self):
        self.assertFalse(looks_like_beckman(""))


class TestBeckmanFieldExtraction(unittest.TestCase):
    def test_all_body_fields_extracted_with_real_names(self):
        fields = extract_beckman_fields(SAMPLE_PAYLOAD)
        self.assertEqual(
            set(fields.keys()),
            {
                "sample_id",
                "rack_no",
                "tube_pos",
                "channel_id",
                "assay_abbr",
                "raw_absorbance",
                "calculated_value",
                "units",
                "reagent_flag",
            },
        )

    def test_kv_prefixed_tokens_stripped_of_key_prefix(self):
        fields = extract_beckman_fields(SAMPLE_PAYLOAD)
        self.assertIn("1.2450", fields["raw_absorbance"])
        self.assertIn("5.08", fields["calculated_value"])
        self.assertIn("PROZONE_WARN", fields["reagent_flag"])
        # Not left with the "ABS:"/"VAL:"/"FLAG:" prefix still attached.
        self.assertNotIn("ABS:1.2450", fields["raw_absorbance"])

    def test_bare_units_token_extracted_without_prefix(self):
        fields = extract_beckman_fields(SAMPLE_PAYLOAD)
        self.assertIn("mg/dL", fields["units"])
        self.assertIn("U/L", fields["units"])

    def test_comment_lines_produce_no_records(self):
        fields = extract_beckman_fields(SAMPLE_PAYLOAD)
        self.assertEqual(len(fields["sample_id"]), 3)  # 3 data lines, 2 comment lines skipped

    def test_via_extract_field_values_dispatch(self):
        fields = _extract_field_values(SAMPLE_PAYLOAD)
        self.assertEqual(len(fields.get("sample_id", [])), 3)

    def test_type_filter_returns_empty_flat_format_has_no_subsources(self):
        fields = _extract_field_values(SAMPLE_PAYLOAD, type_filter="anything")
        self.assertEqual(fields, {})


class TestBeckmanRowExtraction(unittest.TestCase):
    def test_one_row_per_stx_etx_line(self):
        rows = extract_beckman_rows(SAMPLE_PAYLOAD)
        self.assertEqual(len(rows), 3)

    def test_row_keeps_all_fields_together(self):
        rows = extract_beckman_rows(SAMPLE_PAYLOAD)
        first = rows[0]
        self.assertEqual(first["sample_id"], "BC-AU58-50001")
        self.assertEqual(first["assay_abbr"], "UA")
        self.assertEqual(first["raw_absorbance"], "1.2450")
        self.assertEqual(first["calculated_value"], "5.08")
        self.assertEqual(first["units"], "mg/dL")
        self.assertEqual(first["reagent_flag"], "PROZONE_WARN")

    def test_via_row_extraction_dispatch(self):
        raw = RawObject.create(source_system="Beckman", payload=SAMPLE_PAYLOAD, acl_tags=[])
        rows = extract_rows([raw])
        self.assertEqual(len(rows), 3)


@unittest.skipUnless(os.path.exists(_REAL_FILE), "Instrument Data/ is a local, untracked upload -- not present in every checkout")
class TestBeckmanRealFile(unittest.TestCase):
    def test_real_sample_file_fully_parses(self):
        with open(_REAL_FILE, encoding="utf-8") as f:
            content = f.read()
        fields = extract_beckman_fields(content)
        self.assertEqual(len(fields["sample_id"]), 516)
        rows = extract_beckman_rows(content)
        self.assertEqual(len(rows), 516)


if __name__ == "__main__":
    unittest.main()
