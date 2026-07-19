"""
CSV / spreadsheet drop connector (tribal data class).

Each new row since watermark becomes a ChangeEvent with a text payload
suitable for dual-path extract (key: value lines).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from synapse.connectors.base import ChangeEvent, Connector, ConnectorWatermark
from synapse.models import utc_now_iso


@dataclass
class CsvDropConnector(Connector):
    path: str
    connector_id: str = "csv-drop"
    source_system: str = "Spreadsheet"
    default_acl: list[str] = field(
        default_factory=lambda: ["domain:sre", "clearance:l2"]
    )
    _seen: int = 0

    def poll(
        self, watermark: Optional[ConnectorWatermark] = None
    ) -> list[ChangeEvent]:
        p = Path(self.path)
        if not p.is_file():
            return []
        start = 0
        if watermark and str(watermark.position).isdigit():
            start = int(watermark.position)
        events: list[ChangeEvent] = []
        with p.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                # row index 0-based; watermark is last processed index+1 style
                if i < start:
                    continue
                lines = [f"{k}: {v}" for k, v in row.items() if v not in (None, "")]
                payload = "\n".join(lines)
                events.append(
                    ChangeEvent(
                        event_id=str(uuid4()),
                        source_system=self.source_system,
                        payload=payload,
                        occurred_at=utc_now_iso(),
                        acl_tags=list(self.default_acl),
                        op="upsert",
                        source_uri=f"file://{p.resolve()}#row={i}",
                        meta={"row": i},
                    )
                )
        return events

    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        if not events:
            return ConnectorWatermark(
                connector_id=self.connector_id, position=str(self._seen)
            )
        last = max(int(e.meta.get("row", 0)) for e in events)
        self._seen = last + 1
        return ConnectorWatermark(
            connector_id=self.connector_id, position=str(self._seen)
        )

    def describe(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "source_system": self.source_system,
            "type": "CsvDropConnector",
            "path": self.path,
        }
