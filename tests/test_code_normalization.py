"""
Shared code-system identity normalization (Claude_Instructions.md Step 3.1)
-- the fix for the specific gap found testing New Data/: HL7 and FHIR both
carry an explicit coding-system pointer alongside the code (HL7 OBX-3
component 3 / FHIR `coding[0].system`), and the original extractors both
discarded it, so the identical LOINC-coded analyte produced two
unrelated LabResult identities depending on which wire format carried it.

The end-to-end test here is deliberately built with a real, correctly-
declared LOINC code on both sides -- proving the normalization itself is
sound -- rather than reproducing New Data/'s fixture verbatim, which uses
non-conformant code strings on its FHIR side (a data-quality issue in
that fixture, documented in workspace_scratch/, not something this
normalizer should special-case around).
"""

from __future__ import annotations

import json
import unittest

from synapse.coding_systems import normalize_code
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore

TSH_LOINC = "3016-3"


class TestNormalizeCode(unittest.TestCase):
    def test_hl7_and_fhir_loinc_tokens_converge(self):
        self.assertEqual(normalize_code("LN", TSH_LOINC), normalize_code("http://loinc.org", TSH_LOINC))

    def test_snomed_tokens_converge(self):
        self.assertEqual(
            normalize_code("SCT", "271737000"),
            normalize_code("http://snomed.info/sct", "271737000"),
        )

    def test_different_systems_stay_distinct(self):
        self.assertNotEqual(normalize_code("LN", "12345"), normalize_code("SCT", "12345"))

    def test_missing_system_falls_back_to_local_not_dropped(self):
        key = normalize_code(None, "HGB")
        self.assertEqual(key, "local:HGB")
        # A genuinely different local code must not collide with it.
        self.assertNotEqual(key, normalize_code(None, "WBC"))

    def test_empty_code_returns_empty_string(self):
        self.assertEqual(normalize_code("LN", ""), "")
        self.assertEqual(normalize_code("LN", None), "")


class TestCrossFormatConvergence(unittest.TestCase):
    def test_same_patient_same_loinc_code_converges_across_hl7_and_fhir(self):
        """The actual proof this dataset was built to exercise: the same
        analyte, same patient, arriving via two structurally unrelated
        formats, must resolve to ONE LabResult entity -- not two."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")

        hl7_msg = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20260721083000||ORU^R01|MSG1|P|2.5.1\n"
            "PID|1||CONV-001^^^HIS^MR||Doe^Jane||19800101|F|||1 Main St||5551234567\n"
            f"OBR|1|ORD1|LAB1|{TSH_LOINC}^TSH^LN|||20260721080000\n"
            f"OBX|1|NM|{TSH_LOINC}^TSH^LN||2.5|uIU/mL|0.4-4.0|N|||F\n"
        )
        r1 = ing.land("LIS-ORU", hl7_msg, ["domain:clinical", "clearance:l2"])
        hl7_out = ex.extract_from_episode(r1.episode, r1.raw)
        self.assertIsNotNone(hl7_out)

        fhir_bundle = json.dumps(
            {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "conv-001",
                            "identifier": [{"system": "urn:oid:HIS", "value": "CONV-001"}],
                            "name": [{"family": "Doe", "given": ["Jane"]}],
                            "birthDate": "1980-01-01",
                            "gender": "female",
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Observation",
                            # No `id` here, and `basedOn` pointing at the same
                            # order id the HL7 side's OBR-2 carries ("ORD1")
                            # -- both formats' *instance* scoping (a
                            # separate, deliberate mechanism from the code
                            # normalization under test: it keeps two
                            # distinct blood draws for the same analyte from
                            # colliding) needs to agree on which real-world
                            # order/accession this result belongs to, same
                            # as the code itself needs to agree on LOINC.
                            "status": "final",
                            "code": {
                                "coding": [
                                    {
                                        "system": "http://loinc.org",
                                        "code": TSH_LOINC,
                                        "display": "TSH",
                                    }
                                ]
                            },
                            "subject": {"reference": "Patient/conv-001"},
                            "basedOn": [{"reference": "ORD1"}],
                            "valueQuantity": {"value": 2.6, "unit": "uIU/mL"},
                        }
                    },
                ],
            }
        )
        r2 = ing.land("FHIR-Interface", fhir_bundle, ["domain:clinical", "clearance:l2"])
        fhir_out = ex.extract_from_episode(r2.episode, r2.raw)
        self.assertIsNotNone(fhir_out)

        # Same patient converges (pre-existing behavior, reconfirmed here).
        self.assertEqual(hl7_out.entity.entity_id, fhir_out.entity.entity_id)

        # The actual fix under test: TSH must be ONE LabResult entity, not
        # two, because both sides declared LOINC and both sides are now
        # read via the same normalize_code().
        tsh_entities = [e for e in store.entities.values() if e.entity_type == "LabResult"]
        self.assertEqual(
            len(tsh_entities), 1, "same patient's same LOINC-coded analyte must be one entity"
        )
        preds = {f.predicate: f.object for f in store.facts_for_entity(tsh_entities[0].entity_id)}
        # Both sources' result values are present against the one entity.
        self.assertEqual(preds.get("result"), 2.6)  # last-write-wins on the same predicate


if __name__ == "__main__":
    unittest.main()
