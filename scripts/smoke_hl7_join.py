#!/usr/bin/env python3
"""
Active_File.md task 11 — prove real HL7v2 message parsing, not another CSV.

Lands 3 synthetic ORU^R01 messages (one for a brand-new patient, one for
P001 "David Williams" who already exists from the hospital_management CSVs
-- proving cross-format entity resolution -- and one with abnormal flags).

  python scripts/smoke_hl7_join.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB = ROOT / ".data" / "hl7_demo.db"


def main() -> int:
    from synapse.connectors.hl7_file import Hl7DirectoryConnector
    from synapse.session import open_session

    if DB.is_file():
        DB.unlink()
    session = open_session(str(DB))
    try:
        # Pre-land David Williams from hospital_management via CSV, exactly
        # as the real HIS system already has him -- this is the entity the
        # HL7 message for P001 must resolve to, not duplicate.
        session.ingestion.domain = "hospital_ops"
        r = session.ingestion.land(
            "HIS-Patients",
            "Patient_id: P001\nFirst_name: David\nLast_name: Williams\n"
            "Insurance_provider: WellnessCorp\n",
            ["domain:clinical", "clearance:l2"],
        )
        pre_existing = session.dual_path.extract(r.episode, r.raw)
        pre_existing_id = pre_existing.entity_name and session.store.get_entity_by_name(
            "David Williams"
        ).entity_id

        conn = Hl7DirectoryConnector(
            path=str(ROOT / ".data" / "synthetic_hl7"), connector_id="hl7-feed"
        )
        session.connectors.register(conn)
        poll = session.connector_runner.poll_one("hl7-feed")

        lab_results = [
            e for e in session.store.entities.values() if e.entity_type == "LabResult"
        ]
        patients = [
            e for e in session.store.entities.values() if e.entity_type == "Patient"
        ]

        def facts_of(entity_id):
            return {f.predicate: f.object for f in session.store.facts_for_entity(entity_id)}

        david = session.store.get_entity_by_name("David Williams")
        david_still_one_entity = david.entity_id == pre_existing_id

        david_results = [
            r for r in lab_results if facts_of(r.entity_id).get("patient_entity_id") == david.entity_id
        ]

        report = {
            "poll": poll.to_dict(),
            "patient_entities": len(patients),
            "labresult_entities": len(lab_results),
            "david_williams_stayed_one_entity_across_csv_and_hl7": david_still_one_entity,
            "david_williams_hl7_results": sorted(r.canonical_name for r in david_results),
            "sample_result_HGB": facts_of(
                next(r.entity_id for r in lab_results if r.canonical_name == "Hemoglobin")
            ),
            "sample_result_LDL_abnormal": facts_of(
                next(r.entity_id for r in lab_results if r.canonical_name == "LDL Cholesterol")
            ),
        }
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
