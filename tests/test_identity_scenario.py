import unittest

from synapse.models import EntityStatus
from synapse.scenarios.identity_access import IdentityAccessScenario


class TestIdentityScenario(unittest.TestCase):
    def test_single_person_status_conflict(self):
        scenario = IdentityAccessScenario()
        bundle = scenario.seed()
        people = [
            e
            for e in bundle.store.entities.values()
            if e.entity_type == "Person" and e.status == EntityStatus.ACTIVE
        ]
        self.assertEqual(len(people), 1, msg=[p.canonical_name for p in people])
        person = people[0]
        statuses = {
            str(f.object)
            for f in bundle.store.facts_for_entity(person.entity_id, "account_status")
            if f.valid_to is None
        }
        self.assertIn("active", statuses)
        self.assertIn("deprovisioned", statuses)

        result = bundle.query.ask(
            IdentityAccessScenario.principal_l2(),
            entity_name="Jane Doe",
        )
        self.assertTrue(result.allowed)
        self.assertTrue(
            any(v.conflict.predicate == "account_status" for v in result.conflict_views)
        )
        self.assertIn("AMBIGUOUS account_status", result.claim.statement)


if __name__ == "__main__":
    unittest.main()
