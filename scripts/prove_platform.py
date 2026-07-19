#!/usr/bin/env python3
"""
Full platform proof harness (no secrets printed).

Walks: engines → org seed → SaaS stubs → multi-engine ask → as_of/history →
reprocess → materialize → action bus → capability matrix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from synapse.capability_matrix import capability_matrix
    from synapse.env_load import load_dotenv
    from synapse.integrations.availability import engine_availability
    from synapse.scenarios.org_discrepancy import OrgDiscrepancyCorpus
    from synapse.security import Principal
    from synapse.session import open_session

    load_dotenv()
    out: dict = {"ok": True, "steps": []}

    eng = engine_availability()
    out["steps"].append(
        {
            "step": "engines",
            "all_importable": eng.get("all_importable"),
            "all_installed": eng.get("all_installed"),
        }
    )
    if not eng.get("all_importable"):
        out["ok"] = False

    db = str(ROOT / ".data" / "prove.db")
    session = open_session(db)
    try:
        corpus = OrgDiscrepancyCorpus(store=session.store).seed()
        out["steps"].append(
            {
                "step": "org_seed",
                "entities": corpus.entity_names[:8],
                "raw": len(session.store.raw_objects),
            }
        )

        # Poll SaaS stubs + mock
        polls = []
        for cid in ("crm-stub", "slack-stub", "metrics-stub", "mock-cdc"):
            try:
                if cid == "mock-cdc":
                    from synapse.connectors.mock_cdc import MockCdcConnector

                    c = session.connectors.get(cid)
                    if isinstance(c, MockCdcConnector):
                        c.emit(
                            "BUILD SUCCESSFUL: checkout-service deployed image tag v2.4.2 automatically.",
                            acl_tags=["domain:sre", "clearance:l2"],
                        )
                pr = session.connector_runner.poll_one(cid)
                polls.append(pr.to_dict())
            except Exception as e:
                polls.append({"connector_id": cid, "error": str(e)[:120]})
        out["steps"].append({"step": "saas_stubs", "polls": polls})

        principal = Principal.from_tags(
            "prove-l2",
            [
                "domain:sre",
                "domain:revenue",
                "domain:identity",
                "domain:support",
                "clearance:l2",
                "channel:incidents",
                "channel:support",
                "channel:itsm",
            ],
        )

        asks = []
        for q, kw in (
            ("What is checkout-service?", {"entity_name": "checkout-service", "budget_class": "interactive"}),
            ("What are global themes and failure modes?", {"intent": "themes", "budget_class": "deep"}),
            ("section CrashLoopBackOff failure", {"intent": "document"}),
        ):
            a = session.orchestrator.ask(principal, q, **kw)
            asks.append(
                {
                    "q": q,
                    "allowed": a.allowed,
                    "engines": list(a.engine_hits.keys()),
                    "confidence": a.confidence,
                    "early_exit": "early_exit" in a.engine_hits,
                    "cache_hit": a.cache_hit,
                }
            )
        # cache hit second ask
        a2 = session.orchestrator.ask(
            principal,
            "What is checkout-service?",
            entity_name="checkout-service",
            budget_class="interactive",
        )
        asks.append({"q": "checkout (cached)", "cache_hit": a2.cache_hit, "allowed": a2.allowed})
        out["steps"].append({"step": "asks", "results": asks})

        ent = session.store.get_entity_by_name("checkout-service")
        if ent:
            tl = session.temporal.timeline(ent.entity_id, predicate="current_version")
            out["steps"].append({"step": "timeline", "len": len(tl)})

        rep = session.reprocess.run(limit=5)
        out["steps"].append(
            {
                "step": "reprocess",
                "episodes": rep.episodes_reprocessed,
                "facts_after": rep.facts_after,
            }
        )

        view = session.materializer.entity_fact_table()
        paths = session.materializer.write(view, ROOT / ".data" / "materialized")
        out["steps"].append(
            {"step": "materialize", "rows": len(view.rows), "paths": paths}
        )

        act = session.actions.propose(
            "create_ticket",
            {"title": "prove platform"},
            proposed_by="prove",
            risk="high",
        )
        session.actions.approve(act.action_id, by="mgr", reason="prove")
        done = session.actions.execute(act.action_id)
        out["steps"].append({"step": "action", "status": done.status.value})

        cap = capability_matrix()
        pass_n = sum(1 for c in cap["capabilities"] if str(c["status"]).startswith("pass"))
        out["steps"].append(
            {
                "step": "capability",
                "version": cap["version"],
                "pass_count": pass_n,
                "total": len(cap["capabilities"]),
            }
        )
        out["steps"].append({"step": "cache", **session.claim_cache.stats()})
        out["steps"].append(
            {
                "step": "stats",
                "entities": len(session.store.entities),
                "facts": len(session.store.facts),
                "conflicts": len(session.store.conflicts),
            }
        )
    finally:
        session.close()

    # Soft fail if engines not importable
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
