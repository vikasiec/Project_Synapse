"""Banking vertical (Active_File.md task 10) — second domain, proving
docs/DOMAIN_PACK_CONTRACT.md generalizes beyond healthcare."""

from __future__ import annotations

import unittest
from pathlib import Path

from synapse.connectors.csv_drop import CsvDropConnector
from synapse.connectors.registry import ConnectorRegistry
from synapse.connectors.runner import ConnectorRunner
from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore

HOLDER_PAYLOAD = (
    "Holder_id: H001\nFirst_name: John\nLast_name: Smith\n"
    "National_id: NID-55012\nEmail: john.smith1@mail.com\n"
)
ACCOUNT_PAYLOAD = (
    "Account_id: A001\nHolder_id: H001\nAccount_type: Checking\n"
    "Branch: Downtown\nStatus: Active\n"
)
TRANSACTION_PAYLOAD = (
    "Transaction_id: T001\nAccount_id: A001\nAmount: 1500.00\n"
    "Transaction_type: Deposit\nDescription: Payroll\n"
)

BANKING_DIR = Path(__file__).resolve().parents[1] / ".data" / "synthetic_banking"


class TestBankingExtract(unittest.TestCase):
    def test_ontology_types_registered(self):
        ont = OntologyRegistry.default()
        for name in ("AccountHolder", "Account", "Transaction"):
            self.assertIn(name, ont.types)
        self.assertTrue(ont.get("AccountHolder").strict_identity)

    def test_account_holder_never_shares_family_with_patient_or_person(self):
        ont = OntologyRegistry.default()
        self.assertFalse(ont.types_match("AccountHolder", "Patient"))
        self.assertFalse(ont.types_match("AccountHolder", "Person"))
        self.assertFalse(ont.types_match("AccountHolder", "IdentityPrincipal"))

    def test_account_row_not_mistaken_for_holder(self):
        """accounts.csv carries holder_id as a foreign key but no identity
        fields — must never be extracted as an AccountHolder."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="banking")
        r = ing.land("Bank-CoreBanking", ACCOUNT_PAYLOAD, ["domain:banking", "clearance:l2"])
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Account")

    def test_transaction_row_not_mistaken_for_account(self):
        """A transaction row has account_id but not account_type/branch/status."""
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="banking")
        r = ing.land(
            "Bank-Ledger", TRANSACTION_PAYLOAD, ["domain:banking", "clearance:l2"]
        )
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "Transaction")

    def test_two_holders_sharing_a_name_stay_distinct(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="banking")
        h1 = "Holder_id: H001\nFirst_name: John\nLast_name: Smith\nNational_id: NID-55012\n"
        h3 = "Holder_id: H003\nFirst_name: John\nLast_name: Smith\nNational_id: NID-55014\n"
        r1 = ing.land("Bank-CoreBanking", h1, ["domain:banking", "clearance:l2"])
        out1 = ex.extract_from_episode(r1.episode, r1.raw)
        r3 = ing.land("Bank-CoreBanking", h3, ["domain:banking", "clearance:l2"])
        out3 = ex.extract_from_episode(r3.episode, r3.raw)
        self.assertNotEqual(out1.entity.entity_id, out3.entity.entity_id)

    def test_full_chain_resolves_in_dependency_order(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="banking")
        for source, payload in (
            ("Bank-CoreBanking", HOLDER_PAYLOAD),
            ("Bank-CoreBanking", ACCOUNT_PAYLOAD),
            ("Bank-Ledger", TRANSACTION_PAYLOAD),
        ):
            r = ing.land(source, payload, ["domain:banking", "clearance:l2"])
            ex.extract_from_episode(r.episode, r.raw)

        txn = store.get_entity_by_name("T001")
        self.assertIsNotNone(txn)
        tf = {f.predicate: f.object for f in store.facts_for_entity(txn.entity_id)}
        self.assertIn("account_entity_id", tf)

        account = store.entities.get(tf["account_entity_id"])
        af = {f.predicate: f.object for f in store.facts_for_entity(account.entity_id)}
        self.assertIn("holder_entity_id", af)

    @unittest.skipUnless(
        (BANKING_DIR / "account_holders.csv").is_file(), "synthetic banking data not present"
    )
    def test_real_csvs_fully_extract_and_join(self):
        store = SemanticStore()
        reg = ConnectorRegistry()
        ingestion = IngestionService(store, domain="banking")
        dual_path = DualPathExtractor(store, residual=HeuristicResidualExtractor())
        runner = ConnectorRunner(
            store, reg, ingestion=ingestion, dual_path=dual_path,
            domain="banking", use_dual_path=True,
        )
        for fname, source_system, cid in (
            ("account_holders.csv", "Bank-CoreBanking", "bank-holders"),
            ("accounts.csv", "Bank-CoreBanking", "bank-accounts"),
            ("transactions.csv", "Bank-Ledger", "bank-transactions"),
        ):
            conn = CsvDropConnector(
                path=str(BANKING_DIR / fname),
                connector_id=cid,
                source_system=source_system,
                default_acl=["domain:banking", "clearance:l2"],
            )
            reg.register(conn)
            runner.poll_one(cid)

        holders = [e for e in store.entities.values() if e.entity_type == "AccountHolder"]
        accounts = [e for e in store.entities.values() if e.entity_type == "Account"]
        txns = [e for e in store.entities.values() if e.entity_type == "Transaction"]
        self.assertEqual(len(holders), 8)
        self.assertEqual(len(accounts), 10)
        self.assertEqual(len(txns), 15)
        for e in accounts:
            preds = {f.predicate for f in store.facts_for_entity(e.entity_id)}
            self.assertIn("holder_entity_id", preds)
        for e in txns:
            preds = {f.predicate for f in store.facts_for_entity(e.entity_id)}
            self.assertIn("account_entity_id", preds)

        smiths = [h for h in holders if h.canonical_name == "John Smith"]
        self.assertEqual(len(smiths), 2)


if __name__ == "__main__":
    unittest.main()
