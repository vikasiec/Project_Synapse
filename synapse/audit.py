"""Append-only audit trail for security and adjudication events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional
from uuid import uuid4

from synapse.models import utc_now_iso

OnRecord = Callable[["AuditEvent"], None]


@dataclass
class AuditEvent:
    event_id: str
    event_type: str
    timestamp: str
    actor: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditLog:
    """In-memory append-only log; optional sink for durable backends."""

    def __init__(self, on_record: Optional[OnRecord] = None) -> None:
        self.events: list[AuditEvent] = []
        self._on_record = on_record

    def set_sink(self, on_record: Optional[OnRecord]) -> None:
        self._on_record = on_record

    def record(
        self,
        event_type: str,
        *,
        actor: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=str(uuid4()),
            event_type=event_type,
            timestamp=utc_now_iso(),
            actor=actor,
            detail=dict(detail or {}),
        )
        self.events.append(event)
        if self._on_record is not None:
            self._on_record(event)
        return event

    def by_type(self, event_type: str) -> list[AuditEvent]:
        return [e for e in self.events if e.event_type == event_type]

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.events]
