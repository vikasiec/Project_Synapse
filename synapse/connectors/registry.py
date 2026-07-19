"""Connector registry + watermark store (in-memory / dict)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from synapse.connectors.base import Connector, ConnectorWatermark
from synapse.connectors.file_jsonl import JsonlFileConnector
from synapse.connectors.mock_cdc import MockCdcConnector


@dataclass
class ConnectorRegistry:
    connectors: dict[str, Connector] = field(default_factory=dict)
    watermarks: dict[str, ConnectorWatermark] = field(default_factory=dict)

    def register(self, connector: Connector) -> None:
        self.connectors[connector.connector_id] = connector

    def get(self, connector_id: str) -> Connector:
        if connector_id not in self.connectors:
            raise KeyError(f"Unknown connector: {connector_id}")
        return self.connectors[connector_id]

    def list(self) -> list[dict]:
        return [c.describe() for c in self.connectors.values()]

    def watermark(self, connector_id: str) -> Optional[ConnectorWatermark]:
        return self.watermarks.get(connector_id)

    def set_watermark(self, wm: ConnectorWatermark) -> None:
        self.watermarks[wm.connector_id] = wm


def build_default_registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(MockCdcConnector(connector_id="mock-cdc", source_system="MockSource"))
    try:
        from pathlib import Path

        from synapse.connectors.webhook_inbox import WebhookInboxConnector

        root = Path(__file__).resolve().parents[2]
        wh_path = root / ".data" / "webhook" / "events.jsonl"
        reg.register(
            WebhookInboxConnector(
                connector_id="webhook-inbox",
                source_system="Webhook",
                path=str(wh_path),
            )
        )
    except Exception:
        pass
    try:
        from synapse.connectors.saas_stub import (
            CrmStubConnector,
            MetricsStubConnector,
            SlackStubConnector,
        )

        reg.register(CrmStubConnector())
        reg.register(SlackStubConnector())
        reg.register(MetricsStubConnector())
    except Exception:
        pass
    return reg
