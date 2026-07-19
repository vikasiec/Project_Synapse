"""
query.py's answer narration had a hardcoded predicate whitelist
(current_version/annual_revenue/runtime_state/account_status — all
infra/revenue/identity specific) baked into the domain-blind core. Any other
domain's facts (e.g. healthcare Patient predicates) fell through to a false
"No primary facts visible" even when real facts existed. Found via Sense
board walkthrough (Active_File.md task 9), fixed with a generic fallback.
"""

from __future__ import annotations

import unittest

from synapse.control_plane import ControlPlane
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.query import QueryService
from synapse.resolution import ConflictResolver
from synapse.security import Principal
from synapse.store import SemanticStore


class TestQueryGenericNarration(unittest.TestCase):
    def setUp(self):
        self.store = SemanticStore()
        self.ontology = OntologyRegistry.default()
        self.extractor = RuleExtractor(self.store, ontology=self.ontology)
        self.ingestion = IngestionService(self.store, domain="hospital_ops")
        cp = ControlPlane({"HIS-Patients": 0.85})
        resolver = ConflictResolver(self.store, cp, ontology=self.ontology)
        self.query = QueryService(self.store, cp, resolver)
        self.principal = Principal.from_tags(
            "clinician-1", ["domain:clinical", "clearance:l2"]
        )

    def test_patient_facts_narrated_not_falsely_empty(self):
        payload = (
            "Patient_id: P001\nFirst_name: David\nLast_name: Williams\n"
            "Insurance_provider: WellnessCorp\nContact_number: 6939585183\n"
        )
        r = self.ingestion.land("HIS-Patients", payload, ["domain:clinical", "clearance:l2"])
        out = self.extractor.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)

        result = self.query.ask(self.principal, entity_name="David Williams")
        self.assertTrue(result.allowed)
        self.assertNotIn("No primary facts visible", result.claim.statement)
        self.assertIn("insurance_provider=WellnessCorp", result.claim.statement)
        self.assertIn("contact_number=6939585183", result.claim.statement)

    def test_entity_with_truly_no_facts_is_denied_not_narrated(self):
        """An entity with zero facts is denied at the ABAC gate before
        narration ever runs (existing, correct behavior) — the new generic
        fallback must not paper over this by inventing a fake statement."""
        from synapse.models import Entity

        ent = Entity.create(
            "Patient", "Nobody Here", acl_tags=["domain:clinical", "clearance:l2"]
        )
        self.store.put_entity(ent)
        result = self.query.ask(self.principal, entity_name="Nobody Here")
        self.assertFalse(result.allowed)
        self.assertIsNone(result.claim)
        self.assertIn("No facts visible", result.denial_reason)


if __name__ == "__main__":
    unittest.main()
