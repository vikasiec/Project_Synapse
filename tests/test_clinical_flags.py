"""Clinical reference-range flag evaluation: instrument data format
support (docs/Instrument_Data_Format.md item 4, "Clinical Normalization
Engine"). Verified against real values from the actual instrument files,
not synthetic-only."""

from __future__ import annotations

import unittest

from synapse.clinical_flags import (
    compute_flag,
    compute_flag_for_row,
    compute_flag_for_row_split_range,
    parse_reference_range,
)
from synapse.coding_systems import LOCAL_CODE_TO_LOINC, to_loinc


class TestParseReferenceRange(unittest.TestCase):
    def test_hyphen_form(self):
        self.assertEqual(parse_reference_range("13.5-17.5"), (13.5, 17.5))

    def test_caret_form(self):
        self.assertEqual(parse_reference_range("0.6^1.3"), (0.6, 1.3))

    def test_none_for_missing(self):
        self.assertIsNone(parse_reference_range(None))
        self.assertIsNone(parse_reference_range(""))

    def test_none_for_malformed(self):
        self.assertIsNone(parse_reference_range("not a range"))

    def test_none_when_low_greater_than_high(self):
        self.assertIsNone(parse_reference_range("100-50"))


class TestComputeFlag(unittest.TestCase):
    def test_within_range_is_normal(self):
        self.assertEqual(compute_flag(14.2, range_str="13.5-17.5"), "NORMAL")

    def test_below_range_is_low(self):
        self.assertEqual(compute_flag(13.1, range_str="13.5-17.5"), "LOW")

    def test_above_range_is_high(self):
        self.assertEqual(compute_flag(71.38, ref_low=10.0, ref_high=40.0), "HIGH")

    def test_far_above_range_is_panic(self):
        # Real value from the Siemens sample file: B12 3186.06 pg/mL
        # against 211.0-911.0 -- roughly 3.2x the range's own width beyond
        # the upper bound.
        self.assertEqual(compute_flag(3186.06, range_str="211.0-911.0"), "PANIC")

    def test_moderately_above_range_is_critical_not_just_high(self):
        # width=100, high=200 -> value 400 is 2x the width beyond the
        # bound, past the 1.5x CRITICAL threshold but short of 3x PANIC.
        self.assertEqual(compute_flag(400, ref_low=100, ref_high=200), "CRITICAL")

    def test_none_when_value_missing(self):
        self.assertIsNone(compute_flag(None, range_str="1-10"))

    def test_none_when_range_missing(self):
        self.assertIsNone(compute_flag(5.0))

    def test_none_when_range_malformed(self):
        self.assertIsNone(compute_flag(5.0, range_str="garbage"))

    def test_degenerate_zero_width_range_still_flags_direction(self):
        self.assertEqual(compute_flag(5.0, ref_low=5.0, ref_high=5.0), "NORMAL")
        self.assertEqual(compute_flag(6.0, ref_low=5.0, ref_high=5.0), "HIGH")


class TestComputeFlagForRow(unittest.TestCase):
    def test_combined_range_row(self):
        row = {"observation_value": "14.2", "reference_range": "13.5-17.5"}
        self.assertEqual(compute_flag_for_row(row, "observation_value", "reference_range"), "NORMAL")

    def test_split_range_row(self):
        row = {"result_value": "0.98", "reference_range_low": "0.6", "reference_range_high": "1.3"}
        self.assertEqual(
            compute_flag_for_row_split_range(row, "result_value", "reference_range_low", "reference_range_high"),
            "NORMAL",
        )

    def test_missing_field_returns_none(self):
        row = {"observation_value": "14.2"}
        self.assertIsNone(compute_flag_for_row(row, "observation_value", "reference_range"))


class TestLoincTranslation(unittest.TestCase):
    def test_known_codes_from_real_files(self):
        # Spot-check codes actually present in the real sample files.
        self.assertEqual(to_loinc("GLUC3"), "2345-7")  # Roche/Abbott glucose
        self.assertEqual(to_loinc("4080"), "2132-9")  # Siemens Vitamin B12
        self.assertEqual(to_loinc("WBC"), "6690-2")  # Sysmex WBC

    def test_case_insensitive(self):
        self.assertEqual(to_loinc("gluc3"), "2345-7")

    def test_unknown_code_returns_none(self):
        self.assertIsNone(to_loinc("NOT-A-REAL-CODE"))

    def test_missing_code_returns_none(self):
        self.assertIsNone(to_loinc(None))
        self.assertIsNone(to_loinc(""))

    def test_every_entry_is_a_plausible_loinc_shape(self):
        # LOINC codes are digits-hyphen-checkdigit (e.g. "2345-7") --
        # a cheap sanity check that no entry is obviously malformed.
        import re

        loinc_shape = re.compile(r"^\d+-\d$")
        for local_code, loinc in LOCAL_CODE_TO_LOINC.items():
            self.assertRegex(loinc, loinc_shape, f"{local_code} -> {loinc} doesn't look like a LOINC code")


if __name__ == "__main__":
    unittest.main()
