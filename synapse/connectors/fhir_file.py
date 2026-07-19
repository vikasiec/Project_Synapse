"""
FHIR Bundle directory connector (Active_File.md task 15).

Each *.json file in the directory is treated as one Bundle resource -> one
ChangeEvent, landed as raw JSON text (schema-on-read: no parsing happens
here, that's extraction's job -- see synapse/fhir.py). Domain-blind: this
connector knows nothing about FHIR semantics, only "one file = one record",
same pattern as csv_drop.py / hl7_file.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from synapse.connectors.base import ChangeEvent, Connector, ConnectorWatermark
from synapse.models import utc_now_iso


@dataclass
class FhirDirectoryConnector(Connector):
    path: str
    connector_id: str = "fhir-dir"
    source_system: str = "FHIR-Interface"
    default_acl: list[str] = field(
        default_factory=lambda: ["domain:clinical", "clearance:l2"]
    )
    _baseline: set = field(default_factory=set, repr=False)

    def poll(
        self, watermark: Optional[ConnectorWatermark] = None
    ) -> list[ChangeEvent]:
        root = Path(self.path)
        if not root.is_dir():
            return []
        seen: set = set()
        if watermark and watermark.position:
            seen = set(watermark.position.split(","))
        self._baseline = set(seen)

        events: list[ChangeEvent] = []
        for fpath in sorted(root.glob("*.json")):
            if fpath.name in seen:
                continue
            text = fpath.read_text(encoding="utf-8")
            events.append(
                ChangeEvent(
                    event_id=str(uuid4()),
                    source_system=self.source_system,
                    payload=text,
                    occurred_at=utc_now_iso(),
                    acl_tags=list(self.default_acl),
                    op="upsert",
                    source_uri=f"file://{fpath.resolve()}",
                    meta={"filename": fpath.name},
                )
            )
        return events

    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        names = {e.meta.get("filename") for e in events if e.meta.get("filename")}
        total = self._baseline | names
        return ConnectorWatermark(
            connector_id=self.connector_id, position=",".join(sorted(total))
        )

    def describe(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "source_system": self.source_system,
            "type": "FhirDirectoryConnector",
            "path": self.path,
        }
