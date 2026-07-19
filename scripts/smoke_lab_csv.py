#!/usr/bin/env python3
"""
Re-run Claude's lab CSV POC: land + extract must produce facts.

  python scripts/smoke_lab_csv.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CSV = ROOT / ".data" / "kaggle_raw" / "lab_test_results_public.csv"
DB = ROOT / ".data" / "lab_demo.db"


def main() -> int:
    if not CSV.is_file():
        print(json.dumps({"ok": False, "error": f"missing {CSV}"}))
        return 2

    from synapse.connectors.csv_drop import CsvDropConnector
    from synapse.session import open_session

    # Fresh file for clean watermark (or delete old wm by new connector id)
    session = open_session(str(DB))
    try:
        conn = CsvDropConnector(
            path=str(CSV),
            connector_id="lab-csv",
            source_system="Spreadsheet",
            default_acl=["domain:clinical", "clearance:l2"],
        )
        session.connectors.register(conn)
        session.ingestion.domain = "clinical_lab"
        # Reset watermark so full file re-polls
        from synapse.connectors.base import ConnectorWatermark

        session.connectors.set_watermark(
            ConnectorWatermark(connector_id="lab-csv", position="0")
        )
        # CsvDrop uses position as start row index; "0" means start at 0
        # Actually poll: if watermark.position is digit, start = int(position)
        # advance sets to last+1. For full re-read use position before 0:
        # Looking at code: start = int(watermark.position) if digit — so 0 skips nothing
        # Wait: `if i < start: continue` — position 0 starts at row 0. Good.
        # But if previous run advanced to N, we need reset to 0.
        # set to empty? if not digit start=0. Use position "" 
        session.connectors.watermarks.pop("lab-csv", None)

        result = session.connector_runner.poll_one("lab-csv")
        ferritin = session.store.get_entity_by_name("Ferritin")
        facts_n = len(session.store.facts)
        out = {
            "ok": result.extracted > 0 and facts_n > 0,
            "poll": result.to_dict(),
            "entities": len(session.store.entities),
            "facts": facts_n,
            "ferritin": ferritin.canonical_name if ferritin else None,
            "ferritin_ontology": ferritin.ontology_type if ferritin else None,
            "sample_facts": [
                {
                    "predicate": f.predicate,
                    "object": f.object,
                    "entity": session.store.entities.get(f.subject_entity_id)
                    and session.store.entities[f.subject_entity_id].canonical_name,
                }
                for f in list(session.store.facts.values())[:8]
            ],
        }
        print(json.dumps(out, indent=2, default=str))
        return 0 if out["ok"] else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
