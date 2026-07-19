"""
Webhook / HTTP drop connector (POC).

Append JSON events to an in-memory or file-backed queue; poll like CDC.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from synapse.connectors.base import ChangeEvent, Connector, ConnectorWatermark
from synapse.models import new_id, utc_now_iso


@dataclass
class WebhookInboxConnector(Connector):
    """
    Accepts push events via enqueue(); poll drains since watermark.
    Optional path: persist queue as JSONL for restart durability.
    """

    connector_id: str = "webhook-inbox"
    source_system: str = "Webhook"
    path: Optional[str] = None
    _queue: list[dict[str, Any]] = field(default_factory=list)
    _seq: int = 0

    def __post_init__(self) -> None:
        if self.path and Path(self.path).is_file():
            for line in Path(self.path).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._queue.append(json.loads(line))
                    self._seq = max(self._seq, int(self._queue[-1].get("_seq", 0)))
                except json.JSONDecodeError:
                    continue

    def enqueue(
        self,
        payload: str,
        *,
        source_system: Optional[str] = None,
        acl_tags: Optional[list[str]] = None,
        source_uri: Optional[str] = None,
    ) -> dict[str, Any]:
        self._seq += 1
        row = {
            "_seq": self._seq,
            "event_id": new_id(),
            "payload": payload,
            "source_system": source_system or self.source_system,
            "acl_tags": list(acl_tags or ["domain:sre", "clearance:l2"]),
            "source_uri": source_uri or f"webhook://{self.connector_id}/{self._seq}",
            "occurred_at": utc_now_iso(),
        }
        self._queue.append(row)
        if self.path:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"seq": self._seq, "event_id": row["event_id"]}

    def poll(
        self, watermark: Optional[ConnectorWatermark] = None
    ) -> list[ChangeEvent]:
        after = 0
        if watermark and watermark.position:
            try:
                after = int(watermark.position)
            except ValueError:
                after = 0
        out: list[ChangeEvent] = []
        for row in self._queue:
            seq = int(row.get("_seq", 0))
            if seq <= after:
                continue
            out.append(
                ChangeEvent(
                    event_id=row["event_id"],
                    source_system=row["source_system"],
                    payload=row["payload"],
                    occurred_at=row.get("occurred_at") or utc_now_iso(),
                    acl_tags=list(row.get("acl_tags") or []),
                    source_uri=row.get("source_uri"),
                    op="upsert",
                    meta={"position": str(seq)},
                )
            )
        return out

    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        if not events:
            return ConnectorWatermark(connector_id=self.connector_id, position="0")
        last = 0
        for e in events:
            try:
                last = max(last, int((e.meta or {}).get("position") or 0))
            except (TypeError, ValueError):
                continue
        return ConnectorWatermark(connector_id=self.connector_id, position=str(last))

    def describe(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "source_system": self.source_system,
            "type": "WebhookInboxConnector",
            "queued": len(self._queue),
            "path": self.path,
        }
