"""In-memory mock CDC stream for tests and demos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from synapse.connectors.base import ChangeEvent, Connector, ConnectorWatermark
from synapse.models import utc_now_iso


@dataclass
class MockCdcConnector(Connector):
    """
    Queue of synthetic change events.
    poll() returns events after current watermark index.
    """

    connector_id: str = "mock-cdc"
    source_system: str = "MockSource"
    default_acl: list[str] = field(default_factory=lambda: ["domain:sre", "clearance:l2"])
    _queue: list[ChangeEvent] = field(default_factory=list)
    _cursor: int = 0

    def emit(
        self,
        payload: str,
        *,
        source_system: Optional[str] = None,
        acl_tags: Optional[list[str]] = None,
        op: str = "upsert",
    ) -> ChangeEvent:
        ev = ChangeEvent(
            event_id=str(uuid4()),
            source_system=source_system or self.source_system,
            payload=payload,
            occurred_at=utc_now_iso(),
            acl_tags=list(acl_tags or self.default_acl),
            op=op,
            source_uri=f"mock://{self.connector_id}/{len(self._queue)}",
            meta={"seq": len(self._queue)},
        )
        self._queue.append(ev)
        return ev

    def poll(self, watermark: Optional[ConnectorWatermark] = None) -> list[ChangeEvent]:
        start = 0
        if watermark and watermark.position.isdigit():
            start = int(watermark.position) + 1
        elif self._cursor:
            start = self._cursor
        return list(self._queue[start:])

    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        if not events:
            pos = str(max(self._cursor - 1, -1))
        else:
            # last event meta seq or index in queue
            last = events[-1]
            seq = last.meta.get("seq")
            if seq is None:
                # find index
                try:
                    seq = self._queue.index(last)
                except ValueError:
                    seq = self._cursor + len(events) - 1
            pos = str(seq)
            self._cursor = int(pos) + 1
        return ConnectorWatermark(connector_id=self.connector_id, position=pos)
