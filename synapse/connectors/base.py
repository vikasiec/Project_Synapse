"""
Connector contracts.

Org-wide continuous data enters Synapse as ChangeEvents, not one-shot dumps.
Implementations: mock CDC, JSONL file tail, (later) real DB/SaaS CDC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Optional

from synapse.models import utc_now_iso


@dataclass
class ConnectorWatermark:
    """Per-connector cursor for resume / late data."""

    connector_id: str
    position: str  # opaque: offset, LSN, timestamp, file byte
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeEvent:
    """One unit of change from a source system."""

    event_id: str
    source_system: str
    payload: str
    occurred_at: str
    acl_tags: list[str] = field(default_factory=list)
    op: str = "upsert"  # upsert | delete | snapshot
    source_uri: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Connector(ABC):
    """Pull-based connector with watermarked poll."""

    connector_id: str
    source_system: str

    @abstractmethod
    def poll(self, watermark: Optional[ConnectorWatermark] = None) -> list[ChangeEvent]:
        """Return new events since watermark (exclusive)."""

    @abstractmethod
    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        """Compute next watermark after successfully processing events."""

    def describe(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "source_system": self.source_system,
            "type": type(self).__name__,
        }
