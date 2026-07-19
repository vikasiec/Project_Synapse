#!/usr/bin/env python3
"""
POC smoke (no secrets printed).

1) Load .env
2) Confirm Gemini residual Path B
3) Dual-path extract on one sample (1 Gemini call if residual present)
4) Optional Graphiti+Neo4j sync if GRAPHITI_ENABLED=1
5) File-drop connector poll from .data/inbox
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from synapse.env_load import load_dotenv
    from synapse.llm_gemini import gemini_configured, create_residual_extractor
    from synapse.session import open_session
    from synapse.dual_path import DualPathExtractor
    from synapse.ingestion import IngestionService
    from synapse.connectors.file_jsonl import JsonlFileConnector

    load_dotenv()
    report: dict = {"steps": []}

    # --- Gemini ---
    configured = gemini_configured()
    backend = create_residual_extractor().name
    report["steps"].append(
        {"step": "gemini", "configured": configured, "backend": backend}
    )
    if not configured:
        report["ok"] = False
        report["error"] = "GEMINI_API_KEY not loaded"
        print(json.dumps(report, indent=2))
        return 1

    session = open_session(str(ROOT / ".data" / "smoke.db"))
    try:
        # --- dual path residual (single call budget) ---
        dual = DualPathExtractor(session.store)
        ing = IngestionService(session.store)
        landed = ing.land(
            "GitHub-CI",
            "BUILD SUCCESSFUL: checkout-service deployed image tag v9.9.1 automatically.\n"
            "note: on-call suspects partial EU traffic still on canary; watch error budgets.\n",
            ["domain:sre", "clearance:l2"],
        )
        out = dual.extract(landed.episode, landed.raw)
        report["steps"].append(
            {
                "step": "dual_path",
                "entity": out.entity_name,
                "path_b_backend": out.path_b_backend,
                "path_b_used": out.path_b_used,
                "det_facts": len(out.deterministic_facts),
                "residual_facts": len(out.residual_facts),
                "predicates": [f.predicate for f in out.all_facts],
            }
        )

        # --- graph sync ---
        snap = session.sync_graph()
        gstats = session.graph.stats()
        report["steps"].append(
            {
                "step": "graph",
                "backend": snap.backend,
                "nodes": len(snap.nodes),
                "edges": len(snap.edges),
                "episodes_pushed": gstats.get("episodes_pushed"),
                "last_error": gstats.get("last_error"),
            }
        )

        # --- file inbox connector ---
        inbox = ROOT / ".data" / "inbox" / "events.jsonl"
        if inbox.is_file():
            conn = JsonlFileConnector(
                path=inbox,
                connector_id="inbox-jsonl",
                source_system="FileDrop",
            )
            session.connectors.register(conn)
            poll = session.connector_runner.poll_one("inbox-jsonl")
            report["steps"].append({"step": "file_inbox", **poll.to_dict()})
        else:
            report["steps"].append({"step": "file_inbox", "skipped": True})

        report["ok"] = True
        report["store"] = {
            "raw": len(session.store.raw_objects),
            "entities": len(session.store.entities),
            "facts": len(session.store.facts),
        }
    finally:
        session.close()

    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
