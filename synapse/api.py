"""
Minimal local HTTP API (stdlib only) + static UI.

Endpoints:
  GET  /  and /ui          → web console
  GET  /health
  GET  /v1/stats
  POST /v1/seed            {scenario?: checkout|billing}
  POST /v1/ingest
  POST /v1/query
  GET  /v1/conflicts
  POST /v1/conflicts/{id}/pin
  GET  /v1/entities
  POST /v1/entities/merge
  GET  /v1/er/suggestions
  GET  /v1/audit
  POST /v1/eval
  GET  /v1/raw            → Sense board RAW panel
  GET  /v1/episodes       → Sense board RAW panel (prepped units)
  GET  /v1/facts          → Sense board MEANING panel
  GET  /v1/sense/summary  → Sense board status strip
  POST /v1/sense/drop     → land CSV/JSONL path or pasted JSON (C1)
"""

from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from synapse.entity_resolution import EntityResolutionService
from synapse.scenarios.billing_customer import BillingCustomerScenario
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.security import (
    Principal,
    filter_conflicts,
    filter_entities,
    filter_episodes,
    filter_facts,
    filter_raw_objects,
    principal_may_access,
)
from synapse.session import SynapseSession, open_session
from synapse.store import SemanticStore

_PIN_RE = re.compile(r"^/v1/conflicts/([^/]+)/pin$")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _json_response(handler: BaseHTTPRequestHandler, code: int, body: Any) -> None:
    data = json.dumps(body, indent=2).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _bytes_response(
    handler: BaseHTTPRequestHandler,
    code: int,
    data: bytes,
    content_type: str,
) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


_FALLBACK_DEMO_DOMAINS = ["domain:sre", "domain:revenue", "domain:identity"]


def _resolve_principal(
    principal: Any, store: Optional[SemanticStore] = None
) -> Principal:
    """
    Shared principal resolution for both GET (query string) and POST (JSON
    body) routes -- kept as one function so the two paths can't drift.

    l1/l2 are demo/UI convenience presets, not real per-user ACL profiles --
    they've always meant "broad viewer access to everything currently known
    to this store", now including `role:operator` so the existing Sense
    board UI's mutation calls (merge, pin, reprocess, materialize, connector
    poll, sense drop, ...) keep working exactly as before under Active_File.md
    row 30's ABAC gate -- neither preset grants `role:admin` (export/audit),
    which is a genuine, deliberate tightening from before that row.

    When `store` is provided, the domain tags are derived from what's
    actually landed (`store.known_acl_domains()`) instead of a hardcoded
    list, so a new pack's data (e.g. domain:banking) is visible to the
    default UI viewer the moment it lands, not just the three original
    scenario domains (Active_File.md row 12, Codex review). Falls back to
    the original static list when no store is available (e.g. unit tests
    constructing a Principal directly).
    """
    domains = sorted(store.known_acl_domains()) if store is not None else []
    if not domains:
        domains = list(_FALLBACK_DEMO_DOMAINS)

    if principal == "l1":
        return Principal.from_tags("user-l1", domains + ["clearance:l1", "role:operator"])
    if principal == "l2":
        return Principal.from_tags(
            "user-l2",
            domains
            + [
                "clearance:l2",
                "channel:incidents",
                "channel:support",
                "channel:itsm",
                "role:operator",
            ],
        )
    if isinstance(principal, dict):
        return Principal.from_tags(
            principal.get("id", "api-user"),
            principal.get("attributes", ["domain:sre", "clearance:l2"]),
        )
    if isinstance(principal, str) and "," in principal:
        return Principal.from_tags("api-user", [t.strip() for t in principal.split(",")])
    return Principal.from_tags(
        "user-l2",
        domains
        + [
            "clearance:l2",
            "channel:incidents",
            "channel:support",
            "channel:itsm",
            "role:operator",
        ],
    )


def _principal_from_body(
    body: dict[str, Any], store: Optional[SemanticStore] = None
) -> Principal:
    return _resolve_principal(body.get("principal", "l2"), store)


def _principal_from_query(
    qs: dict[str, list[str]], store: Optional[SemanticStore] = None
) -> Principal:
    """GET-route counterpart to `_principal_from_body` -- reads `?principal=`
    from the parsed query string instead of a JSON body (Active_File.md
    row 30: GET routes previously resolved no principal at all)."""
    raw = qs.get("principal", ["l2"])[0]
    return _resolve_principal(raw, store)


