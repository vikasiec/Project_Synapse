#!/usr/bin/env python3
"""
Active_File.md task 10 — baseline probe for the synthetic banking dataset.

Same discipline as task 1: run the unmodified pipeline against the new
domain's data first, so the gap is evidence-based, not assumed.

  python scripts/smoke_banking_baseline.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / ".data" / "synthetic_banking"
FILES = {
    "account_holders.csv": "Bank-CoreBanking",
    "accounts.csv": "Bank-CoreBanking",
    "transactions.csv": "Bank-Ledger",
}


def main() -> int:
    from synapse.connectors.csv_drop import CsvDropConnector
    from synapse.connectors.registry import ConnectorRegistry
    from synapse.connectors.runner import ConnectorRunner
    from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
    from synapse.ingestion import IngestionService
    from synapse.store import SemanticStore

    report: dict = {"domain": "banking", "files": {}}

    for fname, source_system in FILES.items():
        path = DATA_DIR / fname
        store = SemanticStore()
        reg = ConnectorRegistry()
        conn = CsvDropConnector(
            path=str(path),
            connector_id=f"bank-{fname}",
            source_system=source_system,
            default_acl=["domain:banking", "clearance:l2"],
        )
        reg.register(conn)
        runner = ConnectorRunner(
            store,
            reg,
            ingestion=IngestionService(store, domain="banking"),
            dual_path=DualPathExtractor(store, residual=HeuristicResidualExtractor()),
            domain="banking",
            use_dual_path=True,
        )
        result = runner.poll_one(f"bank-{fname}")
        report["files"][fname] = {
            "rows": result.events,
            "landed": result.landed,
            "entities_extracted": result.extracted,
        }

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
