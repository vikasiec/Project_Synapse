"""
Project Synapse multi-command CLI.

  python -m synapse simulate
  python -m synapse seed --db .data/synapse.db
  python -m synapse query checkout-service --principal l2
  python -m synapse conflicts
  python -m synapse pin <conflict_id> --fact <fact_id> --by user --reason "..."
  python -m synapse eval
  python -m synapse serve --port 8787
  python -m synapse audit
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from synapse.harness import run_checkout_incident_simulation
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.security import Principal
from synapse.session import open_session


def _principal(name: str) -> Principal:
    if name == "l1":
        return Principal.from_tags(
            "cli-l1",
            ["domain:sre", "domain:revenue", "domain:identity", "clearance:l1"],
        )
    if name == "l2":
        return Principal.from_tags(
            "cli-l2",
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
    # free-form: comma-separated tags, id=cli
    tags = [t.strip() for t in name.split(",") if t.strip()]
    return Principal.from_tags("cli-user", tags or ["domain:sre", "clearance:l2"])


def cmd_simulate(args: argparse.Namespace) -> int:
    run_checkout_incident_simulation(
        verbose=not args.quiet,
        db_path=args.db,
        demonstrate_pin=not args.no_pin,
    )
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        before = len(session.store.raw_objects)
        extra_meta: dict = {}
        if args.scenario in ("billing", "revenue", "crm"):
            from synapse.scenarios.billing_customer import BillingCustomerScenario

            bundle = BillingCustomerScenario(store=session.store).seed(
                skip_if_populated=args.skip_if_populated
            )
            entity_hint = bundle.entity_name
        elif args.scenario in ("identity", "access", "iam"):
            from synapse.scenarios.identity_access import IdentityAccessScenario

            bundle = IdentityAccessScenario(store=session.store).seed(
                skip_if_populated=args.skip_if_populated
            )
            entity_hint = bundle.entity_name
        elif args.scenario in ("org", "multi", "discrepancy", "all"):
            from synapse.scenarios.org_discrepancy import OrgDiscrepancyCorpus

            corpus = OrgDiscrepancyCorpus(store=session.store).seed(
                skip_if_populated=args.skip_if_populated
            )
            entity_hint = ", ".join(corpus.entity_names[:6])
            extra_meta = {
                "domains": corpus.domains,
                "extra_ingested": corpus.extra_ingested,
                "entity_names": corpus.entity_names,
            }
            bundle = corpus
        else:
            bundle = CheckoutIncidentScenario(store=session.store).seed(
                skip_if_populated=args.skip_if_populated
            )
            entity_hint = bundle.entity_name
        session.sync_graph()
        session.engines.rebuild_communities()
        session.engines.index_episode_docs()
        after = len(session.store.raw_objects)
        print(
            json.dumps(
                {
                    "scenario": args.scenario,
                    "entity_hint": entity_hint,
                    "raw_before": before,
                    "raw_after": after,
                    "entities": len(session.store.entities),
                    "facts": len(session.store.facts),
                    "db": args.db,
                    **extra_meta,
                },
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """Budgeted multi-engine orchestrated ask (org-wide §6 lifecycle)."""
    session = open_session(args.db)
    try:
        ans = session.orchestrator.ask(
            _principal(args.principal),
            args.question,
            intent=args.intent,
            entity_name=args.entity,
            budget_class=args.budget,
            as_of=getattr(args, "as_of", None),
        )
        print(json.dumps(ans.to_dict(), indent=2))
        return 0 if ans.allowed else 2
    finally:
        session.close()


def cmd_query(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        result = session.query.ask(
            _principal(args.principal),
            entity_name=args.entity,
            intent=args.intent,
            as_of=getattr(args, "as_of", None),
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.allowed else 2
    finally:
        session.close()


def cmd_history(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        ent = session.store.get_entity_by_name(args.entity)
        if not ent:
            print(json.dumps({"error": f"entity not found: {args.entity}"}))
            return 1
        rows = session.temporal.timeline(ent.entity_id, predicate=args.predicate)
        print(
            json.dumps(
                {
                    "entity": ent.canonical_name,
                    "entity_id": ent.entity_id,
                    "predicate": args.predicate,
                    "timeline": rows,
                },
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


def cmd_conflicts(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        # Materialize open conflicts via detect on known entities
        for ent in session.store.entities.values():
            session.resolver.detect_scalar_conflicts(ent.entity_id)
        rows = []
        for c in session.store.conflicts.values():
            if args.open_only and c.status.value != "open":
                continue
            rows.append(c.to_dict())
        print(json.dumps(rows, indent=2))
    finally:
        session.close()
    return 0


def cmd_pin(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        result = session.adjudication.human_pin(
            args.conflict_id,
            chosen_fact_id=args.fact,
            adjudicator=args.by,
            reason=args.reason,
        )
        print(json.dumps(result.conflict.to_dict(), indent=2))
    finally:
        session.close()
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from synapse.eval_runner import evaluate_pack

    store = None
    session = None
    # Suite always uses isolated stores; single pack may use --db only if forced
    if args.db and args.pack not in ("all", "suite", "*"):
        session = open_session(args.db)
        store = session.store
    try:
        report = evaluate_pack(args.pack, store=store)
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.ok else 1
    finally:
        if session:
            session.close()


def cmd_audit(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        events = session.store.audit.to_list()
        if args.type:
            events = [e for e in events if e["event_type"] == args.type]
        print(json.dumps(events[-args.limit :], indent=2))
    finally:
        session.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        payload = args.payload
        if args.file:
            payload = open(args.file, encoding="utf-8").read()
        if payload is None:
            print("Provide --payload or --file", file=sys.stderr)
            return 2
        tags = [t.strip() for t in args.acl.split(",") if t.strip()]
        result = session.ingestion.land(
            args.source,
            payload,
            tags,
            actor=args.by,
        )
        extracted = session.extractor.extract_from_episode(result.episode, result.raw)
        print(
            json.dumps(
                {
                    "deduplicated": result.deduplicated,
                    "raw": result.raw.to_dict(),
                    "episode_id": result.episode.episode_id,
                    "facts": len(extracted.facts) if extracted else 0,
                    "entity": extracted.entity.canonical_name if extracted else None,
                },
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        result = session.er.merge(
            args.survivor,
            args.loser,
            adjudicator=args.by,
            reason=args.reason,
        )
        print(
            json.dumps(
                {
                    "survivor": result.survivor.to_dict(),
                    "loser": result.loser.to_dict(),
                    "facts_rewritten": result.facts_rewritten,
                },
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from synapse.export_import import export_store_to_file

    session = open_session(args.db)
    try:
        path = export_store_to_file(session.store, args.out)
        print(json.dumps({"exported": str(path), "raw": len(session.store.raw_objects)}, indent=2))
    finally:
        session.close()
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from synapse.export_import import import_store_from_file

    session = open_session(args.db)
    try:
        import_store_from_file(args.path, store=session.store)
        print(
            json.dumps(
                {
                    "imported_from": args.path,
                    "raw": len(session.store.raw_objects),
                    "entities": len(session.store.entities),
                    "facts": len(session.store.facts),
                },
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        snap = session.sync_graph()
        if args.entity:
            ent = session.store.get_entity_by_name(args.entity)
            eid = ent.entity_id if ent else args.entity
            print(json.dumps(session.graph.neighborhood(eid, depth=args.depth), indent=2))
        else:
            print(json.dumps({"stats": session.graph.stats(), "snapshot_meta": {
                "backend": snap.backend,
                "built_at": snap.built_at,
                "nodes": len(snap.nodes),
                "edges": len(snap.edges),
            }}, indent=2))
    finally:
        session.close()
    return 0


def cmd_connectors(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        print(json.dumps(session.connectors.list(), indent=2))
    finally:
        session.close()
    return 0


def cmd_poll(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        if args.connector:
            results = [session.connector_runner.poll_one(args.connector)]
        else:
            results = session.connector_runner.poll_all()
        session.sync_graph()
        print(json.dumps([r.to_dict() for r in results], indent=2))
    finally:
        session.close()
    return 0


def cmd_register_jsonl(args: argparse.Namespace) -> int:
    from synapse.connectors.file_jsonl import JsonlFileConnector

    session = open_session(args.db)
    try:
        conn = JsonlFileConnector(
            path=args.path,
            connector_id=args.id,
            source_system=args.source,
        )
        session.connectors.register(conn)
        # Persist registry only in-memory for this process; poll immediately optional
        if args.poll:
            result = session.connector_runner.poll_one(args.id)
            session.sync_graph()
            print(json.dumps({"registered": conn.describe(), "poll": result.to_dict()}, indent=2))
        else:
            print(json.dumps({"registered": conn.describe()}, indent=2))
    finally:
        session.close()
    return 0


def cmd_register_csv(args: argparse.Namespace) -> int:
    from synapse.connectors.csv_drop import CsvDropConnector

    session = open_session(args.db)
    try:
        conn = CsvDropConnector(
            path=args.path,
            connector_id=args.id,
            source_system=args.source,
        )
        session.connectors.register(conn)
        if args.poll:
            result = session.connector_runner.poll_one(args.id)
            session.sync_graph()
            print(
                json.dumps(
                    {"registered": conn.describe(), "poll": result.to_dict()},
                    indent=2,
                )
            )
        else:
            print(json.dumps({"registered": conn.describe()}, indent=2))
    finally:
        session.close()
    return 0


def cmd_mock_emit(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        from synapse.connectors.mock_cdc import MockCdcConnector

        conn = session.connectors.get(args.connector)
        if not isinstance(conn, MockCdcConnector):
            print(json.dumps({"error": "connector is not MockCdcConnector"}), indent=2)
            return 2
        ev = conn.emit(args.payload, acl_tags=[t.strip() for t in args.acl.split(",") if t.strip()])
        if args.poll:
            result = session.connector_runner.poll_one(args.connector)
            session.sync_graph()
            print(json.dumps({"emitted": ev.to_dict(), "poll": result.to_dict()}, indent=2))
        else:
            print(json.dumps({"emitted": ev.to_dict()}, indent=2))
    finally:
        session.close()
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    """Register + poll default .data/inbox/events.jsonl file drop."""
    from pathlib import Path

    from synapse.connectors.file_jsonl import JsonlFileConnector

    root = Path(__file__).resolve().parents[1]
    path = Path(args.path) if args.path else root / ".data" / "inbox" / "events.jsonl"
    session = open_session(args.db)
    try:
        if not path.is_file():
            print(json.dumps({"error": f"missing inbox file: {path}"}, indent=2))
            return 2
        conn = JsonlFileConnector(
            path=path,
            connector_id=args.id,
            source_system=args.source,
        )
        session.connectors.register(conn)
        result = session.connector_runner.poll_one(args.id)
        # Local graph mirror (not full Graphiti push of all episodes)
        session.sync_graph()
        # Query summary of entities
        entities = [
            {
                "name": e.canonical_name,
                "type": e.entity_type,
                "status": e.status.value,
            }
            for e in session.store.entities.values()
            if e.status.value == "active"
        ]
        print(
            json.dumps(
                {
                    "inbox": str(path),
                    "poll": result.to_dict(),
                    "entities": entities,
                    "facts": len(session.store.facts),
                    "conflicts_open": len(
                        [c for c in session.store.conflicts.values() if c.status.value == "open"]
                    ),
                },
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


def cmd_graphiti_search(args: argparse.Namespace) -> int:
    from synapse.graphiti_ops import GraphitiOps

    ops = GraphitiOps()
    try:
        hits = ops.search(args.query, num_results=args.limit)
        print(json.dumps([h.to_dict() for h in hits], indent=2))
        return 0
    except Exception as e:
        import os

        msg = str(e)
        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "NEO4J_PASSWORD"):
            v = os.environ.get(k)
            if v:
                msg = msg.replace(v, "***")
        print(json.dumps({"error": msg[:300]}, indent=2))
        return 1
    finally:
        ops.close()


def cmd_engines(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        if args.rebuild:
            session.engines.rebuild_communities()
            session.engines.index_episode_docs()
        print(json.dumps(session.engines.describe(), indent=2))
    finally:
        session.close()
    return 0


def cmd_themes(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        session.engines.rebuild_communities()
        hits = session.engines.route_query(args.question, intent="themes")
        print(json.dumps(hits, indent=2))
    finally:
        session.close()
    return 0


def cmd_doc_route(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        if args.text:
            text = args.text
            title = "cli-doc"
        elif args.file:
            from pathlib import Path

            text = Path(args.file).read_text(encoding="utf-8")
            title = Path(args.file).name
        else:
            session.engines.index_episode_docs()
            hits = session.engines.route_query(args.query, intent="document")
            print(json.dumps(hits, indent=2))
            return 0
        tree = session.engines.index_document(text, title=title)
        routed = session.engines.pageindex.route(tree, args.query, top_k=args.top_k)
        print(
            json.dumps(
                {"doc": tree.to_dict(), "route": routed},
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


def cmd_poc_status(args: argparse.Namespace) -> int:
    from synapse.env_load import load_dotenv
    from synapse.capability_matrix import capability_matrix
    from synapse.cost_model import describe_cost_model
    from synapse.graphiti_ops import GraphitiOps
    from synapse.integrations.availability import engine_availability
    from synapse.integrations.graphiti_adapter import graphiti_status
    from synapse.integrations.graphrag_adapter import create_graphrag_adapter
    from synapse.integrations.pageindex_adapter import create_pageindex_adapter
    from synapse.integrations.data_juicer_adapter import create_prep_adapter
    from synapse.llm_gemini import create_residual_extractor, gemini_configured

    load_dotenv()
    gstat = GraphitiOps().status()
    print(
        json.dumps(
            {
                "version": "0.14.0",
                "gemini_configured": gemini_configured(),
                "path_b_backend": create_residual_extractor().name,
                "graphiti": gstat,
                "blueprint_engines": engine_availability(),
                "adapters": {
                    "graphiti": graphiti_status(),
                    "graphrag": create_graphrag_adapter().describe(),
                    "pageindex": create_pageindex_adapter().describe(),
                    "data_juicer": create_prep_adapter().describe(),
                },
                "capability_matrix": capability_matrix(),
                "cost_model": describe_cost_model(),
                "inbox_default": str(
                    __import__("pathlib").Path(__file__).resolve().parents[1]
                    / ".data"
                    / "inbox"
                    / "events.jsonl"
                ),
            },
            indent=2,
        )
    )
    return 0


def cmd_reprocess(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        report = session.reprocess.run(
            domain=args.domain,
            limit=args.limit,
            actor="cli:reprocess",
        )
        session.claim_cache.invalidate_all()
        print(json.dumps(report.to_dict(), indent=2))
    finally:
        session.close()
    return 0


def cmd_materialize(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        view = (
            session.materializer.conflict_table()
            if args.view == "conflicts"
            else session.materializer.entity_fact_table()
        )
        paths = session.materializer.write(view, args.out)
        print(
            json.dumps(
                {"view": view.to_dict(), "paths": paths},
                indent=2,
                default=str,
            )
        )
    finally:
        session.close()
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        # seed baseline then second pass only reports true drift; for POC
        # first call establishes baselines, --scan twice optional
        session.drift.observe_all()
        events = session.drift.observe_all() if args.rescan else []
        # If store was empty of baselines before first observe, events empty —
        # still describe shapes
        print(
            json.dumps(
                {
                    "new_events": [e.to_dict() for e in events],
                    "describe": session.drift.describe(),
                },
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


def cmd_action_propose(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        payload = json.loads(args.payload) if args.payload.startswith("{") else {"text": args.payload}
        a = session.actions.propose(
            args.type,
            payload,
            proposed_by=args.by,
            risk=args.risk,
        )
        print(json.dumps(a.to_dict(), indent=2))
    finally:
        session.close()
    return 0


def cmd_action_decide(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        if args.approve:
            a = session.actions.approve(args.action_id, by=args.by, reason=args.reason)
        elif args.reject:
            a = session.actions.reject(args.action_id, by=args.by, reason=args.reason)
        else:
            print(json.dumps({"error": "pass --approve or --reject"}))
            return 1
        if args.execute and a.status.value == "approved":
            a = session.actions.execute(args.action_id, by=args.by)
        print(json.dumps(a.to_dict(), indent=2))
    finally:
        session.close()
    return 0


def cmd_actions(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        print(json.dumps(session.actions.list(status=args.status), indent=2))
    finally:
        session.close()
    return 0


def cmd_capability(args: argparse.Namespace) -> int:
    from synapse.capability_matrix import capability_matrix

    print(json.dumps(capability_matrix(), indent=2))
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    from synapse.cost_model import describe_cost_model, estimate_query_cost

    if args.budget:
        print(
            json.dumps(
                estimate_query_cost(args.budget, qps=args.qps),
                indent=2,
            )
        )
    else:
        print(json.dumps(describe_cost_model(), indent=2))
    return 0


def cmd_webhook(args: argparse.Namespace) -> int:
    session = open_session(args.db)
    try:
        from synapse.connectors.webhook_inbox import WebhookInboxConnector

        try:
            conn = session.connectors.get("webhook-inbox")
        except KeyError:
            conn = WebhookInboxConnector(connector_id="webhook-inbox")
            session.connectors.register(conn)
        if not isinstance(conn, WebhookInboxConnector):
            print(json.dumps({"error": "webhook-inbox not WebhookInboxConnector"}))
            return 1
        row = conn.enqueue(
            args.payload,
            source_system=args.source,
            acl_tags=[t.strip() for t in args.acl.split(",") if t.strip()],
        )
        out: dict = {"enqueued": row}
        if args.poll:
            result = session.connector_runner.poll_one("webhook-inbox")
            out["poll"] = result.to_dict()
            session.sync_graph()
        print(json.dumps(out, indent=2))
    finally:
        session.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from synapse.api import serve

    serve(host=args.host, port=args.port, db_path=args.db)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="synapse", description="Project Synapse CLI")
    sub = p.add_subparsers(dest="command", required=True)

    sim = sub.add_parser("simulate", help="Run full incident simulation harness")
    sim.add_argument("--db", default=None)
    sim.add_argument("--no-pin", action="store_true")
    sim.add_argument("--quiet", action="store_true")
    sim.set_defaults(func=cmd_simulate)

    seed = sub.add_parser("seed", help="Seed a scenario pack into store")
    seed.add_argument("--db", default=None)
    seed.add_argument(
        "--scenario",
        default="checkout",
        choices=["checkout", "billing", "identity", "org"],
        help="Scenario pack: checkout | billing | identity | org (multi-domain)",
    )
    seed.add_argument("--skip-if-populated", action="store_true")
    seed.set_defaults(func=cmd_seed)

    q = sub.add_parser("query", help="Query an entity")
    q.add_argument("entity")
    q.add_argument("--db", default=None)
    q.add_argument("--principal", default="l2", help="l1 | l2 | tag1,tag2,...")
    q.add_argument("--intent", default="entity_lookup")
    q.add_argument("--as-of", dest="as_of", default=None, help="ISO timestamp for point-in-time view")
    q.set_defaults(func=cmd_query)

    hist = sub.add_parser("history", help="Temporal fact timeline for an entity")
    hist.add_argument("entity")
    hist.add_argument("--predicate", default=None)
    hist.add_argument("--db", default=None)
    hist.set_defaults(func=cmd_history)

    ask = sub.add_parser(
        "ask",
        help="Budgeted multi-engine ask (entity + GraphRAG + PageIndex fusion)",
    )
    ask.add_argument("question")
    ask.add_argument("--db", default=None)
    ask.add_argument("--principal", default="l2")
    ask.add_argument("--intent", default=None, help="entity_lookup|themes|document|hybrid")
    ask.add_argument("--entity", default=None, help="Force entity name")
    ask.add_argument(
        "--budget",
        default=None,
        choices=["interactive", "standard", "deep"],
        help="Budget class override",
    )
    ask.add_argument("--as-of", dest="as_of", default=None, help="Point-in-time ISO")
    ask.set_defaults(func=cmd_ask)

    c = sub.add_parser("conflicts", help="List conflicts")
    c.add_argument("--db", default=None)
    c.add_argument("--open-only", action="store_true")
    c.set_defaults(func=cmd_conflicts)

    pin = sub.add_parser("pin", help="Human-pin a conflict")
    pin.add_argument("conflict_id")
    pin.add_argument("--fact", required=True)
    pin.add_argument("--by", required=True)
    pin.add_argument("--reason", required=True)
    pin.add_argument("--db", default=None)
    pin.set_defaults(func=cmd_pin)

    ev = sub.add_parser("eval", help="Run golden-set evaluation")
    ev.add_argument(
        "--pack",
        default="all",
        help="checkout | billing | identity | org | all (default: all)",
    )
    ev.add_argument("--db", default=None, help="Optional store (single-pack only)")
    ev.set_defaults(func=cmd_eval)

    au = sub.add_parser("audit", help="Show audit events")
    au.add_argument("--db", default=None)
    au.add_argument("--type", default=None)
    au.add_argument("--limit", type=int, default=50)
    au.set_defaults(func=cmd_audit)

    ing = sub.add_parser("ingest", help="Land a single payload")
    ing.add_argument("--source", required=True)
    ing.add_argument("--payload", default=None)
    ing.add_argument("--file", default=None)
    ing.add_argument("--acl", default="domain:sre,clearance:l2")
    ing.add_argument("--by", default="cli:user")
    ing.add_argument("--db", default=None)
    ing.set_defaults(func=cmd_ingest)

    mg = sub.add_parser("merge", help="Merge two entities (ER)")
    mg.add_argument("--survivor", required=True)
    mg.add_argument("--loser", required=True)
    mg.add_argument("--by", required=True)
    mg.add_argument("--reason", required=True)
    mg.add_argument("--db", default=None)
    mg.set_defaults(func=cmd_merge)

    ex = sub.add_parser("export", help="Export store snapshot to JSON")
    ex.add_argument("--out", required=True, help="Output JSON path")
    ex.add_argument("--db", default=None)
    ex.set_defaults(func=cmd_export)

    im = sub.add_parser("import", help="Import store snapshot from JSON")
    im.add_argument("path", help="Input JSON path")
    im.add_argument("--db", default=None)
    im.set_defaults(func=cmd_import)

    gr = sub.add_parser("graph", help="Build local graph memory view")
    gr.add_argument("--db", default=None)
    gr.add_argument("--entity", default=None, help="Neighborhood around entity name/id")
    gr.add_argument("--depth", type=int, default=1)
    gr.set_defaults(func=cmd_graph)

    lc = sub.add_parser("connectors", help="List registered connectors")
    lc.add_argument("--db", default=None)
    lc.set_defaults(func=cmd_connectors)

    pl = sub.add_parser("poll", help="Poll CDC connectors into the store")
    pl.add_argument("--connector", default=None, help="Connector id (default: all)")
    pl.add_argument("--db", default=None)
    pl.set_defaults(func=cmd_poll)

    rj = sub.add_parser("register-jsonl", help="Register a JSONL file connector")
    rj.add_argument("--path", required=True)
    rj.add_argument("--id", default="jsonl-file")
    rj.add_argument("--source", default="JsonlDrop")
    rj.add_argument("--poll", action="store_true")
    rj.add_argument("--db", default=None)
    rj.set_defaults(func=cmd_register_jsonl)

    rc = sub.add_parser("register-csv", help="Register a CSV spreadsheet drop connector")
    rc.add_argument("--path", required=True)
    rc.add_argument("--id", default="csv-drop")
    rc.add_argument("--source", default="Spreadsheet")
    rc.add_argument("--poll", action="store_true")
    rc.add_argument("--db", default=None)
    rc.set_defaults(func=cmd_register_csv)

    me = sub.add_parser("mock-emit", help="Enqueue a mock CDC event")
    me.add_argument("--payload", required=True)
    me.add_argument("--connector", default="mock-cdc")
    me.add_argument("--acl", default="domain:sre,clearance:l2")
    me.add_argument("--poll", action="store_true")
    me.add_argument("--db", default=None)
    me.set_defaults(func=cmd_mock_emit)

    ib = sub.add_parser("inbox", help="Poll .data/inbox JSONL file-drop (dual-path extract)")
    ib.add_argument("--path", default=None, help="Default: .data/inbox/events.jsonl")
    ib.add_argument("--id", default="inbox-jsonl")
    ib.add_argument("--source", default="FileDrop")
    ib.add_argument("--db", default=None)
    ib.set_defaults(func=cmd_inbox)

    gs = sub.add_parser("graphiti-search", help="Search live Graphiti/Neo4j graph")
    gs.add_argument("query")
    gs.add_argument("--limit", type=int, default=8)
    gs.set_defaults(func=cmd_graphiti_search)

    ps = sub.add_parser("poc-status", help="POC readiness (no secrets printed)")
    ps.set_defaults(func=cmd_poc_status)

    eng = sub.add_parser("engines", help="Show blueprint engine mapping status")
    eng.add_argument("--db", default=None)
    eng.add_argument("--rebuild", action="store_true", help="Rebuild communities + doc trees")
    eng.set_defaults(func=cmd_engines)

    th = sub.add_parser("themes", help="GraphRAG global/thematic query (package + store communities)")
    th.add_argument("question")
    th.add_argument("--db", default=None)
    th.set_defaults(func=cmd_themes)

    dr = sub.add_parser("doc-route", help="PageIndex structure navigation (package + local tree)")
    dr.add_argument("query")
    dr.add_argument("--file", default=None)
    dr.add_argument("--text", default=None)
    dr.add_argument("--top-k", type=int, default=3)
    dr.add_argument("--db", default=None)
    dr.set_defaults(func=cmd_doc_route)

    rp = sub.add_parser("reprocess", help="Re-run extractors over landed episodes (H6)")
    rp.add_argument("--db", default=None)
    rp.add_argument("--domain", default=None)
    rp.add_argument("--limit", type=int, default=None)
    rp.set_defaults(func=cmd_reprocess)

    mat = sub.add_parser("materialize", help="Emit BI views JSON/CSV (H16)")
    mat.add_argument("--out", default=".data/materialized")
    mat.add_argument("--view", default="entity_facts", choices=["entity_facts", "conflicts"])
    mat.add_argument("--db", default=None)
    mat.set_defaults(func=cmd_materialize)

    df = sub.add_parser("drift", help="Schema drift scan (H5)")
    df.add_argument("--db", default=None)
    df.add_argument("--rescan", action="store_true", help="Second pass for delta events")
    df.set_defaults(func=cmd_drift)

    ap = sub.add_parser("action-propose", help="Propose write-back action (H15)")
    ap.add_argument("--type", default="create_ticket")
    ap.add_argument("--payload", required=True, help="JSON object or text")
    ap.add_argument("--by", default="cli:user")
    ap.add_argument("--risk", default="high", choices=["low", "medium", "high"])
    ap.add_argument("--db", default=None)
    ap.set_defaults(func=cmd_action_propose)

    ad = sub.add_parser("action-decide", help="Approve/reject (+ optional sim execute)")
    ad.add_argument("action_id")
    ad.add_argument("--by", required=True)
    ad.add_argument("--reason", required=True)
    ad.add_argument("--approve", action="store_true")
    ad.add_argument("--reject", action="store_true")
    ad.add_argument("--execute", action="store_true")
    ad.add_argument("--db", default=None)
    ad.set_defaults(func=cmd_action_decide)

    al = sub.add_parser("actions", help="List action bus proposals")
    al.add_argument("--status", default=None)
    al.add_argument("--db", default=None)
    al.set_defaults(func=cmd_actions)

    cap = sub.add_parser("capability", help="Capability matrix / doability scoreboard")
    cap.set_defaults(func=cmd_capability)

    cost = sub.add_parser("cost", help="Cost/latency envelopes")
    cost.add_argument("--budget", default=None, choices=["interactive", "standard", "deep"])
    cost.add_argument("--qps", type=float, default=1.0)
    cost.set_defaults(func=cmd_cost)

    wh = sub.add_parser("webhook", help="Enqueue webhook inbox event")
    wh.add_argument("--payload", required=True)
    wh.add_argument("--source", default="Webhook")
    wh.add_argument("--acl", default="domain:sre,clearance:l2")
    wh.add_argument("--poll", action="store_true")
    wh.add_argument("--db", default=None)
    wh.set_defaults(func=cmd_webhook)

    srv = sub.add_parser("serve", help="Start local HTTP API + UI")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8787)
    srv.add_argument("--db", default=None)
    srv.set_defaults(func=cmd_serve)

    return p


def main(argv: Optional[list[str]] = None) -> None:
    try:
        from synapse.env_load import load_dotenv

        load_dotenv()
    except Exception:
        pass
    # Backward compatible: bare `python -m synapse` with no args → simulate
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["simulate"]
    # Legacy flags without subcommand
    if argv and argv[0].startswith("-"):
        argv = ["simulate"] + argv

    parser = build_parser()
    args = parser.parse_args(argv)
    code = args.func(args)
    raise SystemExit(code or 0)
