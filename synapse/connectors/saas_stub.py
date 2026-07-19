"""
SaaS stub connectors — stand-ins for real CRM / messaging CDC.

Each poll emits a small batch of realistic discrepancy-laden events, then
advances a watermark so repeat polls are idle (unless reset/force).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from synapse.connectors.base import ChangeEvent, Connector, ConnectorWatermark
from synapse.models import utc_now_iso


@dataclass
class _Batch:
    events: list[ChangeEvent]
    emitted: bool = False


def _ev(source: str, payload: str, acl: list[str], seq: int) -> ChangeEvent:
    return ChangeEvent(
        event_id=str(uuid4()),
        source_system=source,
        payload=payload,
        occurred_at=utc_now_iso(),
        acl_tags=list(acl),
        op="upsert",
        source_uri=f"stub://{source}/{seq}",
        meta={"seq": seq},
    )


@dataclass
class CrmStubConnector(Connector):
    """Simulated Salesforce-class CRM export / CDC."""

    connector_id: str = "crm-stub"
    source_system: str = "CRM-Salesforce"
    default_acl: list[str] = field(
        default_factory=lambda: ["domain:revenue", "clearance:l2"]
    )
    _batch: Optional[_Batch] = None

    def _ensure(self) -> _Batch:
        if self._batch is None:
            self._batch = _Batch(
                events=[
                    _ev(
                        self.source_system,
                        "customer: Northwind Traders\nannual_revenue: $2100000\nstatus: active",
                        self.default_acl,
                        0,
                    ),
                    _ev(
                        self.source_system,
                        "customer: Acme Corp\nannual_revenue: $1250000\nnote: Q2 forecast inflated",
                        self.default_acl,
                        1,
                    ),
                ]
            )
        return self._batch

    def poll(
        self, watermark: Optional[ConnectorWatermark] = None
    ) -> list[ChangeEvent]:
        b = self._ensure()
        if b.emitted:
            return []
        if watermark and watermark.position not in ("", "-1", None):
            # already drained
            b.emitted = True
            return []
        return list(b.events)

    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        b = self._ensure()
        b.emitted = True
        pos = str(events[-1].meta.get("seq", 0)) if events else "0"
        return ConnectorWatermark(connector_id=self.connector_id, position=pos)

    def reset(self) -> None:
        if self._batch:
            self._batch.emitted = False

    def describe(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "source_system": self.source_system,
            "type": "CrmStubConnector",
            "emitted": bool(self._batch and self._batch.emitted),
        }


@dataclass
class SlackStubConnector(Connector):
    """Simulated incident channel feed."""

    connector_id: str = "slack-stub"
    source_system: str = "Slack-Incident-Feed"
    default_acl: list[str] = field(
        default_factory=lambda: [
            "domain:sre",
            "clearance:l2",
            "channel:incidents",
        ]
    )
    _batch: Optional[_Batch] = None

    def _ensure(self) -> _Batch:
        if self._batch is None:
            self._batch = _Batch(
                events=[
                    _ev(
                        self.source_system,
                        (
                            "[Incident-220] oncall: payments-service canary looking bad; "
                            "holding checkout-service at v2.4.0"
                        ),
                        self.default_acl,
                        0,
                    ),
                    _ev(
                        self.source_system,
                        (
                            "[Incident-221] note: Jane Doe coordinating with support on "
                            "Acme Corp impact"
                        ),
                        self.default_acl + ["domain:identity", "domain:support"],
                        1,
                    ),
                ]
            )
        return self._batch

    def poll(
        self, watermark: Optional[ConnectorWatermark] = None
    ) -> list[ChangeEvent]:
        b = self._ensure()
        if b.emitted:
            return []
        if watermark and watermark.position not in ("", "-1", None):
            b.emitted = True
            return []
        return list(b.events)

    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        b = self._ensure()
        b.emitted = True
        pos = str(events[-1].meta.get("seq", 0)) if events else "0"
        return ConnectorWatermark(connector_id=self.connector_id, position=pos)

    def reset(self) -> None:
        if self._batch:
            self._batch.emitted = False

    def describe(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "source_system": self.source_system,
            "type": "SlackStubConnector",
            "emitted": bool(self._batch and self._batch.emitted),
        }


@dataclass
class MetricsStubConnector(Connector):
    """Simulated metrics / TSDB entity-aligned rollup."""

    connector_id: str = "metrics-stub"
    source_system: str = "Metrics-TSDB"
    default_acl: list[str] = field(
        default_factory=lambda: ["domain:sre", "clearance:l2"]
    )
    _batch: Optional[_Batch] = None

    def _ensure(self) -> _Batch:
        if self._batch is None:
            self._batch = _Batch(
                events=[
                    _ev(
                        self.source_system,
                        (
                            "service: checkout-service\n"
                            "runtime_state: degraded\n"
                            "error_rate: 0.12\n"
                            "note: elevated 5xx after canary"
                        ),
                        self.default_acl,
                        0,
                    ),
                ]
            )
        return self._batch

    def poll(
        self, watermark: Optional[ConnectorWatermark] = None
    ) -> list[ChangeEvent]:
        b = self._ensure()
        if b.emitted:
            return []
        if watermark and watermark.position not in ("", "-1", None):
            b.emitted = True
            return []
        return list(b.events)

    def advance(self, events: list[ChangeEvent]) -> ConnectorWatermark:
        b = self._ensure()
        b.emitted = True
        pos = str(events[-1].meta.get("seq", 0)) if events else "0"
        return ConnectorWatermark(connector_id=self.connector_id, position=pos)

    def describe(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "source_system": self.source_system,
            "type": "MetricsStubConnector",
            "emitted": bool(self._batch and self._batch.emitted),
        }
