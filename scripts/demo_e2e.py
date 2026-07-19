#!/usr/bin/env python3
"""
End-to-end POC story (secrets never printed):

1. poc-status (all four blueprint engines)
2. Seed org multi-domain discrepancy corpus
3. Poll file inbox → dual-path extract
4. Budgeted multi-engine ask (entity + GraphRAG + PageIndex)
5. Optional Graphiti search (uses free-tier budget — limited)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from synapse.env_load import load_dotenv
    from synapse.connectors.file_jsonl import JsonlFileConnector
    from synapse.graphiti_ops import GraphitiOps
    from synapse.llm_gemini import create_residual_extractor, gemini_configured
    from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
    from synapse.session import open_session

    load_dotenv()
    out: dict = {"ok": True, "steps": []}

    from synapse.integrations.availability import engine_availability

    out["steps"].append(
        {
            "step": "status",
            "gemini": gemini_configured(),
            "path_b": create_residual_extractor().name,
            "graphiti": GraphitiOps().status(),
            "engines": engine_availability(),
        }
    )

    db = str(ROOT / ".data" / "demo.db")
    session = open_session(db)
    try:
        from synapse.scenarios.org_discrepancy import OrgDiscrepancyCorpus

        corpus = OrgDiscrepancyCorpus(store=session.store).seed(skip_if_populated=True)
        session.engines.rebuild_communities()
        session.engines.index_episode_docs()
        out["steps"].append(
            {
                "step": "org_corpus",
                "entities": corpus.entity_names,
                "extra_ingested": corpus.extra_ingested,
                "raw": len(session.store.raw_objects),
            }
        )

        inbox = ROOT / ".data" / "inbox" / "events.jsonl"
        conn = JsonlFileConnector(
            path=inbox, connector_id="inbox-jsonl", source_system="FileDrop"
        )
        session.connectors.register(conn)
        poll = session.connector_runner.poll_one("inbox-jsonl")
        out["steps"].append({"step": "inbox_poll", **poll.to_dict()})

        # Materialize conflicts for services/customers
        for ent in list(session.store.entities.values()):
            if ent.status.value == "active":
                session.resolver.detect_scalar_conflicts(ent.entity_id)

        # Query a couple entities with multi-domain principal
        principal = CheckoutIncidentScenario.principal_l2()
        # broaden principal for revenue samples in inbox
        from synapse.security import Principal

        principal = Principal.from_tags(
            "demo-l2",
            [
                "domain:sre",
                "domain:revenue",
                "domain:identity",
                "clearance:l2",
                "channel:incidents",
                "channel:support",
                "channel:itsm",
            ],
        )
        queries = []
        for name in ("payments-service", "Northwind Traders", "Sam Rivera"):
            r = session.query.ask(principal, entity_name=name)
            queries.append(
                {
                    "entity": name,
                    "allowed": r.allowed,
                    "conflicts": [v.conflict.predicate for v in r.conflict_views],
                    "statement": (r.claim.statement[:220] if r.claim else None),
                }
            )
        out["steps"].append({"step": "semantic_queries", "results": queries})

        # Multi-engine orchestrated asks
        orch_results = []
        for q, kw in (
            ("What is checkout-service version conflict?", {"entity_name": "checkout-service"}),
            ("What are global themes and failure modes?", {"intent": "themes"}),
            ("Find section about CrashLoopBackOff failure modes", {"intent": "document"}),
        ):
            ans = session.orchestrator.ask(principal, q, **kw)
            orch_results.append(
                {
                    "question": q,
                    "allowed": ans.allowed,
                    "engines": list(ans.engine_hits.keys()),
                    "confidence": ans.confidence,
                    "gaps": ans.gaps[:3],
                    "statement": (ans.statement or "")[:240],
                    "budget": ans.budget.budget_class.value,
                }
            )
        out["steps"].append({"step": "orchestrator_asks", "results": orch_results})
        out["steps"].append(
            {"step": "ontology", "summary": session.ontology.describe()}
        )

        # Platform gap closures
        session.drift.observe_all()
        out["steps"].append({"step": "drift", "describe": session.drift.describe()})
        rep = session.reprocess.run(limit=5, actor="demo:reprocess")
        out["steps"].append({"step": "reprocess", **rep.to_dict()})
        view = session.materializer.entity_fact_table()
        paths = session.materializer.write(view, ROOT / ".data" / "materialized")
        out["steps"].append(
            {
                "step": "materialize",
                "rows": len(view.rows),
                "trust": view.trust_score,
                "paths": paths,
            }
        )
        act = session.actions.propose(
            "create_ticket",
            {"title": "demo incident"},
            proposed_by="demo",
            risk="high",
        )
        session.actions.approve(act.action_id, by="demo-mgr", reason="demo")
        done = session.actions.execute(act.action_id)
        out["steps"].append({"step": "action_bus", "status": done.status.value})

        from synapse.capability_matrix import capability_matrix

        out["steps"].append(
            {
                "step": "capability",
                "pass_count": sum(
                    1
                    for c in capability_matrix()["capabilities"]
                    if str(c["status"]).startswith("pass")
                ),
            }
        )

        # Local mirror graph
        snap = session.sync_graph()
        out["steps"].append(
            {
                "step": "local_graph",
                "backend": snap.backend,
                "nodes": len(snap.nodes),
                "edges": len(snap.edges),
            }
        )

        # Live Graphiti search (optional — may use LLM budget)
        if out["steps"][0]["graphiti"].get("neo4j_ready"):
            ops = GraphitiOps()
            try:
                hits = ops.search("checkout service canary", num_results=5)
                out["steps"].append(
                    {
                        "step": "graphiti_search",
                        "hits": [h.to_dict() for h in hits[:5]],
                    }
                )
            except Exception as e:
                import os

                msg = str(e)
                for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "NEO4J_PASSWORD"):
                    v = os.environ.get(k)
                    if v:
                        msg = msg.replace(v, "***")
                out["steps"].append({"step": "graphiti_search", "error": msg[:200]})
            finally:
                ops.close()

        out["store"] = {
            "raw": len(session.store.raw_objects),
            "entities": len(session.store.entities),
            "facts": len(session.store.facts),
            "open_conflicts": sum(
                1 for c in session.store.conflicts.values() if c.status.value == "open"
            ),
        }
    finally:
        session.close()

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
