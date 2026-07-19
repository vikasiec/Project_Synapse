"""
Graph memory adapter layer (Graphiti-shaped).

- LocalGraphitiStub: always-available in-process temporal graph
- OptionalGraphitiAdapter: wraps getzep/graphiti when installed + configured
- create_graph_adapter(): factory with env / explicit backend selection
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from synapse.models import EntityStatus, Fact, utc_now_iso
from synapse.store import SemanticStore


@dataclass
class GraphNode:
    node_id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    edge_id: str
    source_id: str
    target_id: str
    predicate: str
    valid_from: str
    valid_to: Optional[str] = None
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphSnapshot:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    built_at: str
    backend: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "built_at": self.built_at,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }


@runtime_checkable
class GraphMemoryAdapter(Protocol):
    name: str

    def sync_from_store(self, store: SemanticStore) -> GraphSnapshot: ...

    def neighborhood(self, entity_id: str, *, depth: int = 1) -> dict[str, Any]: ...

    def path(self, source_id: str, target_id: str) -> list[str]: ...

    def stats(self) -> dict[str, Any]: ...


class LocalGraphitiStub:
    """
    In-process temporal graph built from Entity + Fact.

    Nodes: entities (+ literal value nodes for fact objects)
    Edges: entity --predicate--> value_node with temporal validity
    """

    name = "local_graphiti_stub"

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._adj: dict[str, list[str]] = {}

    def sync_from_store(self, store: SemanticStore) -> GraphSnapshot:
        self._nodes.clear()
        self._edges.clear()
        self._adj.clear()

        for ent in store.entities.values():
            if ent.status == EntityStatus.MERGED and ent.merged_into:
                self._add_node(
                    GraphNode(
                        node_id=ent.entity_id,
                        label="Entity",
                        properties={
                            "entity_type": ent.entity_type,
                            "canonical_name": ent.canonical_name,
                            "status": ent.status.value,
                            "merged_into": ent.merged_into,
                        },
                    )
                )
                self._add_edge(
                    GraphEdge(
                        edge_id=f"merge:{ent.entity_id}",
                        source_id=ent.entity_id,
                        target_id=ent.merged_into,
                        predicate="merged_into",
                        valid_from=utc_now_iso(),
                        properties={"status": "merged"},
                    )
                )
                continue

            self._add_node(
                GraphNode(
                    node_id=ent.entity_id,
                    label="Entity",
                    properties={
                        "entity_type": ent.entity_type,
                        "canonical_name": ent.canonical_name,
                        "status": ent.status.value,
                        "aliases": list(ent.aliases),
                        "trust_score": ent.trust_score,
                    },
                )
            )

        for fact in store.facts.values():
            value_id = self._value_node_id(fact)
            self._add_node(
                GraphNode(
                    node_id=value_id,
                    label="Value",
                    properties={
                        "predicate": fact.predicate,
                        "object": fact.object,
                        "source_system": fact.source_system,
                    },
                )
            )
            self._add_edge(
                GraphEdge(
                    edge_id=fact.fact_id,
                    source_id=fact.subject_entity_id,
                    target_id=value_id,
                    predicate=fact.predicate,
                    valid_from=fact.valid_from,
                    valid_to=fact.valid_to,
                    properties={
                        "confidence": fact.confidence,
                        "source_system": fact.source_system,
                        "current": fact.valid_to is None,
                    },
                )
            )

        return GraphSnapshot(
            nodes=list(self._nodes.values()),
            edges=list(self._edges),
            built_at=utc_now_iso(),
            backend=self.name,
        )

    def neighborhood(self, entity_id: str, *, depth: int = 1) -> dict[str, Any]:
        if not self._nodes:
            return {"entity_id": entity_id, "nodes": [], "edges": []}

        frontier = {entity_id}
        seen_nodes = set(frontier)
        for _ in range(max(0, depth)):
            nxt: set[str] = set()
            for n in frontier:
                for m in self._adj.get(n, []):
                    if m not in seen_nodes:
                        seen_nodes.add(m)
                        nxt.add(m)
            frontier = nxt

        nodes = [self._nodes[i].to_dict() for i in seen_nodes if i in self._nodes]
        edges = [
            e.to_dict()
            for e in self._edges
            if e.source_id in seen_nodes and e.target_id in seen_nodes
        ]
        return {"entity_id": entity_id, "depth": depth, "nodes": nodes, "edges": edges}

    def path(self, source_id: str, target_id: str) -> list[str]:
        if source_id == target_id:
            return [source_id]
        from collections import deque

        q = deque([(source_id, [source_id])])
        visited = {source_id}
        while q:
            node, trail = q.popleft()
            for nb in self._adj.get(node, []):
                if nb in visited:
                    continue
                new_trail = trail + [nb]
                if nb == target_id:
                    return new_trail
                visited.add(nb)
                q.append((nb, new_trail))
        return []

    def stats(self) -> dict[str, Any]:
        current_edges = sum(1 for e in self._edges if e.valid_to is None)
        return {
            "backend": self.name,
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "current_edges": current_edges,
            "historical_edges": len(self._edges) - current_edges,
        }

    def _add_node(self, node: GraphNode) -> None:
        self._nodes[node.node_id] = node
        self._adj.setdefault(node.node_id, [])

    def _add_edge(self, edge: GraphEdge) -> None:
        self._edges.append(edge)
        self._adj.setdefault(edge.source_id, []).append(edge.target_id)
        self._adj.setdefault(edge.target_id, []).append(edge.source_id)

    @staticmethod
    def _value_node_id(fact: Fact) -> str:
        return f"val:{fact.predicate}:{fact.object!s}:{fact.source_system}"


class OptionalGraphitiAdapter:
    """
    Optional bridge to getzep/graphiti.

    Behavior:
      1. Injected client (RecordingGraphitiClient or real) → push mode
      2. Else try import graphiti when GRAPHITI_ENABLED=1
      3. Always keep LocalGraphitiStub mirror for neighborhood queries
    """

    name = "optional_graphiti"

    def __init__(self, client: Any = None) -> None:
        self._local = LocalGraphitiStub()
        self._client = client
        self._mode = "local_mirror"
        self._last_error: Optional[str] = None
        self._episodes_pushed = 0
        self._pushed_ids: set[str] = set()
        if client is not None:
            self._mode = "client_injected"
        else:
            self._try_connect()

    def _try_connect(self) -> None:
        enabled = os.environ.get("GRAPHITI_ENABLED", "").lower() in {
            "1",
            "true",
            "yes",
        }
        if not enabled:
            self._mode = "local_mirror"
            return
        try:
            from synapse.graphiti_factory import build_graphiti_client

            self._client, label = build_graphiti_client()
            self._mode = "graphiti_connected"
            self._last_error = None
            # store label only for stats
            self._backend_label = label
        except Exception as exc:
            self._client = None
            self._mode = "local_mirror"
            # Never include secrets in error strings (uri ok; redact passwords if any)
            msg = str(exc)
            for secret_env in (
                "NEO4J_PASSWORD",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "GRAPHITI_PASSWORD",
            ):
                val = os.environ.get(secret_env)
                if val and val in msg:
                    msg = msg.replace(val, "***")
            self._last_error = msg[:300]

    def sync_from_store(self, store: SemanticStore) -> GraphSnapshot:
        snap = self._local.sync_from_store(store)

        if self._client is not None and self._mode in {
            "graphiti_connected",
            "client_injected",
        }:
            try:
                self._push_episodes(store)
            except Exception as exc:
                self._last_error = f"push failed: {exc}"
                # keep client for retry; still serve local graph
                self._mode = f"{self._mode}_push_error"

        return GraphSnapshot(
            nodes=snap.nodes,
            edges=snap.edges,
            built_at=snap.built_at,
            backend=f"{self.name}:{self._mode}",
        )

    def _push_episodes(self, store: SemanticStore) -> None:
        add_episode = getattr(self._client, "add_episode", None)
        if not callable(add_episode):
            return

        import asyncio
        import inspect
        from datetime import datetime, timezone

        # Free-tier guard for live Graphiti (many LLM calls per episode).
        # Injected/recording clients push all unless capped explicitly.
        if self._mode == "client_injected":
            max_push = int(os.environ.get("GRAPHITI_MAX_PUSH_EPISODES", "100000"))
        else:
            max_push = int(os.environ.get("GRAPHITI_MAX_PUSH_EPISODES", "2"))

        async def _push_all() -> None:
            # Build indices once if available
            build = getattr(self._client, "build_indices_and_constraints", None)
            if callable(build) and not getattr(self, "_indices_built", False):
                try:
                    if inspect.iscoroutinefunction(build):
                        await build()
                    else:
                        build()
                    self._indices_built = True
                except Exception:
                    pass

            pushed_this_run = 0
            for ep in store.episodes.values():
                if ep.episode_id in self._pushed_ids:
                    continue
                if pushed_this_run >= max_push:
                    break
                name = f"synapse-episode-{ep.episode_id[:8]}"
                body = ep.payload_text
                ref = datetime.now(timezone.utc)
                try:
                    if inspect.iscoroutinefunction(add_episode):
                        await add_episode(
                            name=name,
                            episode_body=body,
                            source_description=ep.domain or "synapse",
                            reference_time=ref,
                        )
                    else:
                        add_episode(
                            name=name,
                            episode_body=body,
                            source_description=ep.domain or "synapse",
                            reference_time=ref,
                        )
                except TypeError:
                    if inspect.iscoroutinefunction(add_episode):
                        await add_episode(
                            name=name,
                            episode_body=body,
                            source_description=ep.domain or "synapse",
                        )
                    else:
                        add_episode(
                            name=name,
                            episode_body=body,
                            source_description=ep.domain or "synapse",
                        )
                self._pushed_ids.add(ep.episode_id)
                self._episodes_pushed += 1
                pushed_this_run += 1

        try:
            asyncio.get_running_loop()
            # Already in async context — schedule and wait via nest if needed
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: asyncio.run(_push_all())).result(timeout=600)
        except RuntimeError:
            asyncio.run(_push_all())

    def neighborhood(self, entity_id: str, *, depth: int = 1) -> dict[str, Any]:
        out = self._local.neighborhood(entity_id, depth=depth)
        out["backend"] = f"{self.name}:{self._mode}"
        return out

    def path(self, source_id: str, target_id: str) -> list[str]:
        return self._local.path(source_id, target_id)

    def stats(self) -> dict[str, Any]:
        base = self._local.stats()
        base["backend"] = f"{self.name}:{self._mode}"
        base["episodes_pushed"] = self._episodes_pushed
        base["last_error"] = self._last_error
        return base


class GraphitiRemoteAdapter(OptionalGraphitiAdapter):
    """Alias kept for older imports."""


def create_graph_adapter(
    backend: Optional[str] = None,
    *,
    client: Any = None,
) -> GraphMemoryAdapter:
    """
    Factory.

    backend:
      - "local" | "stub" → LocalGraphitiStub
      - "graphiti" | "optional" | "remote" → OptionalGraphitiAdapter
    client: optional injected GraphitiClient (e.g. RecordingGraphitiClient)
    """
    choice = (backend or os.environ.get("SYNAPSE_GRAPH_BACKEND") or "local").lower()
    if client is not None or choice in {"graphiti", "optional", "remote"}:
        return OptionalGraphitiAdapter(client=client)
    return LocalGraphitiStub()


def graphiti_available() -> dict[str, Any]:
    """Diagnostics for CI / health endpoint."""
    from synapse.graphiti_client import try_import_real_graphiti

    cls, mod_or_err = try_import_real_graphiti()
    return {
        "graphiti_enabled_env": os.environ.get("GRAPHITI_ENABLED", ""),
        "importable": cls is not None,
        "module": mod_or_err if cls is not None else None,
        "error": None if cls is not None else mod_or_err,
    }
