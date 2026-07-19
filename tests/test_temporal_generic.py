"""
temporal.py's OPERATIONAL_PREDICATES was a hardcoded infra/revenue-domain
predicate whitelist -- temporal supersession silently never applied to any
healthcare/banking predicate (e.g. "result"), so the same patient's repeated
lab result over time looked like an open cross-source conflict instead of a
legitimate updated value. Found via Codex's H1-H16 architecture review
(Active_File.md row 14). Fixed generically: supersession now applies to
every predicate, gated only by (predicate, source_system) grouping, which
is what actually makes it safe.
"""

from __future__ import annotations

import unittest

from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore

MSG_DAY1 = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG1|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd||6939585183\n"
    "OBR|1|ORD1|LAB1|CBC^Complete Blood Count^L|||20230810080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
)
MSG_DAY2 = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230910083000||ORU^R01|MSG2|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd||6939585183\n"
    "OBR|1|ORD2|LAB2|CBC^Complete Blood Count^L|||20230910080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||13.8|g/dL|13.5-17.5|N|||F\n"
)


class TestTemporalGenericSupersession(unittest.TestCase):
    def test_repeated_hl7_lab_result_supersedes_not_conflicts(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")

        r1 = ing.land("LIS-ORU", MSG_DAY1, ["domain:clinical", "clearance:l2"])
        ex.extract_from_episode(r1.episode, r1.raw)
        r2 = ing.land("LIS-ORU", MSG_DAY2, ["domain:clinical", "clearance:l2"])
        ex.extract_from_episode(r2.episode, r2.raw)

        hgb_entities = [
            e for e in store.entities.values() if e.canonical_name == "Hemoglobin"
        ]
        self.assertEqual(len(hgb_entities), 1)

        results = [
            f for f in store.facts_for_entity(hgb_entities[0].entity_id) if f.predicate == "result"
        ]
        self.assertEqual(len(results), 2)
        current = [f for f in results if f.valid_to is None]
        superseded = [f for f in results if f.valid_to is not None]
        self.assertEqual(len(current), 1, "exactly one current result, not an open conflict")
        self.assertEqual(current[0].object, 13.8)
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0].object, 14.2)

    def test_different_sources_same_predicate_still_conflict(self):
        """The fix must not eliminate genuine cross-source conflicts --
        different source_system, same predicate, must stay separate."""
        from synapse.control_plane import ControlPlane
        from synapse.resolution import ConflictResolver
        from synapse.models import Fact

        store = SemanticStore()
        from synapse.models import Entity

        ent = Entity.create("LabResult", "Glucose")
        store.put_entity(ent)
        f1 = Fact.create(
            ent.entity_id, "result", 95.0, confidence=0.9,
            evidence_refs=[], source_system="Lab-A", acl_tags=[],
        )
        f2 = Fact.create(
            ent.entity_id, "result", 110.0, confidence=0.9,
            evidence_refs=[], source_system="Lab-B", acl_tags=[],
        )
        store.put_fact(f1)
        store.put_fact(f2)

        from synapse.temporal import TemporalService

        TemporalService(store).apply_for_entity(ent.entity_id)
        results = [f for f in store.facts_for_entity(ent.entity_id) if f.predicate == "result"]
        still_current = [f for f in results if f.valid_to is None]
        self.assertEqual(len(still_current), 2, "different sources must not supersede each other")

        cp = ControlPlane({"Lab-A": 0.8, "Lab-B": 0.6})
        resolver = ConflictResolver(store, cp)
        views = resolver.detect_scalar_conflicts(ent.entity_id)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].conflict.predicate, "result")


if __name__ == "__main__":
    unittest.main()
