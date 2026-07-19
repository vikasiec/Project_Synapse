#!/usr/bin/env python3
"""
Active_File.md task 4 — prove multi-source conflict detection in healthcare.

Lands patients.csv (HIS-Patients, system of record) and a synthesized
patients_front_desk.csv (FrontDesk-Intake, re-entered at check-in) for the
same 10 patients into one store, confirms they resolve to the same Patient
entity via strict-identity ID blocking (patient_id, not name), and reports
which patients now have an OPEN scalar conflict vs. which agree cleanly.

  python scripts/smoke_hospital_conflict.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / ".data" / "kaggle_raw" / "hospital_management"
DB = ROOT / ".data" / "hospital_conflict_demo.db"


def main() -> int:
    from synapse.connectors.csv_drop import CsvDropConnector
    from synapse.session import open_session

    if DB.is_file():
        DB.unlink()
    session = open_session(str(DB))
    try:
        session.ingestion.domain = "hospital_ops"

        for fname, source_system, cid in (
            ("patients.csv", "HIS-Patients", "hosp-patients-sor"),
            ("patients_front_desk.csv", "FrontDesk-Intake", "hosp-patients-frontdesk"),
        ):
            conn = CsvDropConnector(
                path=str(DATA_DIR / fname),
                connector_id=cid,
                source_system=source_system,
                default_acl=["domain:clinical", "clearance:l2"],
            )
            session.connectors.register(conn)
            session.connector_runner.poll_one(cid)

        # Only the first 10 patients exist in both files — restrict report to those
        target_ids = {f"P{n:03d}" for n in range(1, 11)}
        rows = []
        total_entities_for_10 = 0
        for pid in sorted(target_ids):
            ent = None
            for e in session.store.entities.values():
                if any(
                    x.get("system") == "HIS-Patients" and x.get("id") == pid
                    for x in e.external_ids
                ):
                    ent = e
                    break
            if ent is None:
                rows.append({"patient_id": pid, "error": "not found"})
                continue
            total_entities_for_10 += 1
            views = session.resolver.detect_scalar_conflicts(ent.entity_id)
            open_conflicts = [
                {
                    "predicate": v.conflict.predicate,
                    "status": v.conflict.status.value,
                    "values": sorted(
                        {
                            str(f.object)
                            for f in session.store.facts_for_entity(ent.entity_id)
                            if f.predicate == v.conflict.predicate
                        }
                    ),
                    "preferred_source": v.preferred.fact.source_system if v.preferred else None,
                    "preferred_value": v.preferred.fact.object if v.preferred else None,
                }
                for v in views
                if v.conflict.status.value == "open"
            ]
            rows.append(
                {
                    "patient_id": pid,
                    "entity_id": ent.entity_id,
                    "canonical_name": ent.canonical_name,
                    "sources_merged": sorted({x["system"] for x in ent.external_ids}),
                    "open_conflicts": open_conflicts,
                }
            )

        report = {
            "entities_resolved_for_10_patients": total_entities_for_10,
            "expected": 10,
            "single_entity_per_patient": total_entities_for_10 == 10,
            "patients_with_conflict": sum(1 for r in rows if r.get("open_conflicts")),
            "patients_clean": sum(
                1 for r in rows if "open_conflicts" in r and not r["open_conflicts"]
            ),
            "detail": rows,
        }
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
