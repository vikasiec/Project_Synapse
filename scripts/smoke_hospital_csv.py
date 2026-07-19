#!/usr/bin/env python3
"""
Active_File.md task 1 — hospital_management dataset diagnostic.

Runs the existing dual-path extractor + ontology (unchanged) against all five
CSVs in .data/kaggle_raw/hospital_management/ and reports what extracts vs.
what falls through, so the gap is evidence-based rather than assumed.

  python scripts/smoke_hospital_csv.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / ".data" / "kaggle_raw" / "hospital_management"
FILES = {
    "patients.csv": "HIS-Patients",
    "doctors.csv": "HIS-Doctors",
    "appointments.csv": "HIS-Scheduling",
    "billing.csv": "HIS-Billing",
    "treatments.csv": "HIS-Treatments",
}


def main() -> int:
    from synapse.connectors.csv_drop import CsvDropConnector
    from synapse.connectors.registry import ConnectorRegistry
    from synapse.connectors.runner import ConnectorRunner
    from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
    from synapse.ingestion import IngestionService
    from synapse.store import SemanticStore

    report: dict = {"domain": "hospital_ops", "files": {}}

    for fname, source_system in FILES.items():
        path = DATA_DIR / fname
        if not path.is_file():
            report["files"][fname] = {"error": "missing"}
            continue

        store = SemanticStore()
        reg = ConnectorRegistry()
        conn = CsvDropConnector(
            path=str(path),
            connector_id=f"hosp-{fname}",
            source_system=source_system,
            default_acl=["domain:clinical", "clearance:l2"],
        )
        reg.register(conn)
        runner = ConnectorRunner(
            store,
            reg,
            ingestion=IngestionService(store, domain="hospital_ops"),
            dual_path=DualPathExtractor(store, residual=HeuristicResidualExtractor()),
            domain="hospital_ops",
            use_dual_path=True,
        )
        result = runner.poll_one(f"hosp-{fname}")
        report["files"][fname] = {
            "source_system": source_system,
            "rows": result.events,
            "landed": result.landed,
            "entities_extracted": result.extracted,
            "residual_facts": result.residual_facts,
            "total_facts_in_store": len(store.facts),
            "total_entities_in_store": len(store.entities),
        }

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