def _filtered_timeline(
    session: SynapseSession,
    entity_id: str,
    principal: Principal,
    predicate: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    ACL-filtered counterpart to `TemporalService.timeline()` for the API
    layer (Active_File.md row 30) -- deliberately not touching
    `timeline()`'s own signature, since it's a lower-level, separately
    tested service used by callers that don't have a principal. Same dict
    shape and ordering as `timeline()`, just built from
    `filter_facts()`-scoped facts.
    """
    facts = session.store.facts_for_entity(entity_id, predicate)
    visible = filter_facts(principal, facts)
    from synapse.control_plane import parse_iso_z

    visible.sort(key=lambda f: parse_iso_z(f.valid_from))
    return [
        {
            "fact_id": f.fact_id,
            "predicate": f.predicate,
            "object": f.object,
            "source_system": f.source_system,
            "valid_from": f.valid_from,
            "valid_to": f.valid_to,
            "confidence": f.confidence,
            "active": f.valid_to is None,
        }
        for f in visible
    ]


def _filtered_export(session: SynapseSession, principal: Principal) -> dict[str, Any]:
    """
    ACL-scoped counterpart to `export_store()` (Active_File.md row 36,
    RC-08). `role:admin` (required to reach `/v1/export` at all, see
    `_require_role`) only grants the *capability* to call this route --
    it does not bypass ACL visibility, same separation of concerns as
    everywhere else in this file. Deliberately not touching
    `export_store()`'s own signature: it's shared with other legitimate
    full-access callers (CLI, tests) that don't have a principal to scope
    by, same boundary decision as `_filtered_timeline`.
    """
    store = session.store
    visible_raw = filter_raw_objects(principal, store.raw_objects.values())
    visible_episodes = filter_episodes(principal, store.episodes.values())
    visible_entities = filter_entities(principal, store.entities.values())
    visible_facts = filter_facts(principal, store.facts.values())
    visible_conflicts = filter_conflicts(principal, store.conflicts.values(), store.facts)
    visible_fact_ids = {f.fact_id for f in visible_facts}
    visible_claims = [
        c
        for c in store.claims.values()
        if c.supporting_fact_ids and visible_fact_ids.issuperset(c.supporting_fact_ids)
    ]
    from synapse.models import utc_now_iso

    return {
        "snapshot_version": 1,
        "exported_at": utc_now_iso(),
        "raw_objects": [o.to_dict() for o in visible_raw],
        "episodes": [e.to_dict() for e in visible_episodes],
        "entities": [e.to_dict() for e in visible_entities],
        "facts": [f.to_dict() for f in visible_facts],
        "conflicts": [c.to_dict() for c in visible_conflicts],
        "claims": [c.to_dict() for c in visible_claims],
        "audit": [],
    }


def _require_role(handler: BaseHTTPRequestHandler, principal: Principal, role: str) -> bool:
    """Returns True and writes a 403 if `principal` lacks `role` -- caller
    must `return` immediately when this returns False."""
    if f"role:{role}" in principal.attributes:
        return True
    _json_response(
        handler,
        403,
        {"error": "forbidden", "required_role": role, "principal_id": principal.principal_id},
    )
    return False


def make_handler(session: SynapseSession):
    er = EntityResolutionService(session.store)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            sys_stderr_write = __import__("sys").stderr.write
            sys_stderr_write("%s - %s\n" % (self.address_string(), fmt % args))

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path

            if path in ("/", "/ui", "/index.html"):
                html = (STATIC_DIR / "index.html").read_bytes()
                return _bytes_response(self, 200, html, "text/html; charset=utf-8")

            if path.startswith("/static/"):
                rel = path[len("/static/") :]
                fpath = (STATIC_DIR / rel).resolve()
                if not str(fpath).startswith(str(STATIC_DIR.resolve())) or not fpath.is_file():
                    return _json_response(self, 404, {"error": "not_found"})
                ctype = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
                return _bytes_response(self, 200, fpath.read_bytes(), ctype)

            if path == "/health":
                from synapse.graph_memory import graphiti_available
                from synapse.llm_gemini import gemini_configured
                from synapse import __version__
                import os

                return _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "service": "synapse",
                        "version": __version__,
                        "graphiti": graphiti_available(),
                        "llm": {
                            "gemini_configured": gemini_configured(),
                            "backend": os.environ.get("SYNAPSE_LLM_BACKEND", "auto"),
                            "model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite"),
                        },
                    },
                )
            if path == "/v1/stats":
                s = session.store
                return _json_response(
                    self,
                    200,
                    {
                        "raw_objects": len(s.raw_objects),
                        "episodes": len(s.episodes),
                        "entities": len(s.entities),
                        "facts": len(s.facts),
                        "conflicts": len(s.conflicts),
                        "claims": len(s.claims),
                        "audit_events": len(s.audit.events),
                        "db_path": session.db_path,
                    },
                )
            if path == "/v1/raw":
                qs = parse_qs(urlparse(self.path).query)
                limit = int(qs.get("limit", ["50"])[0])
                principal = _principal_from_query(qs, session.store)
                visible = filter_raw_objects(principal, session.store.raw_objects.values())
                rows = sorted(visible, key=lambda r: r.ingested_at, reverse=True)[:limit]
                items = [
                    {
                        "object_id": r.object_id,
                        "source": r.source_system,
                        "received_at": r.ingested_at,
                        "preview": r.raw_payload[:200],
                        "content_type": r.media_type,
                    }
                    for r in rows
                ]
                return _json_response(
                    self,
                    200,
                    {"items": items, "count": len(visible)},
                )
            if path == "/v1/episodes":
                qs = parse_qs(urlparse(self.path).query)
                limit = int(qs.get("limit", ["50"])[0])
                principal = _principal_from_query(qs, session.store)
                visible = filter_episodes(principal, session.store.episodes.values())
                rows = sorted(visible, key=lambda e: e.time_span_start or "", reverse=True)[:limit]
                items = []
                for e in rows:
                    sources = sorted(
                        {
                            session.store.raw_objects[rid].source_system
                            for rid in e.raw_object_ids
                            if rid in session.store.raw_objects
                        }
                    )
                    items.append(
                        {
                            "episode_id": e.episode_id,
                            "source": ", ".join(sources) or None,
                            "t_start": e.time_span_start,
                            "preview": e.payload_text[:200],
                        }
                    )
                return _json_response(
                    self,
                    200,
                    {"items": items, "count": len(visible)},
                )
            if path == "/v1/facts":
                qs = parse_qs(urlparse(self.path).query)
                limit = int(qs.get("limit", ["100"])[0])
                entity_id = qs.get("entity_id", [None])[0]
                principal = _principal_from_query(qs, session.store)
                rows = filter_facts(principal, session.store.facts.values())
                if entity_id:
                    rows = [f for f in rows if f.subject_entity_id == entity_id]
                rows.sort(key=lambda f: f.valid_from, reverse=True)
                total = len(rows)
                rows = rows[:limit]

                def _path_badge(extractor_version: str) -> str:
                    if extractor_version.startswith("rule-extractor"):
                        return "rules"
                    if "residual" in extractor_version:
                        return "residual"
                    return "other"

                items = [
                    {
                        "fact_id": f.fact_id,
                        "entity_id": f.subject_entity_id,
                        "predicate": f.predicate,
                        "value": f.object,
                        "source": f.source_system,
                        "confidence": f.confidence,
                        "path": _path_badge(f.extractor_version),
                    }
                    for f in rows
                ]
                return _json_response(self, 200, {"items": items, "count": total})
            if path == "/v1/sense/summary":
                s = session.store
                open_conflicts = sum(
                    1 for c in s.conflicts.values() if c.status.value == "open"
                )
                return _json_response(
                    self,
                    200,
                    {
                        "raw_objects": len(s.raw_objects),
                        "episodes": len(s.episodes),
                        "entities": len(s.entities),
                        "facts": len(s.facts),
                        "conflicts_open": open_conflicts,
                        "conflicts_total": len(s.conflicts),
                    },
                )
            if path == "/v1/metrics":
                from synapse.metrics import METRICS

                return _json_response(self, 200, METRICS.snapshot())
            if path == "/v1/connectors":
                return _json_response(self, 200, session.connectors.list())
            if path == "/v1/poc-status":
                from synapse.env_load import load_dotenv
                from synapse.capability_matrix import capability_matrix
                from synapse.graphiti_ops import GraphitiOps
                from synapse.llm_gemini import create_residual_extractor, gemini_configured

                load_dotenv()
                return _json_response(
                    self,
                    200,
                    {
                        "version": "0.14.0",
                        "gemini_configured": gemini_configured(),
                        "path_b_backend": create_residual_extractor().name,
                        "graphiti": GraphitiOps().status(),
                        "engines": session.engines.describe(),
                        "capability_matrix": capability_matrix(),
                        "cache": session.claim_cache.stats(),
                    },
                )
            if path == "/v1/engines":
                return _json_response(self, 200, session.engines.describe())
            if path == "/v1/ontology":
                return _json_response(self, 200, session.ontology.describe())
            if path == "/v1/capability":
                from synapse.capability_matrix import capability_matrix

                return _json_response(self, 200, capability_matrix())
            if path == "/v1/cost":
                from synapse.cost_model import describe_cost_model

                return _json_response(self, 200, describe_cost_model())
            if path == "/v1/drift":
                session.drift.observe_all()
                return _json_response(self, 200, session.drift.describe())
            if path == "/v1/actions":
                return _json_response(self, 200, session.actions.list())
            if path == "/v1/cache":
                return _json_response(self, 200, session.claim_cache.stats())
            if path == "/v1/conflicts":
                qs = parse_qs(urlparse(self.path).query)
                open_only = qs.get("open_only", ["false"])[0].lower() == "true"
                principal = _principal_from_query(qs, session.store)
                for ent in session.store.entities.values():
                    if ent.status.value == "active":
                        session.resolver.detect_scalar_conflicts(ent.entity_id)
                candidates = [
                    c
                    for c in session.store.conflicts.values()
                    if not open_only or c.status.value == "open"
                ]
                visible = filter_conflicts(principal, candidates, session.store.facts)
                rows = [c.to_dict() for c in visible]
                return _json_response(self, 200, rows)
            if path == "/v1/entities":
                qs = parse_qs(urlparse(self.path).query)
                principal = _principal_from_query(qs, session.store)
                visible = filter_entities(principal, session.store.entities.values())
                rows = [e.to_dict() for e in visible]
                return _json_response(self, 200, rows)
            if path.startswith("/v1/history/"):
                name = path[len("/v1/history/") :].strip("/")
                from urllib.parse import unquote

                name = unquote(name)
                ent = session.store.get_entity_by_name(name)
                if not ent:
                    return _json_response(self, 404, {"error": "entity not found"})
                qs = parse_qs(urlparse(self.path).query)
                principal = _principal_from_query(qs, session.store)
                if not principal_may_access(principal, set(ent.acl_tags)):
                    return _json_response(self, 404, {"error": "entity not found"})
                pred = (qs.get("predicate") or [None])[0]
                rows = _filtered_timeline(session, ent.entity_id, principal, pred or None)
                return _json_response(
                    self,
                    200,
                    {
                        "entity": ent.canonical_name,
                        "entity_id": ent.entity_id,
                        "timeline": rows,
                    },
                )
            if path == "/v1/er/suggestions":
                return _json_response(self, 200, er.suggest_merges())
            if path == "/v1/graph":
                snap = session.sync_graph()
                qs = parse_qs(urlparse(self.path).query)
                entity = qs.get("entity", [None])[0]
                depth = int(qs.get("depth", ["1"])[0])
                if entity:
                    ent = session.store.get_entity_by_name(entity)
                    eid = ent.entity_id if ent else entity
                    return _json_response(
                        self, 200, session.graph.neighborhood(eid, depth=depth)
                    )
                return _json_response(
                    self,
                    200,
                    {
                        "stats": session.graph.stats(),
                        "built_at": snap.built_at,
                        "backend": snap.backend,
                    },
                )
            if path == "/v1/export":
                qs = parse_qs(urlparse(self.path).query)
                principal = _principal_from_query(qs, session.store)
                if not _require_role(self, principal, "admin"):
                    return None
                return _json_response(self, 200, _filtered_export(session, principal))
            if path == "/v1/audit":
                qs = parse_qs(urlparse(self.path).query)
                principal = _principal_from_query(qs, session.store)
                if not _require_role(self, principal, "admin"):
                    return None
                limit = int(qs.get("limit", ["50"])[0])
                etype = qs.get("type", [None])[0]
                events = session.store.audit.to_list()
                if etype:
                    events = [e for e in events if e["event_type"] == etype]
                return _json_response(self, 200, events[-limit:])
            return _json_response(self, 404, {"error": "not_found", "path": path})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            try:
                body = _read_json(self)
            except json.JSONDecodeError:
                return _json_response(self, 400, {"error": "invalid_json"})

            if path == "/v1/seed":
                scenario_name = (body.get("scenario") or "checkout").lower()
                skip = bool(body.get("skip_if_populated", True))
                extra: dict = {}
                try:
                    if scenario_name in ("billing", "revenue", "crm"):
                        BillingCustomerScenario(store=session.store).seed(
                            skip_if_populated=skip
                        )
                    elif scenario_name in ("identity", "access", "iam"):
                        from synapse.scenarios.identity_access import (
                            IdentityAccessScenario,
                        )

                        IdentityAccessScenario(store=session.store).seed(
                            skip_if_populated=skip
                        )
                    elif scenario_name in ("org", "multi", "discrepancy", "all"):
                        from synapse.scenarios.org_discrepancy import (
                            OrgDiscrepancyCorpus,
                        )

                        corpus = OrgDiscrepancyCorpus(store=session.store).seed(
                            skip_if_populated=skip
                        )
                        extra = {
                            "domains": corpus.domains,
                            "entity_names": corpus.entity_names,
                            "extra_ingested": corpus.extra_ingested,
                        }
                    else:
                        CheckoutIncidentScenario(store=session.store).seed(
                            skip_if_populated=skip
                        )
                    # Keep seed fast for UI — local graph only; never block on live Graphiti/LLM
                    graph_meta: dict = {"graph": {}, "graph_built_at": None}
                    try:
                        from synapse.graph_memory import LocalGraphitiStub

                        local = LocalGraphitiStub()
                        snap = local.sync_from_store(session.store)
                        graph_meta = {
                            "graph": {
                                "backend": snap.backend,
                                "nodes": len(snap.nodes),
                                "edges": len(snap.edges),
                            },
                            "graph_built_at": snap.built_at,
                        }
                    except Exception:
                        pass
                    try:
                        session.engines.rebuild_communities()
                        session.engines.index_episode_docs()
                    except Exception:
                        pass
                    return _json_response(
                        self,
                        200,
                        {
                            "ok": True,
                            "scenario": scenario_name,
                            "raw_objects": len(session.store.raw_objects),
                            "entities": len(session.store.entities),
                            "facts": len(session.store.facts),
                            "conflicts": len(session.store.conflicts),
                            **graph_meta,
                            **extra,
                        },
                    )
                except Exception as e:
                    return _json_response(
                        self,
                        500,
                        {
                            "error": "seed_failed",
                            "message": str(e)[:400],
                            "hint": (
                                "If using SQLite under multi-thread serve, upgrade "
                                "sqlite_store thread safety or restart server."
                            ),
                        },
                    )

            if path == "/v1/ingest":
                source = body.get("source_system") or body.get("source")
                payload = body.get("payload")
                acl = body.get("acl_tags") or ["domain:sre", "clearance:l2"]
                if not source or payload is None:
                    return _json_response(
                        self, 400, {"error": "source_system and payload required"}
                    )
                result = session.ingestion.land(
                    source,
                    payload,
                    list(acl),
                    actor=body.get("actor", "api:ingest"),
                )
                extracted = session.extractor.extract_from_episode(
                    result.episode, result.raw
                )
                return _json_response(
                    self,
                    200,
                    {
                        "deduplicated": result.deduplicated,
                        "object_id": result.raw.object_id,
                        "episode_id": result.episode.episode_id,
                        "entity": extracted.entity.canonical_name if extracted else None,
                        "facts_added": len(extracted.facts) if extracted else 0,
                    },
                )

            if path == "/v1/query":
                entity = body.get("entity") or body.get("entity_name")
                if not entity:
                    return _json_response(self, 400, {"error": "entity required"})
                result = session.query.ask(
                    _principal_from_body(body, session.store),
                    entity_name=entity,
                    intent=body.get("intent", "entity_lookup"),
                    as_of=body.get("as_of"),
                )
                return _json_response(
                    self, 200 if result.allowed else 403, result.to_dict()
                )

            if path == "/v1/history":
                entity = body.get("entity") or body.get("entity_name")
                if not entity:
                    return _json_response(self, 400, {"error": "entity required"})
                ent = session.store.get_entity_by_name(entity)
                if not ent:
                    return _json_response(self, 404, {"error": "entity not found"})
                principal = _principal_from_body(body, session.store)
                if not principal_may_access(principal, set(ent.acl_tags)):
                    return _json_response(self, 404, {"error": "entity not found"})
                rows = _filtered_timeline(session, ent.entity_id, principal, body.get("predicate"))
                return _json_response(
                    self,
                    200,
                    {
                        "entity": ent.canonical_name,
                        "entity_id": ent.entity_id,
                        "timeline": rows,
                    },
                )

            if path == "/v1/ask":
                question = body.get("question") or body.get("query") or ""
                if not question:
                    return _json_response(self, 400, {"error": "question required"})
                ans = session.orchestrator.ask(
                    _principal_from_body(body, session.store),
                    question,
                    intent=body.get("intent"),
                    entity_name=body.get("entity") or body.get("entity_name"),
                    budget_class=body.get("budget_class") or body.get("budget"),
                    as_of=body.get("as_of"),
                )
                return _json_response(
                    self, 200 if ans.allowed else 403, ans.to_dict()
                )

            if path == "/v1/entities/merge":
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                try:
                    merge = er.merge(
                        body["survivor_id"],
                        body["loser_id"],
                        adjudicator=body.get("adjudicator", "api:er"),
                        reason=body.get("reason", "manual merge"),
                    )
                except (KeyError, ValueError) as exc:
                    return _json_response(self, 400, {"error": str(exc)})
                return _json_response(
                    self,
                    200,
                    {
                        "survivor": merge.survivor.to_dict(),
                        "loser": merge.loser.to_dict(),
                        "facts_rewritten": merge.facts_rewritten,
                    },
                )

            m = _PIN_RE.match(path)
            if m:
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                conflict_id = m.group(1)
                try:
                    pin = session.adjudication.human_pin(
                        conflict_id,
                        chosen_fact_id=body["chosen_fact_id"],
                        adjudicator=body.get("adjudicator", "api:user"),
                        reason=body.get("reason", "api pin"),
                    )
                except KeyError:
                    return _json_response(
                        self, 400, {"error": "chosen_fact_id required"}
                    )
                except Exception as exc:
                    return _json_response(self, 400, {"error": str(exc)})
                return _json_response(self, 200, pin.conflict.to_dict())

            if path == "/v1/eval":
                from synapse.eval_runner import evaluate_pack

                pack = (body.get("pack") or "all").lower()
                # Eval uses isolated stores for correctness
                report = evaluate_pack(pack, store=None)
                return _json_response(
                    self, 200 if report.ok else 409, report.to_dict()
                )

            if path == "/v1/connectors/poll":
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                cid = body.get("connector_id")
                if cid:
                    results = [session.connector_runner.poll_one(cid)]
                else:
                    results = session.connector_runner.poll_all()
                session.sync_graph()
                return _json_response(
                    self, 200, {"results": [r.to_dict() for r in results]}
                )

            if path == "/v1/connectors/mock-emit":
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                from synapse.connectors.mock_cdc import MockCdcConnector

                cid = body.get("connector_id") or "mock-cdc"
                try:
                    conn = session.connectors.get(cid)
                except KeyError:
                    return _json_response(self, 404, {"error": "unknown connector"})
                if not isinstance(conn, MockCdcConnector):
                    return _json_response(self, 400, {"error": "not a mock connector"})
                payload = body.get("payload")
                if not payload:
                    return _json_response(self, 400, {"error": "payload required"})
                ev = conn.emit(
                    payload,
                    source_system=body.get("source_system"),
                    acl_tags=body.get("acl_tags"),
                )
                poll = None
                if body.get("poll", True):
                    poll = session.connector_runner.poll_one(cid).to_dict()
                    session.sync_graph()
                return _json_response(
                    self, 200, {"emitted": ev.to_dict(), "poll": poll}
                )

            if path == "/v1/graphiti/search":
                from synapse.graphiti_ops import GraphitiOps

                q = body.get("query") or ""
                if not q:
                    return _json_response(self, 400, {"error": "query required"})
                ops = GraphitiOps()
                try:
                    hits = ops.search(q, num_results=int(body.get("limit") or 8))
                    return _json_response(
                        self, 200, {"hits": [h.to_dict() for h in hits]}
                    )
                except Exception as e:
                    import os

                    msg = str(e)
                    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "NEO4J_PASSWORD"):
                        v = os.environ.get(k)
                        if v:
                            msg = msg.replace(v, "***")
                    return _json_response(self, 500, {"error": msg[:300]})
                finally:
                    ops.close()

            if path == "/v1/inbox/poll":
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                from pathlib import Path

                from synapse.connectors.file_jsonl import JsonlFileConnector

                root = Path(__file__).resolve().parents[1]
                path_f = Path(body.get("path") or root / ".data" / "inbox" / "events.jsonl")
                if not path_f.is_file():
                    return _json_response(
                        self, 404, {"error": f"missing inbox file: {path_f}"}
                    )
                cid = body.get("connector_id") or "inbox-jsonl"
                conn = JsonlFileConnector(
                    path=path_f,
                    connector_id=cid,
                    source_system=body.get("source_system") or "FileDrop",
                )
                session.connectors.register(conn)
                result = session.connector_runner.poll_one(cid)
                session.sync_graph()
                session.engines.rebuild_communities()
                return _json_response(self, 200, result.to_dict())

            if path == "/v1/themes":
                q = body.get("question") or body.get("query") or ""
                if not q:
                    return _json_response(self, 400, {"error": "question required"})
                session.engines.rebuild_communities()
                hits = session.engines.route_query(q, intent="themes")
                return _json_response(self, 200, hits)

            if path == "/v1/doc-route":
                q = body.get("query") or ""
                text = body.get("text")
                if not q:
                    return _json_response(self, 400, {"error": "query required"})
                if text:
                    tree = session.engines.index_document(
                        text, title=body.get("title") or "api-doc"
                    )
                    routed = session.engines.pageindex.route(
                        tree, q, top_k=int(body.get("top_k") or 3)
                    )
                    return _json_response(
                        self, 200, {"doc_id": tree.doc_id, "route": routed}
                    )
                session.engines.index_episode_docs()
                return _json_response(
                    self, 200, session.engines.route_query(q, intent="document")
                )

            if path == "/v1/reprocess":
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                report = session.reprocess.run(
                    domain=body.get("domain"),
                    limit=body.get("limit"),
                    actor=body.get("actor") or "api:reprocess",
                )
                session.claim_cache.invalidate_all()
                return _json_response(self, 200, report.to_dict())

            if path == "/v1/materialize":
                mat_principal = _principal_from_body(body, session.store)
                if not _require_role(self, mat_principal, "operator"):
                    return None
                view_name = (body.get("view") or "entity_facts").lower()
                view = (
                    session.materializer.conflict_table(principal=mat_principal)
                    if view_name == "conflicts"
                    else session.materializer.entity_fact_table(principal=mat_principal)
                )
                out_dir = body.get("out") or ".data/materialized"
                paths = session.materializer.write(view, out_dir)
                return _json_response(
                    self, 200, {"view": view.to_dict(), "paths": paths}
                )

            if path == "/v1/actions/propose":
                a = session.actions.propose(
                    body.get("type") or "create_ticket",
                    body.get("payload") or {},
                    proposed_by=body.get("by") or "api:user",
                    risk=body.get("risk") or "high",
                )
                return _json_response(self, 200, a.to_dict())

            if path == "/v1/actions/decide":
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                aid = body.get("action_id")
                if not aid:
                    return _json_response(self, 400, {"error": "action_id required"})
                by = body.get("by") or "api:user"
                reason = body.get("reason") or "api decide"
                try:
                    if body.get("approve"):
                        a = session.actions.approve(aid, by=by, reason=reason)
                    elif body.get("reject"):
                        a = session.actions.reject(aid, by=by, reason=reason)
                    else:
                        return _json_response(
                            self, 400, {"error": "approve or reject required"}
                        )
                    if body.get("execute") and a.status.value == "approved":
                        a = session.actions.execute(aid, by=by)
                    return _json_response(self, 200, a.to_dict())
                except (KeyError, ValueError) as e:
                    return _json_response(self, 400, {"error": str(e)})

            if path == "/v1/sense/drop":
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                kind = (body.get("kind") or "json").lower()
                acl = body.get("acl_tags") or ["domain:sre", "clearance:l2"]

                if kind == "json":
                    payload = body.get("payload")
                    source = body.get("source_system") or "SenseBoard-Paste"
                    if payload is None:
                        return _json_response(
                            self, 400, {"error": "payload required for kind=json"}
                        )
                    if not isinstance(payload, str):
                        payload = json.dumps(payload)
                    result = session.ingestion.land(
                        source, payload, list(acl), actor="api:sense-drop"
                    )
                    extracted = None
                    residual_n = 0
                    if not result.dropped:
                        out = session.dual_path.extract(result.episode, result.raw)
                        extracted = out.entity_name
                        residual_n = len(out.residual_facts)
                    session.sync_graph()
                    return _json_response(
                        self,
                        200,
                        {
                            "kind": "json",
                            "object_id": result.raw.object_id,
                            "episode_id": result.episode.episode_id,
                            "deduplicated": result.deduplicated,
                            "entity": extracted,
                            "residual_facts": residual_n,
                        },
                    )

                if kind in ("csv", "jsonl"):
                    file_path = body.get("path")
                    if not file_path:
                        return _json_response(
                            self, 400, {"error": "path required for kind=csv|jsonl"}
                        )
                    from pathlib import Path as _Path

                    if not _Path(file_path).is_file():
                        return _json_response(
                            self, 404, {"error": f"file not found: {file_path}"}
                        )
                    cid = body.get("connector_id") or f"sense-drop-{kind}"
                    source = body.get("source_system") or (
                        "Spreadsheet" if kind == "csv" else "FileDrop"
                    )
                    try:
                        existing = session.connectors.get(cid)
                    except KeyError:
                        existing = None
                    if existing is None:
                        if kind == "csv":
                            from synapse.connectors.csv_drop import CsvDropConnector

                            conn = CsvDropConnector(
                                path=file_path, connector_id=cid, source_system=source
                            )
                        else:
                            from synapse.connectors.file_jsonl import (
                                JsonlFileConnector,
                            )

                            conn = JsonlFileConnector(
                                path=file_path, connector_id=cid, source_system=source
                            )
                        session.connectors.register(conn)
                    result = session.connector_runner.poll_one(cid)
                    session.sync_graph()
                    return _json_response(
                        self,
                        200,
                        {"kind": kind, "connector_id": cid, "poll": result.to_dict()},
                    )

                return _json_response(self, 400, {"error": f"unknown kind: {kind}"})

            if path == "/v1/webhook":
                if not _require_role(self, _principal_from_body(body, session.store), "operator"):
                    return None
                from synapse.connectors.webhook_inbox import WebhookInboxConnector

                try:
                    conn = session.connectors.get("webhook-inbox")
                except KeyError:
                    conn = WebhookInboxConnector()
                    session.connectors.register(conn)
                if not isinstance(conn, WebhookInboxConnector):
                    return _json_response(self, 500, {"error": "webhook type mismatch"})
                payload = body.get("payload")
                if payload is None:
                    return _json_response(self, 400, {"error": "payload required"})
                row = conn.enqueue(
                    payload if isinstance(payload, str) else json.dumps(payload),
                    source_system=body.get("source_system") or "Webhook",
                    acl_tags=body.get("acl_tags") or ["domain:sre", "clearance:l2"],
                )
                out = {"enqueued": row}
                if body.get("poll"):
                    out["poll"] = session.connector_runner.poll_one(
                        "webhook-inbox"
                    ).to_dict()
                return _json_response(self, 200, out)

            return _json_response(self, 404, {"error": "not_found", "path": path})

    return Handler


def serve(
    host: str = "127.0.0.1",
    port: int = 8787,
    db_path: Optional[str] = None,
) -> None:
    try:
        from synapse.env_load import load_dotenv

        load_dotenv()
    except Exception:
        pass
    session = open_session(db_path)
    handler = make_handler(session)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"Synapse API + UI  http://{host}:{port}/")
    print(f"  db={db_path or 'memory'}")
    print("  UI  /   API  /health /v1/*")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        httpd.server_close()
        session.close()
