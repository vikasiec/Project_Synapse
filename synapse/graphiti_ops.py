"""
High-level Graphiti operations for the POC (search, push, status).

All secrets via env/.env. Errors are redacted.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional


def _redact(msg: str) -> str:
    for k in (
        "NEO4J_PASSWORD",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GRAPHITI_PASSWORD",
    ):
        v = os.environ.get(k)
        if v and v in msg:
            msg = msg.replace(v, "***")
    return msg[:400]


@dataclass
class SearchHit:
    uuid: str
    name: str
    fact: str
    source_node_uuid: Optional[str] = None
    target_node_uuid: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GraphitiOps:
    """Thin sync facade over async graphiti_core client."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    def _ensure_client(self) -> Any:
        if self._client is None:
            from synapse.graphiti_factory import build_graphiti_client

            self._client, _ = build_graphiti_client()
            self._owns_client = True
        return self._client

    def close(self) -> None:
        if not self._client or not self._owns_client:
            return
        close = getattr(self._client, "close", None)
        if not callable(close):
            return
        try:
            maybe = close()
            if inspect.iscoroutine(maybe):
                asyncio.run(maybe)
        except RuntimeError:
            # event loop already running
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(maybe)  # type: ignore[arg-type]
                else:
                    loop.run_until_complete(maybe)
            except Exception:
                pass
        self._client = None

    def search(self, query: str, *, num_results: int = 8) -> list[SearchHit]:
        client = self._ensure_client()

        async def _run() -> list[SearchHit]:
            edges = await client.search(query, num_results=num_results)
            hits: list[SearchHit] = []
            for e in edges or []:
                hits.append(
                    SearchHit(
                        uuid=str(getattr(e, "uuid", "") or ""),
                        name=str(getattr(e, "name", "") or ""),
                        fact=str(getattr(e, "fact", "") or ""),
                        source_node_uuid=str(getattr(e, "source_node_uuid", "") or "")
                        or None,
                        target_node_uuid=str(getattr(e, "target_node_uuid", "") or "")
                        or None,
                    )
                )
            return hits

        return asyncio.run(_run())

    def add_episode_text(
        self,
        body: str,
        *,
        name: Optional[str] = None,
        source_description: str = "synapse_poc",
    ) -> dict[str, Any]:
        client = self._ensure_client()

        async def _run() -> dict[str, Any]:
            build = getattr(client, "build_indices_and_constraints", None)
            if callable(build):
                try:
                    if inspect.iscoroutinefunction(build):
                        await build()
                    else:
                        build()
                except Exception:
                    pass
            result = await client.add_episode(
                name=name or f"synapse-{datetime.now(timezone.utc).strftime('%H%M%S')}",
                episode_body=body,
                source_description=source_description,
                reference_time=datetime.now(timezone.utc),
            )
            return {"type": type(result).__name__, "ok": True}

        return asyncio.run(_run())

    def status(self) -> dict[str, Any]:
        try:
            from synapse.env_load import load_dotenv

            load_dotenv()
            enabled = os.environ.get("GRAPHITI_ENABLED", "").lower() in {
                "1",
                "true",
                "yes",
            }
            neo4j_uri = os.environ.get("NEO4J_URI")
            has_key = bool(
                os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            )
            out: dict[str, Any] = {
                "graphiti_enabled": enabled,
                "neo4j_uri_set": bool(neo4j_uri),
                "gemini_key_set": has_key,
                "model": os.environ.get("GEMINI_MODEL"),
                "embed_model": os.environ.get("GEMINI_EMBED_MODEL"),
            }
            if enabled and neo4j_uri and has_key:
                # connectivity probe only
                from neo4j import GraphDatabase

                user = os.environ.get("NEO4J_USER", "neo4j")
                password = os.environ.get("NEO4J_PASSWORD", "")
                driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
                try:
                    driver.verify_connectivity()
                    out["neo4j_ready"] = True
                finally:
                    driver.close()
            return out
        except Exception as e:
            return {"ok": False, "error": _redact(str(e))}
