"""HL7v2 parser unit tests (Active_File.md task 11)."""

from __future__ import annotations

import unittest

from synapse.hl7v2 import Hl7ParseError, looks_like_hl7, parse_hl7_message

MSG = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG00002|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd^^^^^^||6939585183\n"
    "OBR|1|ORD9002|LAB9002|CBC^Complete Blood Count^L|||20230810080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
    "OBX|2|NM|WBC^White Blood Cell Count^L||11.8|10*3/uL|4.5-11.0|H|||F\n"
)


class TestHl7v2Parser(unittest.TestCase):
    def test_looks_like_hl7(self):
        self.assertTrue(looks_like_hl7(MSG))
        self.assertFalse(looks_like_hl7("patient_id: P001\nfirst_name: David\n"))
        self.assertFalse(looks_like_hl7(""))

    def test_declared_separators_used_not_hardcoded(self):
        msg = parse_hl7_message(MSG)
        self.assertEqual(msg.field_sep, "|")
        self.assertEqual(msg.component_sep, "^")
        self.assertEqual(msg.repetition_sep, "~")
        self.assertEqual(msg.escape_char, "\\")
        self.assertEqual(msg.subcomponent_sep, "&")

    def test_msh_message_type(self):
        msg = parse_hl7_message(MSG)
        msh = msg.first("MSH")
        self.assertIsNotNone(msh)
        self.assertEqual(msh.value(9, 1), "ORU")
        self.assertEqual(msh.value(9, 2), "R01")

    def test_pid_fields(self):
        msg = parse_hl7_message(MSG)
        pid = msg.first("PID")
        self.assertEqual(pid.value(3, 1), "P001")
        self.assertEqual(pid.value(5, 1), "Williams")
        self.assertEqual(pid.value(5, 2), "David")
        self.assertEqual(pid.value(7), "19550604")
        self.assertEqual(pid.value(8), "F")

    def test_multiple_obx_segments(self):
        msg = parse_hl7_message(MSG)
        obx_rows = msg.get("OBX")
        self.assertEqual(len(obx_rows), 2)
        self.assertEqual(obx_rows[0].value(3, 1), "HGB")
        self.assertEqual(obx_rows[0].value(5), "14.2")
        self.assertEqual(obx_rows[1].value(3, 1), "WBC")
        self.assertEqual(obx_rows[1].value(8), "H")  # abnormal flag

    def test_crlf_and_lf_segment_separators_both_handled(self):
        crlf_msg = MSG.replace("\n", "\r\n")
        parsed = parse_hl7_message(crlf_msg)
        self.assertEqual(len(parsed.segments), 5)

    def test_non_hl7_text_raises_parse_error(self):
        with self.assertRaises(Hl7ParseError):
            parse_hl7_message("patient_id: P001\nfirst_name: David\n")

    def test_empty_text_raises_parse_error(self):
        with self.assertRaises(Hl7ParseError):
            parse_hl7_message("")

    def test_missing_field_returns_empty_not_crash(self):
        msg = parse_hl7_message(MSG)
        pid = msg.first("PID")
        self.assertEqual(pid.value(99), "")
        self.assertIsNone(pid.field(99))
        self.assertIsNone(msg.first("ZZZ"))

    def test_nonstandard_declared_delimiters_are_honored(self):
        """Codex review finding 4: the parser must use whatever separators
        the message itself declares in MSH-1/MSH-2, not assume ^~\\&."""
        nonstandard = (
            "MSH#@%!$#LIS#CityLab#HIS#GeneralHospital#20230810083000##ORU@R01#MSG1#P#2.5.1\n"
            "PID#1##P001@@@HIS@MR##Williams@David##19550604#F\n"
        )
        msg = parse_hl7_message(nonstandard)
        self.assertEqual(msg.field_sep, "#")
        self.assertEqual(msg.component_sep, "@")
        self.assertEqual(msg.repetition_sep, "%")
        self.assertEqual(msg.escape_char, "!")
        self.assertEqual(msg.subcomponent_sep, "$")
        pid = msg.first("PID")
        self.assertEqual(pid.value(3, 1), "P001")
        self.assertEqual(pid.value(5, 1), "Williams")
        msh = msg.first("MSH")
        self.assertEqual(msh.value(9, 1), "ORU")
        self.assertEqual(msh.value(9, 2), "R01")


if __name__ == "__main__":
    unittest.main()
