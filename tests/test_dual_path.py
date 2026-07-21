import unittest

from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor, ResidualExtractor
from synapse.ingestion import IngestionService
from synapse.models import Fact
from synapse.store import SemanticStore


class TestDualPath(unittest.TestCase):
    def test_path_a_and_residual_note(self):
        store = SemanticStore()
        ing = IngestionService(store)
        dual = DualPathExtractor(store, residual=HeuristicResidualExtractor())
        result = ing.land(
            "GitHub-CI",
            "BUILD SUCCESSFUL: checkout-service deployed image tag v3.0.0 automatically.\n"
            "note: rollback risk high for EU region\n",
            ["domain:sre", "clearance:l2"],
        )
        out = dual.extract(result.episode, result.raw)
        self.assertEqual(out.entity_name, "checkout-service")
        self.assertTrue(out.deterministic_facts)
        self.assertTrue(out.path_b_used)
        self.assertTrue(any(f.predicate == "free_text_note" for f in out.residual_facts))


class _AllTextEchoResidualExtractor(ResidualExtractor):
    """Test double: emits exactly one fact carrying the residual_text it
    was given, verbatim, as the object -- so a test can assert what text
    actually reached the residual path without depending on any real
    LLM's behavior (honors "no other AI usage": this is a plain object,
    not a model call)."""

    name = "all_text_echo"

    def extract_residual(self, residual_text, *, episode, raw, entity_id):
        if not entity_id or not residual_text.strip():
            return []
        return [
            Fact.create(
                entity_id,
                "free_text_note",
                residual_text,
                confidence=0.5,
                evidence_refs=[raw.object_id, episode.episode_id],
                source_system=raw.source_system,
                acl_tags=list(raw.acl_tags),
                valid_from=raw.ingested_at,
                extractor_version="test-echo/0.1",
            )
        ]


class _FixedPredicateResidualExtractor(ResidualExtractor):
    """Test double: always emits one fact with a caller-chosen predicate,
    to prove the domain-bounded vocabulary filter actually drops/keeps
    facts based on that predicate rather than trusting the backend."""

    name = "fixed_predicate"

    def __init__(self, predicate: str) -> None:
        self.predicate = predicate

    def extract_residual(self, residual_text, *, episode, raw, entity_id):
        if not entity_id:
            return []
        return [
            Fact.create(
                entity_id,
                self.predicate,
                "value",
                confidence=0.6,
                evidence_refs=[raw.object_id, episode.episode_id],
                source_system=raw.source_system,
                acl_tags=list(raw.acl_tags),
                valid_from=raw.ingested_at,
                extractor_version="test-fixed/0.1",
            )
        ]


class TestResidualGatingHl7Fhir(unittest.TestCase):
    """The bug found testing New Data/: every already-parsed HL7 message
    was being resubmitted whole to the residual/LLM path, because the
    generic key:value stripper never matches pipe-delimited segments. Path
    A already reads every OBX/PID/OBR field with a dedicated, correctly-
    typed extractor -- the residual path should see NOTHING for a message
    with no NTE (free-text notes) segment, and ONLY the NTE text when one
    is present."""

    def test_hl7_message_without_nte_sends_no_text_to_residual(self):
        store = SemanticStore()
        echo = _AllTextEchoResidualExtractor()
        dual = DualPathExtractor(store, residual=echo)
        ing = IngestionService(store, domain="clinical_lab")
        msg = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG1|P|2.5.1\n"
            "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd||6939585183\n"
            "OBR|1|ORD1|LAB1|CBC^Complete Blood Count^L|||20230810080000\n"
            "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
        )
        r = ing.land("LIS-ORU", msg, ["domain:clinical", "clearance:l2"])
        out = dual.extract(r.episode, r.raw)
        self.assertFalse(out.path_b_used, "no NTE segment -> nothing genuinely residual")
        self.assertEqual(out.residual_text, "")

    def test_hl7_nte_segment_is_the_only_thing_sent_to_residual(self):
        store = SemanticStore()
        echo = _AllTextEchoResidualExtractor()
        dual = DualPathExtractor(store, residual=echo)
        ing = IngestionService(store, domain="clinical_lab")
        msg = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG1|P|2.5.1\n"
            "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd||6939585183\n"
            "OBR|1|ORD1|LAB1|CBC^Complete Blood Count^L|||20230810080000\n"
            "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
            "NTE|1||Specimen slightly hemolyzed, repeat recommended\n"
        )
        r = ing.land("LIS-ORU", msg, ["domain:clinical", "clearance:l2"])
        out = dual.extract(r.episode, r.raw)
        self.assertEqual(out.residual_text, "Specimen slightly hemolyzed, repeat recommended")
        # The pipe-delimited segments themselves must never reach the
        # residual path -- only the genuine free-text NTE content.
        self.assertNotIn("MSH|", out.residual_text)
        self.assertNotIn("OBX|", out.residual_text)

    def test_fhir_bundle_without_note_sends_no_text_to_residual(self):
        import json

        store = SemanticStore()
        echo = _AllTextEchoResidualExtractor()
        dual = DualPathExtractor(store, residual=echo)
        ing = IngestionService(store, domain="clinical_lab")
        bundle = json.dumps(
            {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "status": "final",
                            "code": {"coding": [{"system": "http://loinc.org", "code": "3016-3", "display": "TSH"}]},
                            "subject": {"reference": "Patient/PAT-1", "display": "Alpha Patient"},
                            "valueQuantity": {"value": 2.1, "unit": "uIU/mL"},
                        }
                    }
                ],
            }
        )
        r = ing.land("FHIR-Interface", bundle, ["domain:clinical", "clearance:l2"])
        out = dual.extract(r.episode, r.raw)
        self.assertFalse(out.path_b_used)
        self.assertEqual(out.residual_text, "")


