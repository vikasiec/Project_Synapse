"""
H6 reprocess idempotency for HL7v2/FHIR (Active_File.md row 28).

test_platform_gaps.py's test_reprocess only ever exercised the original
checkout scenario. This session changed LabResult/Patient identity twice
(row 23: identifier_authority scoping, row 25: observation_instance_id
scoping) -- re-running extraction over an already-landed HL7 or FHIR
episode (what reprocess does) could plausibly have started duplicating
entities under either mechanism if get_or_create's blocking keys weren't
built consistently. This proves it doesn't: reprocessing must resolve
back to the SAME entities, not create new ones, and the resulting
append-only fact history must still collapse to exactly one current
value per predicate via temporal supersession, not a false conflict.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.reprocess import ReprocessService
from synapse.store import SemanticStore

BANKING_DIR = Path(__file__).resolve().parents[1] / ".data" / "synthetic_banking"

HL7_MSG = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG1|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F|||789 Pine Rd||6939585183\n"
    "OBR|1|ORD1|LAB1|CBC^Complete Blood Count^L|||20230810080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N|||F\n"
)

FHIR_BUNDLE = json.dumps(
    {
        "resourceType": "Bundle",
        "type": "message",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "p777",
                    "identifier": [{"system": "urn:oid:HIS", "value": "P777"}],
                    "name": [{"family": "Patel", "given": ["Asha"]}],
                    "birthDate": "1979-04-18",
                    "gender": "female",
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-p777-hgb",
                    "status": "final",
                    "code": {"coding": [{"code": "718-7", "display": "Hemoglobin"}]},
                    "subject": {"reference": "Patient/p777"},
                    "valueQuantity": {"value": 13.2, "unit": "g/dL"},
                }
            },
        ],
    }
)


class TestReprocessInterop(unittest.TestCase):
    def test_banking_reprocess_does_not_duplicate_entities_or_conflicts(self):
        from synapse.connectors.csv_drop import CsvDropConnector
        from synapse.session import open_session

        session = open_session(domain="banking")
        try:
            for fname, source_system, cid in (
                ("account_holders.csv", "Bank-CoreBanking", "reprocess-bank-holders"),
                ("accounts.csv", "Bank-CoreBanking", "reprocess-bank-accounts"),
                ("transactions.csv", "Bank-Ledger", "reprocess-bank-transactions"),
            ):
                conn = CsvDropConnector(
                    path=str(BANKING_DIR / fname),
                    connector_id=cid,
                    source_system=source_system,
                    default_acl=["domain:banking", "clearance:l2"],
                )
                session.connectors.register(conn)
                session.connector_runner.poll_one(cid)

            entity_count_before = len(session.store.entities)
            current_before = sum(
                1 for fact in session.store.facts.values() if fact.valid_to is None
            )
            report = ReprocessService(session.store).run(limit=1000)
            self.assertGreaterEqual(report.episodes_reprocessed, 1)
            self.assertEqual(len(session.store.entities), entity_count_before)

            current_after = sum(
                1 for fact in session.store.facts.values() if fact.valid_to is None
            )
            self.assertEqual(current_after, current_before)
            conflicts = []
            for entity in session.store.entities.values():
                conflicts.extend(session.resolver.detect_scalar_conflicts(entity.entity_id))
            self.assertEqual(conflicts, [], "banking reprocess must not create false conflicts")
        finally:
            session.close()

    def test_hl7_reprocess_does_not_duplicate_entities(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land("LIS-ORU", HL7_MSG, ["domain:clinical", "clearance:l2"])
        ex.extract_from_episode(r.episode, r.raw)

        entity_count_before = len(store.entities)
        report = ReprocessService(store).run(limit=10)
        self.assertGreaterEqual(report.episodes_reprocessed, 1)
        self.assertEqual(len(store.entities), entity_count_before, "reprocess must not duplicate entities")

        hgb = next(e for e in store.entities.values() if e.canonical_name == "Hemoglobin")
        current = [f for f in store.facts_for_entity(hgb.entity_id, "result") if f.valid_to is None]
        self.assertEqual(len(current), 1, "exactly one current result, not a false conflict")
        self.assertEqual(current[0].object, 14.2)

    def test_fhir_reprocess_does_not_duplicate_entities(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land("FHIR-Interface", FHIR_BUNDLE, ["domain:clinical", "clearance:l2"])
        ex.extract_from_episode(r.episode, r.raw)

        entity_count_before = len(store.entities)
        report = ReprocessService(store).run(limit=10)
        self.assertGreaterEqual(report.episodes_reprocessed, 1)
        self.assertEqual(len(store.entities), entity_count_before, "reprocess must not duplicate entities")

        hgb = next(e for e in store.entities.values() if e.canonical_name == "Hemoglobin")
        current = [f for f in store.facts_for_entity(hgb.entity_id, "result") if f.valid_to is None]
        self.assertEqual(len(current), 1, "exactly one current result, not a false conflict")
        self.assertEqual(current[0].object, 13.2)


if __name__ == "__main__":
    unittest.main()
