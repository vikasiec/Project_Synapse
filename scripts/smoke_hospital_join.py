#!/usr/bin/env python3
"""
Active_File.md task 5 — prove the Patient <-> Doctor <-> Appointment join.

Lands patients.csv, doctors.csv, appointments.csv (in that order) into one
store and reports, for a sample of appointments, whether patient_entity_id
and doctor_entity_id resolved to real entities — i.e. "which doctor saw
which patient" is answerable from raw CSVs with zero hand-mapping.

  python scripts/smoke_hospital_join.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / ".data" / "kaggle_raw" / "hospital_management"
DB = ROOT / ".data" / "hospital_join_demo.db"


def main() -> int:
    from synapse.connectors.csv_drop import CsvDropConnector
    from synapse.session import open_session

    if DB.is_file():
        DB.unlink()
    session = open_session(str(DB))
    try:
        session.ingestion.domain = "hospital_ops"

        for fname, source_system, cid in (
            ("patients.csv", "HIS-Patients", "hosp-patients"),
            ("doctors.csv", "HIS-Doctors", "hosp-doctors"),
            ("appointments.csv", "HIS-Scheduling", "hosp-appointments"),
        ):
            conn = CsvDropConnector(
                path=str(DATA_DIR / fname),
                connector_id=cid,
                source_system=source_system,
                default_acl=["domain:clinical", "clearance:l2"],
            )
            session.connectors.register(conn)
            session.connector_runner.poll_one(cid)

        appt_entities = [
            e for e in session.store.entities.values() if e.entity_type == "Appointment"
        ]
        resolved_patient = 0
        resolved_doctor = 0
        sample = []
        for ent in appt_entities:
            facts = {f.predicate: f.object for f in session.store.facts_for_entity(ent.entity_id)}
            has_patient = "patient_entity_id" in facts
            has_doctor = "doctor_entity_id" in facts
            resolved_patient += int(has_patient)
            resolved_doctor += int(has_doctor)
            if len(sample) < 3 and has_patient and has_doctor:
                patient_ent = session.store.entities.get(facts["patient_entity_id"])
                doctor_ent = session.store.entities.get(facts["doctor_entity_id"])
                sample.append(
                    {
                        "appointment": ent.canonical_name,
                        "date": facts.get("appointment_date"),
                        "reason": facts.get("reason_for_visit"),
                        "status": facts.get("appointment_status"),
                        "patient": patient_ent.canonical_name if patient_ent else None,
                        "doctor": doctor_ent.canonical_name if doctor_ent else None,
                        "doctor_specialization": (
                            {
                                f.predicate: f.object
                                for f in session.store.facts_for_entity(doctor_ent.entity_id)
                            }.get("specialization")
                            if doctor_ent
                            else None
                        ),
                    }
                )

        report = {
            "total_appointments": len(appt_entities),
            "patient_link_resolved": resolved_patient,
            "doctor_link_resolved": resolved_doctor,
            "fully_joined": resolved_patient == len(appt_entities)
            and resolved_doctor == len(appt_entities),
            "sample_joined_appointments": sample,
        }
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
