#!/usr/bin/env python3
"""
Active_File.md task 10 — prove the banking pack: extraction + the
AccountHolder <- Account <- Transaction join, plus the name-collision safety
check (two different "John Smith" holders must stay distinct entities).

  python scripts/smoke_banking_join.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / ".data" / "synthetic_banking"
DB = ROOT / ".data" / "banking_demo.db"


def main() -> int:
    from synapse.connectors.csv_drop import CsvDropConnector
    from synapse.session import open_session

    if DB.is_file():
        DB.unlink()
    session = open_session(str(DB))
    try:
        session.ingestion.domain = "banking"

        for fname, source_system, cid in (
            ("account_holders.csv", "Bank-CoreBanking", "bank-holders"),
            ("accounts.csv", "Bank-CoreBanking", "bank-accounts"),
            ("transactions.csv", "Bank-Ledger", "bank-transactions"),
        ):
            conn = CsvDropConnector(
                path=str(DATA_DIR / fname),
                connector_id=cid,
                source_system=source_system,
                default_acl=["domain:banking", "clearance:l2"],
            )
            session.connectors.register(conn)
            session.connector_runner.poll_one(cid)

        counts = {
            etype: sum(1 for e in session.store.entities.values() if e.entity_type == etype)
            for etype in ("AccountHolder", "Account", "Transaction")
        }

        def facts_of(entity_id):
            return {f.predicate: f.object for f in session.store.facts_for_entity(entity_id)}

        accounts = [e for e in session.store.entities.values() if e.entity_type == "Account"]
        account_resolved = sum(1 for e in accounts if "holder_entity_id" in facts_of(e.entity_id))
        txns = [e for e in session.store.entities.values() if e.entity_type == "Transaction"]
        txn_resolved = sum(1 for e in txns if "account_entity_id" in facts_of(e.entity_id))

        # Name-collision safety check: two "John Smith" holders (H001, H003)
        smiths = [
            e
            for e in session.store.entities.values()
            if e.entity_type == "AccountHolder" and e.canonical_name == "John Smith"
        ]

        report = {
            "entity_counts": counts,
            "account_to_holder_resolved": f"{account_resolved}/{len(accounts)}",
            "transaction_to_account_resolved": f"{txn_resolved}/{len(txns)}",
            "john_smith_entities": len(smiths),
            "john_smith_stayed_distinct": len(smiths) == 2,
            "john_smith_national_ids": sorted(
                facts_of(e.entity_id).get("national_id") for e in smiths
            ),
        }
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
