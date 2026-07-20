"""
PID-3 / FHIR identifier assigning-authority namespacing (Active_File.md
row 23) -- the gap Codex's row-13/row-14 reviews independently flagged as
the main remaining limit on calling the HL7v2/FHIR work healthcare-grade:
two different facilities can each issue the same bare patient ID (e.g.
both call someone "P001") to two different real people, and cross-source
identity blocking by ID value alone would silently merge them.

These tests exercise the fix directly against EntityResolutionService,
separately from the HL7v2/FHIR format-specific extraction tests, because
the mechanism (normalize_authority + authority-aware
find_by_external_id_value/get_or_create) is generic core behavior, not
format-specific.
"""

from __future__ import annotations

import unittest

from synapse.entity_resolution import EntityResolutionService, normalize_authority
from synapse.store import SemanticStore


class TestNormalizeAuthority(unittest.TestCase):
    def test_bare_code_and_uri_wrapped_code_are_equivalent(self):
        """HL7v2 PID-3.4 gives a bare namespace-id ("HIS"); FHIR
        Identifier.system gives a URI wrapping the same code
        ("urn:oid:HIS"). Both must normalize to the same key, or the
        already-proven cross-format convergence breaks."""
        self.assertEqual(normalize_authority("HIS"), normalize_authority("urn:oid:HIS"))
        self.assertEqual(normalize_authority("his"), normalize_authority("URN:OID:HIS"))

    def test_url_style_system_takes_last_segment(self):
        self.assertEqual(
            normalize_authority("http://example-hospital.org/patient-ids"),
            "patient-ids",
        )

    def test_empty_and_none_normalize_to_empty_string(self):
        self.assertEqual(normalize_authority(None), "")
        self.assertEqual(normalize_authority(""), "")

    def test_genuinely_different_authorities_stay_different(self):
        self.assertNotEqual(normalize_authority("HIS"), normalize_authority("STMARY"))


class TestAuthorityScopedResolution(unittest.TestCase):
    def _er(self) -> EntityResolutionService:
        return EntityResolutionService(SemanticStore())

    def test_same_bare_id_different_authority_stays_distinct(self):
        """The actual collision the fix defends against: two facilities
        both issue patient ID "P001" to two different real people. Without
        authority scoping, the second get_or_create would silently widen
        the first patient's entity with the second (unrelated) person's
        name/facts."""
        er = self._er()
        p1 = er.get_or_create(
            "Patient",
            "David Williams",
            source_system="hl7_general",
            acl_tags=["domain:clinical"],
            external_id="P001",
            identifier_authority="HIS",
        )
        p2 = er.get_or_create(
            "Patient",
            "Priya Sharma",
            source_system="hl7_stmary",
            acl_tags=["domain:clinical"],
            external_id="P001",
            identifier_authority="STMARY",
        )
        self.assertNotEqual(p1.entity_id, p2.entity_id)

    def test_equivalent_authority_representations_still_converge(self):
        """The backward-compatibility guarantee: HL7's "HIS" and FHIR's
        "urn:oid:HIS" describe the same real facility and must still
        resolve to one entity, exactly as already proven end-to-end."""
        er = self._er()
        p1 = er.get_or_create(
            "Patient",
            "David Williams",
            source_system="hl7_general",
            acl_tags=["domain:clinical"],
            external_id="P001",
            identifier_authority="HIS",
        )
        p2 = er.get_or_create(
            "Patient",
            "David Williams",
            source_system="fhir_general",
            acl_tags=["domain:clinical"],
            external_id="P001",
            identifier_authority="urn:oid:HIS",
        )
        self.assertEqual(p1.entity_id, p2.entity_id)

    def test_missing_authority_on_either_side_stays_permissive(self):
        """CSV-sourced identifiers have no assigning-authority concept at
        all. A source with no stated authority must still converge with a
        source that does -- this is the existing CSV+HL7+FHIR proof, and
        must not regress just because one side now carries an authority."""
        er = self._er()
        p1 = er.get_or_create(
            "Patient",
            "David Williams",
            source_system="csv_hospital",
            acl_tags=["domain:clinical"],
            external_id="P001",
            # no identifier_authority -- CSV has no such field
        )
        p2 = er.get_or_create(
            "Patient",
            "David Williams",
            source_system="hl7_general",
            acl_tags=["domain:clinical"],
            external_id="P001",
            identifier_authority="HIS",
        )
        self.assertEqual(p1.entity_id, p2.entity_id)


if __name__ == "__main__":
    unittest.main()
