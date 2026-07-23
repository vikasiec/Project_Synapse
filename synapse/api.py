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
  GET  /v1/explore        → query-free discovery view: entity types/counts/
                            samples, sources + observed fields, fields
                            shared across sources, predicate vocabulary,
                            open-issue counts (no entity name required)
  GET  /v1/audit
  POST /v1/eval
  GET  /v1/raw            → Sense board RAW panel
  GET  /v1/episodes       → Sense board RAW panel (prepped units)
  GET  /v1/facts          → Sense board MEANING panel
  GET  /v1/sense/summary  → Sense board status strip (incl. dynamic_story
                            reflecting whatever's actually loaded, so
                            Step 1 doesn't always show the canned demos)
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

from synapse.drift import _KEY_RE
from synapse.entity_resolution import normalize_name
from synapse.models import Entity
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
# New Vite/React UI (Catalog/Explore full-canvas journey, row 43). Served
# alongside the legacy static/index.html at "/" until it reaches panel
# parity (RAW/MEANING/CONFLICTS/ASK/EMIT) -- see Active_File.md row 43.
UI_DIST_DIR = Path(__file__).resolve().parent.parent / "ui" / "dist"

# Human labels for the domain ACL tags actually in use across this proof's
# scenarios/connectors. A domain with no entry here still gets a readable
# fallback ("{tag} data") rather than disappearing from the dynamic story.
_DOMAIN_LABELS: dict[str, str] = {
    "domain:sre": "Incident / infra data",
    "domain:revenue": "Billing / revenue data",
    "domain:identity": "Identity / access data",
    "domain:support": "Support ticket data",
    "domain:clinical": "Clinical / lab data",
    "domain:banking": "Banking data",
}


def _dynamic_story(store: SemanticStore) -> Optional[dict[str, Any]]:
    """
    "What's actually loaded" summary for the Sense board's Step 1 card, so
    it reflects real ingested data instead of always showing the three
    original canned demo scenarios regardless of what's in the store
    (the gap a user flagged: after loading real clinical data, Step 1
    still advertised "Checkout outage" / "Billing revenue conflict").

    Returns None when the store has no raw objects at all -- the canned
    cards remain the correct fallback for that first-time-visitor
    bootstrap case, not something this function should paper over.

    Scoped to whichever domain has the most landed raw objects, so a
    store that's mostly one domain (the common case -- one demo run, one
    real ingest) gets one coherent story rather than an average of
    everything landed so far.
    """
    if not store.raw_objects:
        return None

    counts: dict[str, int] = {}
    sources_by_domain: dict[str, set[str]] = {}
    for raw in store.raw_objects.values():
        domains = [t for t in raw.acl_tags if t.startswith("domain:")] or ["domain:unknown"]
        for d in domains:
            counts[d] = counts.get(d, 0) + 1
            sources_by_domain.setdefault(d, set()).add(raw.source_system)

    primary_domain = max(counts, key=counts.get)
    sources = sorted(sources_by_domain[primary_domain])

    entity_count = sum(
        1 for e in store.entities.values() if primary_domain in e.acl_tags
    )
    conflict_count = sum(
        1
        for c in store.conflicts.values()
        if c.status.value == "open"
        and primary_domain in getattr(store.entities.get(c.subject_entity_id), "acl_tags", [])
    )

    label = _DOMAIN_LABELS.get(primary_domain, f"{primary_domain.split(':', 1)[-1]} data")
    source_note = (
        f"{len(sources)} sources converging: {', '.join(sources[:4])}"
        if len(sources) > 1
        else f"1 source: {sources[0]}"
    )
    conflict_note = (
        f" · {conflict_count} open conflict{'s' if conflict_count != 1 else ''}"
        if conflict_count
        else ""
    )

    return {
        "domain": primary_domain,
        "title": f"{label} loaded",
        "subtitle": f"{entity_count} entities · {source_note}{conflict_note}",
        "entity_count": entity_count,
        "source_count": len(sources),
        "sources": sources,
        "conflict_count": conflict_count,
    }


_EXPLORE_SAMPLE_LIMIT = 8


def _explore_summary(
    session: SynapseSession, principal: Principal, workspace_id: Optional[str] = None
) -> dict[str, Any]:
    """
    Query-free "what's actually in here" view (H-explore): entity types +
    counts + a few sample names, sources with their observed field
    vocabulary, which fields are shared across sources, and open-issue
    counts -- everything a user needs to go from "I don't know what to
    ask" to "now I know a name," without ever requiring one up front.

    Deliberately pure aggregation over already-computed store/detector
    state -- no LLM narration. An LLM asked to "describe this dataset"
    has no bounded predicate vocabulary to constrain it against, which is
    exactly the shape of prompt that produced this session's fabricated
    residual-path facts; Explore stays counts/lists/links only.

    ACL-scoped the same way every other read route is: filter_entities/
    filter_facts/filter_raw_objects against the resolved principal, so a
    principal missing a domain tag doesn't learn that domain's types,
    sources, or fields exist at all.
    """
    store = session.store

    visible_entities = [
        e
        for e in filter_entities(principal, store.entities.values())
        if e.status.value == "active"
    ]
    by_type: dict[str, list[Entity]] = {}
    for ent in visible_entities:
        by_type.setdefault(ent.entity_type, []).append(ent)
    entity_types = [
        {
            "type": etype,
            "count": len(ents),
            "samples": [
                e.canonical_name
                for e in ents[:_EXPLORE_SAMPLE_LIMIT]
                if e.canonical_name
            ],
        }
        for etype, ents in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    ]

    visible_raw = filter_raw_objects(principal, store.raw_objects.values())
    if workspace_id:
        visible_raw = [r for r in visible_raw if r.workspace_id == workspace_id]
    domain_by_source: dict[str, str] = {}
    for raw in visible_raw:
        domain = next((t for t in raw.acl_tags if t.startswith("domain:")), "domain:unknown")
        domain_by_source.setdefault(raw.source_system, domain)

    # An HL7/FHIR source decomposes into virtual sub-sources (one per
    # segment/resourceType -- synapse/hl7_semantics.py, profiling.py's
    # list_virtual_sources) so Explore/Schema View show e.g. "MSH"/"PID"/
    # "OBR"/"OBX" as separate, correctly-typed cards instead of one flat
    # blob with positional field codes. Every other source (CSV, plain
    # JSON, KV-text) is unaffected -- list_virtual_sources returns [] for
    # anything that isn't decomposable, so it's listed by its real name.
    from synapse.profiling import list_virtual_sources

    raws_by_base: dict[str, list] = {}
    for raw in visible_raw:
        raws_by_base.setdefault(raw.source_system, []).append(raw)
    source_names: list[str] = []
    virtual_domain: dict[str, str] = {}
    virtual_count: dict[str, int] = {}
    for base, raws in raws_by_base.items():
        sub_types: set[str] = set()
        for raw in raws:
            sub_types.update(list_virtual_sources(raw.raw_payload))
        if sub_types:
            for sub in sub_types:
                name = f"{base}::{sub}"
                source_names.append(name)
                virtual_domain[name] = domain_by_source[base]
                virtual_count[name] = len(raws)
        else:
            source_names.append(base)
            virtual_domain[base] = domain_by_source[base]
            virtual_count[base] = len(raws)
    source_names.sort()

    # Field vocabulary is computed directly from ACL-visible raw payloads
    # with DriftDetector's own key-extraction regex (_KEY_RE), rather than
    # read from session.drift.baselines. Baselines are store-wide, not
    # principal-scoped -- if a source_system name were ever reused across
    # two different ACL domains, reading the shared baseline would leak
    # the other domain's field names to a principal who can't see that
    # domain's raw objects at all. Recomputing from visible_raw only keeps
    # this endpoint's own ACL promise (see docstring) actually true. This
    # also sidesteps DriftDetector's synthetic "has_*" pattern-trip tags
    # (e.g. "has_revenue") entirely, since those never entered the regex
    # extraction in the first place -- no separate filtering needed.
    field_sets: dict[str, set[str]] = {}
    for raw in visible_raw:
        keys = {m.group(1).strip().lower() for m in _KEY_RE.finditer(raw.raw_payload)}
        field_sets.setdefault(raw.source_system, set()).update(keys)
    sources = [
        {
            "source_system": src,
            "acl_domain": virtual_domain[src],
            "object_count": virtual_count[src],
            "observed_fields": sorted(field_sets.get(src, set())),
        }
        for src in source_names
    ]

    field_to_sources: dict[str, set[str]] = {}
    for src in source_names:
        for f in field_sets.get(src, set()):
            field_to_sources.setdefault(f, set()).add(src)
    shared_fields = [
        {"field": f, "sources": sorted(srcs)}
        for f, srcs in sorted(field_to_sources.items())
        if len(srcs) > 1
    ]

    visible_facts = filter_facts(principal, store.facts.values())
    pred_counts: dict[tuple[str, str], int] = {}
    entity_type_by_id = {e.entity_id: e.entity_type for e in visible_entities}
    for f in visible_facts:
        etype = entity_type_by_id.get(f.subject_entity_id)
        if not etype:
            continue
        key = (etype, f.predicate)
        pred_counts[key] = pred_counts.get(key, 0) + 1
    predicate_vocabulary = [
        {"entity_type": etype, "predicate": pred, "fact_count": count}
        for (etype, pred), count in sorted(
            pred_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )
    ]

    for ent in visible_entities:
        session.resolver.detect_scalar_conflicts(ent.entity_id)
    visible_conflicts = filter_conflicts(
        principal,
        [c for c in store.conflicts.values() if c.status.value == "open"],
        store.facts,
    )

    # Duplicate-name *groups*, not session.er.suggest_merges()'s full
    # pairwise suggestion list. suggest_merges() is unscoped (would leak
    # cross-domain entity existence through a raw count) and combinatorial
    # -- a legitimately recurring name (e.g. the same LOINC-coded LabResult
    # type appearing once per patient, by design) turns into
    # C(n,2) "suggestions" for a single blocking bucket; on New Data's 120
    # patients that alone is thousands of meaningless "duplicates" for one
    # real lab-result type, expensive to compute on every GET besides.
    # Counting distinct (type, normalized-name) buckets with 2+ ACL-visible
    # members answers the only question Explore actually needs ("is
    # anything here worth a second look?") without either problem.
    name_buckets: dict[tuple[str, str], set[str]] = {}
    for ent in visible_entities:
        for name in [ent.canonical_name or ""] + list(ent.aliases):
            if not name:
                continue
            key = (ent.entity_type, normalize_name(name))
            name_buckets.setdefault(key, set()).add(ent.entity_id)
    duplicate_group_count = sum(1 for ids in name_buckets.values() if len(ids) > 1)

    return {
        "entity_types": entity_types,
        "sources": sources,
        "shared_fields_across_sources": shared_fields,
        "predicate_vocabulary": predicate_vocabulary,
        "open_issues": {
            "conflict_count": len(visible_conflicts),
            "duplicate_name_group_count": duplicate_group_count,
        },
    }


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
    # Use the session's own EntityResolutionService rather than a fresh
    # throwaway instance -- a prior version constructed a second, separate
    # er here (without session.ontology either), so state written by one
    # route (e.g. link_schema_fields on ACCEPT) was invisible to anything
    # reading session.er elsewhere (cli.py's merge path). One ER instance
    # per session, consistently.
    er = session.er

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

            if path == "/app" or path.startswith("/app/"):
                if not UI_DIST_DIR.is_dir():
                    return _json_response(
                        self, 404, {"error": "ui_not_built", "hint": "cd ui && npm run build"}
                    )
                rel = path[len("/app/") :] if path.startswith("/app/") else ""
                fpath = (UI_DIST_DIR / rel).resolve() if rel else UI_DIST_DIR / "index.html"
                if not str(fpath).startswith(str(UI_DIST_DIR.resolve())):
                    return _json_response(self, 404, {"error": "not_found"})
                if not fpath.is_file():
                    # SPA client-side routing fallback.
                    fpath = UI_DIST_DIR / "index.html"
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
                        "dynamic_story": _dynamic_story(s),
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
                qs = parse_qs(urlparse(self.path).query)
                workspace_id = qs.get("workspace_id", [None])[0]
                described = session.ontology.describe()
                if workspace_id:
                    store = session.store
                    described["relationships"] = [
                        r
                        for r in described["relationships"]
                        if store.workspace_for_source(r["source_a"]["source_system"]) == workspace_id
                        and store.workspace_for_source(r["source_b"]["source_system"]) == workspace_id
                    ]
                return _json_response(self, 200, described)
            if path == "/v1/workspaces":
                store = session.store
                source_counts: dict[str, set] = {}
                for raw in store.raw_objects.values():
                    source_counts.setdefault(raw.workspace_id, set()).add(raw.source_system)
                rel_counts: dict[str, int] = {}
                for edge in session.ontology.relationships.values():
                    ws_a = store.workspace_for_source(edge.source_a.get("source_system", ""))
                    ws_b = store.workspace_for_source(edge.source_b.get("source_system", ""))
                    if ws_a and ws_a == ws_b:
                        rel_counts[ws_a] = rel_counts.get(ws_a, 0) + 1
                workspaces = [
                    {
                        **ws.to_dict(),
                        "source_count": len(source_counts.get(ws.workspace_id, set())),
                        "relationship_count": rel_counts.get(ws.workspace_id, 0),
                    }
                    for ws in sorted(store.workspaces.values(), key=lambda w: w.created_at)
                ]
                return _json_response(self, 200, {"workspaces": workspaces})
            if path == "/v1/schema/layout":
                qs = parse_qs(urlparse(self.path).query)
                workspace_id = qs.get("workspace_id", [None])[0]
                positions = list(session.store.schema_layout.values())
                if workspace_id:
                    positions = [
                        p
                        for p in positions
                        if session.store.workspace_for_source(p["source_system"]) == workspace_id
                    ]
                return _json_response(self, 200, {"positions": positions})
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
            if path == "/v1/er/merge-candidates":
                # Graph-First Discovery & Entity Resolution (docs/Graph-First
                # Discovery & Entity Resolution.pdf) -- scored, cross-system
                # entity merge candidates, distinct from the unscoped
                # same-block dump at /v1/er/suggestions above.
                from synapse.entity_matching import generate_entity_merge_candidates

                qs = parse_qs(urlparse(self.path).query)
                principal = _principal_from_query(qs, session.store)
                workspace_id = qs.get("workspace_id", [None])[0]
                visible_entities = [
                    e for e in filter_entities(principal, session.store.entities.values())
                    if e.status.value == "active"
                ]
                if workspace_id:
                    store = session.store
                    # Entities carry no workspace of their own (ER predates
                    # workspaces and can legitimately merge identities across
                    # source systems) -- so scope via the facts that built
                    # each entity: an entity "belongs" to a workspace if any
                    # of its facts came from a source system landed there.
                    # Without this, Resolve compared every entity ever
                    # landed across every workspace against every other,
                    # burying real candidates under cross-workspace noise
                    # from unrelated datasets.
                    def _touches_workspace(entity) -> bool:
                        for fact in store.facts_for_entity(entity.entity_id):
                            if store.workspace_for_source(fact.source_system) == workspace_id:
                                return True
                        return False

                    visible_entities = [e for e in visible_entities if _touches_workspace(e)]
                candidates = generate_entity_merge_candidates(session.store, entities=visible_entities)
                return _json_response(self, 200, {"candidates": [c.to_dict() for c in candidates]})
            if path == "/v1/explore":
                qs = parse_qs(urlparse(self.path).query)
                principal = _principal_from_query(qs, session.store)
                workspace_id = qs.get("workspace_id", [None])[0]
                return _json_response(self, 200, _explore_summary(session, principal, workspace_id))
            if path == "/v1/explore/profile":
                # Major Goal 1 read path -- lets the Explore UI show computed
                # field profiles for a picked source before/alongside
                # scoring (spec journey step 2), rather than jumping
                # straight from source-select to the candidate graph.
                from synapse.profiling import SchemaProfiler

                qs = parse_qs(urlparse(self.path).query)
                principal = _principal_from_query(qs, session.store)
                source = qs.get("source", [None])[0]
                if not source:
                    return _json_response(self, 400, {"error": "source query param required"})
                workspace_id = qs.get("workspace_id", [None])[0]
                profiler = SchemaProfiler(session.store)
                profiles = profiler.profile_source(source, principal=principal, workspace_id=workspace_id)
                return _json_response(
                    self,
                    200,
                    {"source": source, "fields": [p.to_dict() for p in profiles.values()]},
                )
            if path == "/v1/explore/samples":
                # Curation-support read path: a bounded, ACL-scoped peek at
                # a field's actual observed values, so a human reviewing a
                # candidate match (node double-click, edge double-click) has
                # something concrete to look at. Deliberately not part of
                # SchemaFieldProfile -- that type never carries raw values
                # at all, this is a separate, on-demand, small (<=20) read.
                from synapse.profiling import SchemaProfiler

                qs = parse_qs(urlparse(self.path).query)
                principal = _principal_from_query(qs, session.store)
                source = qs.get("source", [None])[0]
                field = qs.get("field", [None])[0]
                if not source or not field:
                    return _json_response(self, 400, {"error": "source and field query params required"})
                limit = min(int(qs.get("limit", ["5"])[0]), 20)
                workspace_id = qs.get("workspace_id", [None])[0]
                profiler = SchemaProfiler(session.store)
                values = profiler.sample_values(source, field, principal=principal, limit=limit, workspace_id=workspace_id)
                return _json_response(self, 200, {"source": source, "field": field, "values": values})
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

            if path == "/v1/explore/analyze":
                # Major Goal 2 -- distinct from GET /v1/explore (row 37's
                # query-free Sense-board aggregation view). This endpoint
                # scores candidate field-pair matches between two sources.
                from synapse.matching import analyze_sources, score_pair, transitive_candidates
                from synapse.profiling import SchemaProfiler

                principal = _principal_from_body(body, session.store)
                source_a = body.get("source_a")
                source_b = body.get("source_b")
                field_a = body.get("field_a")
                field_b = body.get("field_b")
                if not source_a:
                    return _json_response(self, 400, {"error": "source_a is required"})
                profiler = SchemaProfiler(session.store)
                profiles_a = profiler.profile_source(source_a, principal=principal)

                if source_b and field_a and field_b:
                    # Schema View: the user drew a connection between two
                    # specific fields directly, rather than picking from a
                    # scored all-pairs sweep -- score just that one pair,
                    # bypassing the normal strict-drop floor (they already
                    # decided by drawing the line; a low score is
                    # informational, not a reason to refuse them a drawer).
                    profiles_b = profiler.profile_source(source_b, principal=principal)
                    profile_a = profiles_a.get(field_a)
                    profile_b = profiles_b.get(field_b)
                    if profile_a is None or profile_b is None:
                        return _json_response(self, 404, {"error": "field not found in profiled source"})
                    edge = score_pair(session.store, session.ontology, profile_a, profile_b, force=True)
                    candidates = [edge] if edge is not None else []
                elif source_b:
                    profiles_b = profiler.profile_source(source_b, principal=principal)
                    candidates = analyze_sources(session.store, session.ontology, profiles_a, profiles_b)
                else:
                    # Major Goal 4, task 3: no source_b given -- treat
                    # source_a as a newly-ingested Source C and evaluate it
                    # transitively against the ontology registry's already
                    # SAME_ENTITY_AS-linked sources.
                    candidates = transitive_candidates(
                        session.store, session.ontology, profiler, source_a, profiles_a, principal=principal
                    )
                session.candidate_cache.put_all(candidates)
                return _json_response(
                    self,
                    200,
                    {
                        "source_a": source_a,
                        "source_b": source_b,
                        "candidates": [c.to_dict() for c in candidates],
                    },
                )

            if path == "/v1/workspaces":
                from synapse.workspace import Workspace

                name = (body.get("name") or "").strip()
                if not name:
                    return _json_response(self, 400, {"error": "name is required"})
                description = (body.get("description") or "").strip()
                ws = Workspace.create(name, description)
                session.store.put_workspace(ws)
                return _json_response(self, 200, ws.to_dict())

            if path.startswith("/v1/workspaces/") and path.endswith("/clone"):
                principal = _principal_from_body(body, session.store)
                if not _require_role(self, principal, "operator"):
                    return None
                source_workspace_id = path[len("/v1/workspaces/"):-len("/clone")]
                if source_workspace_id not in session.store.workspaces:
                    return _json_response(self, 404, {"error": f"unknown workspace_id: {source_workspace_id}"})
                name = (body.get("name") or "").strip()
                if not name:
                    return _json_response(self, 400, {"error": "name is required"})
                description = (body.get("description") or "").strip()
                new_ws = session.store.clone_workspace(
                    source_workspace_id, name, description, ontology=session.ontology
                )
                return _json_response(self, 200, new_ws.to_dict())

            if path == "/v1/super-schema":
                from synapse.profiling import SchemaProfiler
                from synapse.super_schema import compute_super_schema

                principal = _principal_from_body(body, session.store)
                workspace_ids = body.get("workspace_ids") or []
                if not isinstance(workspace_ids, list) or len(workspace_ids) < 2:
                    return _json_response(self, 400, {"error": "workspace_ids must be a list of at least 2 ids"})
                unknown = [w for w in workspace_ids if w not in session.store.workspaces]
                if unknown:
                    return _json_response(self, 400, {"error": f"unknown workspace_ids: {unknown}"})
                profiler = SchemaProfiler(session.store)
                result = compute_super_schema(
                    session.store, session.ontology, profiler, workspace_ids, principal=principal
                )
                return _json_response(self, 200, result)

            if path == "/v1/materialize/star-schema/preview":
                from synapse.profiling import SchemaProfiler
                from synapse.star_schema import preview_star_schema

                principal = _principal_from_body(body, session.store)
                if not _require_role(self, principal, "operator"):
                    return None
                workspace_ids = body.get("workspace_ids") or []
                if not isinstance(workspace_ids, list) or len(workspace_ids) < 1:
                    return _json_response(self, 400, {"error": "workspace_ids must be a non-empty list"})
                unknown = [w for w in workspace_ids if w not in session.store.workspaces]
                if unknown:
                    return _json_response(self, 400, {"error": f"unknown workspace_ids: {unknown}"})
                profiler = SchemaProfiler(session.store)
                result = preview_star_schema(
                    session.store, session.ontology, profiler, workspace_ids, principal=principal
                )
                return _json_response(self, 200, result)

            if path == "/v1/materialize/star-schema/execute":
                import re as _re

                from synapse.profiling import SchemaProfiler
                from synapse.star_schema import execute_star_schema

                principal = _principal_from_body(body, session.store)
                if not _require_role(self, principal, "operator"):
                    return None
                workspace_ids = body.get("workspace_ids") or []
                if not isinstance(workspace_ids, list) or len(workspace_ids) < 1:
                    return _json_response(self, 400, {"error": "workspace_ids must be a non-empty list"})
                unknown = [w for w in workspace_ids if w not in session.store.workspaces]
                if unknown:
                    return _json_response(self, 400, {"error": f"unknown workspace_ids: {unknown}"})
                target_db_path = body.get("target_db_path")
                if not target_db_path:
                    label = "_".join(_re.sub(r"[^A-Za-z0-9]+", "-", w) for w in workspace_ids)
                    target_db_path = f".data/warehouse_{label}.db"
                profiler = SchemaProfiler(session.store)
                result = execute_star_schema(
                    session.store, session.ontology, profiler, workspace_ids, target_db_path, principal=principal
                )
                return _json_response(self, 200, result)

            if path == "/v1/explore/ingest":
                # Explore journey step 1 for real use, not just already-
                # landed demo sources: the browser reads a picked file's
                # text client-side (File API) and POSTs its content here --
                # no server-filesystem path required (unlike the older
                # /v1/sense/drop CSV/JSONL "kind", which expects a path on
                # the box the server itself runs on). Landing logic mirrors
                # CsvDropConnector.poll() for CSV (synapse/connectors/
                # csv_drop.py) so the resulting RawObjects are identical in
                # shape either way.
                principal = _principal_from_body(body, session.store)
                if not _require_role(self, principal, "operator"):
                    return None
                filename = (body.get("filename") or "").strip()
                content = body.get("content")
                source_system = (body.get("source_system") or "").strip() or (
                    filename.rsplit(".", 1)[0] if filename else "Uploaded"
                )
                acl = body.get("acl_tags") or ["domain:sre", "clearance:l2"]
                workspace_id = (body.get("workspace_id") or "").strip() or "default"
                if content is None:
                    return _json_response(self, 400, {"error": "content required"})

                ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                landed = 0

                def _land_only(payload: str):
                    return session.ingestion.land(
                        source_system, payload, list(acl), actor="api:explore-ingest", workspace_id=workspace_id
                    )

                if ext == "csv":
                    import csv as _csv
                    import io as _io

                    # Entity extraction is deliberately skipped for bulk
                    # CSV rows: it's a per-row rule-matching pass that made
                    # a 150-row file take minutes, causing a real upload
                    # to silently stall/timeout mid-file. Explore's own
                    # purpose (schema profiling + field matching) reads
                    # RawObjects directly and never needed extraction --
                    # it only fed the optional GraphProximity signal and
                    # the Resolve tab's entity candidates, which is a
                    # secondary benefit, not worth the multi-minute cost on
                    # every upload. Use POST /v1/reprocess afterward if
                    # entity extraction over this data is actually wanted.
                    reader = _csv.DictReader(_io.StringIO(content))
                    for row in reader:
                        lines = [f"{k}: {v}" for k, v in row.items() if v not in (None, "")]
                        if not lines:
                            continue
                        _land_only("\n".join(lines))
                        landed += 1
                elif ext == "jsonl":
                    for line in content.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        _land_only(line)
                        landed += 1
                else:
                    # .json or anything else: one raw object, whole content
                    # (profiler's JSON flattener handles this shape -- row 49).
                    # A single call, so extraction here stays cheap enough to keep.
                    if content.strip():
                        result = _land_only(content)
                        if not result.dropped:
                            session.dual_path.extract(result.episode, result.raw)
                        landed = 1
                        stripped_content = content.lstrip()
                        if stripped_content.startswith("MSH"):
                            # HL7's segments (PID/ORC/OBR/OBX) are true
                            # structural facts of the message, not inferred
                            # candidates -- auto-confirm them so Explore/
                            # Schema View show the file already connected
                            # instead of requiring a click on something
                            # that was never actually in question.
                            from synapse.hl7_semantics import auto_link_structure

                            auto_link_structure(session.store, session.ontology, source_system)
                        elif stripped_content[:1] in ("{", "["):
                            # Same reasoning for a FHIR Bundle: every
                            # resource genuinely belongs to the bundle it
                            # was landed with, not a matched guess.
                            from synapse.profiling import auto_link_fhir_bundle

                            auto_link_fhir_bundle(session.store, session.ontology, source_system)
                session.sync_graph()
                return _json_response(
                    self,
                    200,
                    {
                        "source_system": source_system,
                        "filename": filename,
                        "objects_landed": landed,
                        "workspace_id": workspace_id,
                    },
                )

            if path == "/v1/ontology/relationships/dedupe":
                # One-time cleanup: before ACCEPT/RELABEL correctly threaded
                # relationship_id through (this same fix), re-confirming an
                # already-confirmed field pair with a fresh candidate_id
                # minted a brand new RelationshipEdge instead of recognizing
                # the existing one. Collapses whatever duplicates already
                # accumulated; safe to call repeatedly (no-op once clean).
                principal = _principal_from_body(body, session.store)
                if not _require_role(self, principal, "operator"):
                    return None
                result = session.ontology.dedupe_relationships()
                return _json_response(self, 200, result)

            if path == "/v1/schema/layout":
                principal = _principal_from_body(body, session.store)
                if not _require_role(self, principal, "operator"):
                    return None
                source_system = body.get("source_system")
                x = body.get("x")
                y = body.get("y")
                if not source_system or x is None or y is None:
                    return _json_response(self, 400, {"error": "source_system, x, y are required"})
                entry = session.store.put_layout_position(source_system, float(x), float(y))
                return _json_response(self, 200, entry)

            if path == "/v1/ontology/relationships":
                # Major Goal 4, task 1 (Ontology Write-Back) -- curation
                # canvas ACCEPT/REJECT/RELABEL actions land here.
                principal = _principal_from_body(body, session.store)
                if not _require_role(self, principal, "operator"):
                    return None
                action = (body.get("action") or "").upper()
                candidate_id = body.get("candidate_id")
                if action in ("ACCEPT", "RELABEL") and not candidate_id and not body.get("relationship_id"):
                    return _json_response(self, 400, {"error": "candidate_id required"})

                if action == "ACCEPT":
                    existing = session.ontology.find_relationship_by_candidate_id(candidate_id)
                    if existing is not None:
                        # Already accepted -- return the existing edge rather
                        # than minting a duplicate catalog entry (F-029).
                        return _json_response(self, 200, existing.to_dict())
                    candidate = session.candidate_cache.get(candidate_id)
                    if candidate is None:
                        return _json_response(self, 404, {"error": "unknown_candidate_id"})
                    try:
                        edge = session.ontology.accept_relationship(
                            candidate_id=candidate.candidate_id,
                            source_a=candidate.source_a,
                            source_b=candidate.source_b,
                            predicate=body.get("predicate", "SAME_ENTITY_AS"),
                            match_reasons=candidate.match_reasons,
                            similarity_score=candidate.similarity_score,
                        )
                    except ValueError as exc:
                        return _json_response(self, 400, {"error": str(exc)})
                    # Major Goal 4, task 2: instantly widen ER blocking for a
                    # confirmed SAME_ENTITY_AS field-level relationship.
                    if edge.predicate == "SAME_ENTITY_AS":
                        er.link_schema_fields(edge.source_a, edge.source_b)
                    return _json_response(self, 200, edge.to_dict())

                if action == "REJECT":
                    candidate = session.candidate_cache.get(candidate_id)
                    source_a = candidate.source_a if candidate else body.get("source_a", {})
                    source_b = candidate.source_b if candidate else body.get("source_b", {})
                    rejected = session.ontology.reject_relationship(
                        candidate_id=candidate_id or "",
                        source_a=source_a,
                        source_b=source_b,
                        reason=body.get("reason", ""),
                    )
                    return _json_response(self, 200, rejected.to_dict())

                if action == "RELABEL":
                    relationship_id = body.get("relationship_id")
                    new_predicate = body.get("predicate")
                    if not new_predicate:
                        return _json_response(self, 400, {"error": "predicate required"})
                    if not relationship_id:
                        existing = session.ontology.find_relationship_by_candidate_id(candidate_id)
                        if existing is not None:
                            relationship_id = existing.relationship_id
                    if relationship_id:
                        updated = session.ontology.relabel_relationship(relationship_id, new_predicate)
                        if updated is None:
                            return _json_response(self, 404, {"error": "unknown_relationship_id"})
                        return _json_response(self, 200, updated.to_dict())
                    candidate = session.candidate_cache.get(candidate_id)
                    if candidate is None:
                        return _json_response(self, 404, {"error": "unknown_candidate_id"})
                    try:
                        edge = session.ontology.accept_relationship(
                            candidate_id=candidate.candidate_id,
                            source_a=candidate.source_a,
                            source_b=candidate.source_b,
                            predicate=new_predicate,
                            match_reasons=candidate.match_reasons,
                            similarity_score=candidate.similarity_score,
                        )
                    except ValueError as exc:
                        return _json_response(self, 400, {"error": str(exc)})
                    return _json_response(self, 200, edge.to_dict())

                return _json_response(self, 400, {"error": "action must be ACCEPT, REJECT, or RELABEL"})

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
                from synapse.graph_memory import derive_group_id
                from synapse.graphiti_ops import GraphitiOps

                q = body.get("query") or ""
                if not q:
                    return _json_response(self, 400, {"error": "query required"})
                principal = _principal_from_body(body, session.store)
                visible_episodes = filter_episodes(principal, session.store.episodes.values())
                allowed_group_ids = sorted(
                    {derive_group_id(ep.acl_tags) for ep in visible_episodes}
                )
                ops = GraphitiOps()
                try:
                    hits = ops.search(
                        q,
                        num_results=int(body.get("limit") or 8),
                        group_ids=allowed_group_ids,
                    )
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
                                path=file_path,
                                connector_id=cid,
                                source_system=source,
                                default_acl=list(acl),
                            )
                        else:
                            from synapse.connectors.file_jsonl import (
                                JsonlFileConnector,
                            )

                            conn = JsonlFileConnector(
                                path=file_path,
                                connector_id=cid,
                                source_system=source,
                                default_acl=list(acl),
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