class TestResidualPredicateBounding(unittest.TestCase):
    """Claude_Instructions.md absolute constraint: the residual/LLM path
    must be bounded by a pre-defined per-domain vocabulary, not free to
    invent any predicate name."""

    def test_allowed_predicate_for_domain_survives(self):
        store = SemanticStore()
        dual = DualPathExtractor(store, residual=_FixedPredicateResidualExtractor("risk_flag"))
        ing = IngestionService(store, domain="infra_ops")
        r = ing.land(
            "GitHub-CI",
            "BUILD SUCCESSFUL: checkout-service deployed image tag v1.0.0 automatically.\n"
            "note: something\n",
            ["domain:sre", "clearance:l2"],
        )
        out = dual.extract(r.episode, r.raw)
        self.assertTrue(any(f.predicate == "risk_flag" for f in out.residual_facts))

    def test_wrong_domain_predicate_is_dropped(self):
        """The exact defect found in production: an SRE-flavored predicate
        (`incident_theme`) emitted for a clinical-domain episode must be
        dropped, not stored as if it were a legitimate clinical fact."""
        store = SemanticStore()
        dual = DualPathExtractor(store, residual=_FixedPredicateResidualExtractor("incident_theme"))
        ing = IngestionService(store, domain="clinical_lab")
        msg = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG1|P|2.5.1\n"
            "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd||6939585183\n"
            "OBR|1|ORD1|LAB1|CBC^Complete Blood Count^L|||20230810080000\n"
            "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
            "NTE|1||free text present so the residual path actually runs\n"
        )
        r = ing.land("LIS-ORU", msg, ["domain:clinical", "clearance:l2"])
        out = dual.extract(r.episode, r.raw)
        self.assertFalse(any(f.predicate == "incident_theme" for f in out.residual_facts))

    def test_synonym_predicate_folds_to_canonical_name(self):
        """`ordering_provider` and `ordering_physician` are the same real
        fact; the model must not be allowed to split it across two
        predicate spellings depending on which call happened to produce
        which phrasing."""
        store = SemanticStore()
        dual = DualPathExtractor(store, residual=_FixedPredicateResidualExtractor("ordering_provider"))
        ing = IngestionService(store, domain="clinical_lab")
        msg = (
            "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG1|P|2.5.1\n"
            "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd||6939585183\n"
            "OBR|1|ORD1|LAB1|CBC^Complete Blood Count^L|||20230810080000\n"
            "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
            "NTE|1||ordered per protocol\n"
        )
        r = ing.land("LIS-ORU", msg, ["domain:clinical", "clearance:l2"])
        out = dual.extract(r.episode, r.raw)
        self.assertTrue(any(f.predicate == "ordering_physician" for f in out.residual_facts))
        self.assertFalse(any(f.predicate == "ordering_provider" for f in out.residual_facts))


if __name__ == "__main__":
    unittest.main()
