#!/usr/bin/env python3
"""Prove same-authority, same-time FHIR scalar conflicts surface."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / ".data" / "fhir_conflict_demo.db"


def main() -> int:
    from synapse.connectors.fhir_file import FhirDirectoryConnector
    from synapse.session import open_session

    if DB.is_file():
        DB.unlink()
    session = open_session(str(DB))
    try:
        session.ingestion.domain = "clinical_lab"
        # Land the two fixture bundles as distinct feeds.  The directory
        # connector intentionally deduplicates an identical source URI, so a
        # two-feed conflict proof must preserve each feed's source identity.
        polls = []
        for filename, source_system in (("bundle004_conflict_source_a.json", "FHIR-Lab-A"),
                                         ("bundle005_conflict_source_b.json", "FHIR-Lab-B")):
            raw = (ROOT / ".data" / "synthetic_fhir" / filename).read_text(encoding="utf-8")
            landed = session.ingestion.land(source_system, raw, ["domain:clinical", "clearance:l2"])
            session.dual_path.extract(landed.episode, landed.raw)
            polls.append({"source_system": source_system, "filename": filename, "landed": True})
        patient = session.store.get_entity_by_name("Asha Patel")
        results = [e for e in session.store.entities.values() if e.entity_type == "LabResult"]
        facts = lambda entity_id: {f.predicate: f.object for f in session.store.facts_for_entity(entity_id)}
        result = next(e for e in results if facts(e.entity_id).get("patient_entity_id") == patient.entity_id)
        conflicts = session.resolver.detect_scalar_conflicts(result.entity_id)
        report = {
            "polls": polls,
            "patient_entity_id": patient.entity_id,
            "lab_result_entity_id": result.entity_id,
            "lab_result_facts": facts(result.entity_id),
            "conflicts": [{
                "predicate": c.conflict.predicate,
                "status": c.conflict.status,
                "surface_policy": c.surface_policy,
                "competing_fact_ids": c.conflict.competing_fact_ids,
                "ranked_values": [r.fact.object for r in c.ranked],
            } for c in conflicts],
            "open_conflicts": [c.to_dict() for c in session.store.open_conflicts_for_entity(result.entity_id)],
        }
        print(json.dumps(report, indent=2, default=str))
        return 0 if any(c.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT" for c in conflicts) else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
