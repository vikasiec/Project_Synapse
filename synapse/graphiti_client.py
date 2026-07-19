"""
Graphiti client protocol + offline recording fake.

Real Graphiti (getzep) is optional. Tests and offline demos inject
RecordingGraphitiClient to verify the integration seam without Neo4j.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class EpisodePush:
    name: str
    body: str
    source_description: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class GraphitiClient(Protocol):
    """Minimal surface Synapse needs from a Graphiti-like backend."""

    def add_episode(
        self,
        name: str,
        episode_body: str,
        source_description: str = "",
        **kwargs: Any,
    ) -> Any: ...


class RecordingGraphitiClient:
    """
    Fake Graphiti for offline verification.

    Records every add_episode call so tests can assert push behavior.
    """

    def __init__(self) -> None:
        self.episodes: list[EpisodePush] = []
        self.fail_next: bool = False

    def add_episode(
        self,
        name: str = "",
        episode_body: str = "",
        source_description: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Accept alternate kw names used by different Graphiti versions
        body = episode_body or kwargs.get("body") or kwargs.get("content") or ""
        nm = name or kwargs.get("episode_name") or f"ep-{len(self.episodes)}"
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated Graphiti failure")
        rec = EpisodePush(
            name=str(nm),
            body=str(body),
            source_description=str(source_description or kwargs.get("source") or ""),
            meta={k: v for k, v in kwargs.items() if k not in {"body", "content"}},
        )
        self.episodes.append(rec)
        return {"ok": True, "name": rec.name, "index": len(self.episodes) - 1}

    def reset(self) -> None:
        self.episodes.clear()


def try_import_real_graphiti() -> tuple[Optional[type], Optional[str]]:
    """Return (GraphitiClass, module_name) or (None, error)."""
    try:
        from graphiti_core import Graphiti  # type: ignore

        return Graphiti, "graphiti_core"
    except ImportError:
        pass
    try:
        from graphiti import Graphiti  # type: ignore

        return Graphiti, "graphiti"
    except ImportError as exc:
        return None, str(exc)
