#!/usr/bin/env python3
"""
Active_File.md task 8 — baseline probe for the two remaining unused
healthcare datasets: pathology_health_markers/ and synthetic_medical_symptoms/.

Unlike hospital_management, these have NO identity/foreign-key column at
all (no patient_id) — each row is an anonymous observation. This tests a
genuinely different shape than tasks 1-7. No code changes here — baseline
only, same discipline as task 1.

  python scripts/smoke_health_markers_baseline.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FILES = {
    "pathology_health_markers/health_markers_dataset.csv": "Pathology-Lab",
    "synthetic_medical_symptoms/synthetic_medical_symptoms_dataset.csv": "Symptom-Checker",
}


def main() -> int:
    from synapse.connectors.csv_drop import CsvDropConnector
    from synapse.connectors.registry import ConnectorRegistry
    from synapse.connectors.runner import ConnectorRunner
    from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
    from synapse.ingestion import IngestionService
    from synapse.store import SemanticStore

    report: dict = {"domain": "hospital_ops", "files": {}}

    for rel, source_system in FILES.items():
        path = ROOT / ".data" / "kaggle_raw" / rel
        if not path.is_file():
            report["files"][rel] = {"error": "missing"}
            continue

        store = SemanticStore()
        reg = ConnectorRegistry()
        conn = CsvDropConnector(
            path=str(path),
            connector_id=f"probe-{Path(rel).stem}",
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
        result = runner.poll_one(f"probe-{Path(rel).stem}")
        report["files"][rel] = {
            "source_system": source_system,
            "rows": result.events,
            "landed": result.landed,
            "entities_extracted": result.extracted,
            "residual_facts": result.residual_facts,
        }

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
