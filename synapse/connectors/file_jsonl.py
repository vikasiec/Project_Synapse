"""JSONL file connector — each line is a change payload or full event object."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union
from uuid import uuid4

from synapse.connectors.base import ChangeEvent, Connector, ConnectorWatermark
from synapse.models import utc_now_iso

PathLike = Union[str, Path]


@dataclass
class JsonlFileConnector(Connector):
    """
    Reads new lines from a JSONL file using byte-offset watermark.

    Line formats:
      - plain string payload
      - {"payload": "...", "source_system": "...", "acl_tags": [...]}
    """

    path: PathLike
    connector_id: str = "jsonl-file"
    source_system: str = "JsonlDrop"
    default_acl: list[str] = field(
        default_factory=lambda: ["domain:sre", "clearance:l2"]
    )

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def poll(self, watermark: Optional[ConnectorWatermark] = None) -> list[ChangeEvent]:
        if not self.path.exists():
            return []
        offset = 0
        if watermark and watermark.position.isdigit():
            offset = int(watermark.position)

        events: list[ChangeEvent] = []
        with self.path.open("r", encoding="utf-8") as f:
            f.seek(offset)
            while True:
                line_start = f.tell()
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                events.append(self._parse_line(line, line_start))
        return events

    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        if not events:
            pos = "0"
            if self.path.exists():
                pos = str(self.path.stat().st_size)
        else:
            # position after last event's byte start + line — store end offset in meta
            last = events[-1]
            end = last.meta.get("end_offset")
            pos = str(end if end is not None else self.path.stat().st_size)
        return ConnectorWatermark(connector_id=self.connector_id, position=pos)

    def _parse_line(self, line: str, start_offset: int) -> ChangeEvent:
        end_offset = start_offset + len(line.encode("utf-8")) + 1  # +newline approx
        payload = line
        source = self.source_system
        acl = list(self.default_acl)
        op = "upsert"
        meta: dict[str, Any] = {"start_offset": start_offset, "end_offset": end_offset}
        try:
            obj = json.loads(line)
            if isinstance(obj, str):
                payload = obj
            elif isinstance(obj, dict):
                payload = str(obj.get("payload") or obj.get("text") or line)
                source = str(obj.get("source_system") or source)
                if obj.get("acl_tags"):
                    acl = list(obj["acl_tags"])
                op = str(obj.get("op") or op)
                meta.update({k: v for k, v in obj.items() if k not in {"payload", "text"}})
                meta["start_offset"] = start_offset
                meta["end_offset"] = end_offset
        except json.JSONDecodeError:
            pass
        return ChangeEvent(
            event_id=str(uuid4()),
            source_system=source,
            payload=payload,
            occurred_at=utc_now_iso(),
            acl_tags=acl,
            op=op,
            source_uri=f"file://{self.path}#{start_offset}",
            meta=meta,
        )
