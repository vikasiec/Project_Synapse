"""
Poll connectors → land into semantic store → dual-path extract.

This is the continuous ingest control loop for Phase 2 (single-shot poll for now).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

from synapse.connectors.base import ChangeEvent, Connector
from synapse.connectors.registry import ConnectorRegistry
from synapse.dual_path import DualPathExtractor
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.metrics import METRICS
from synapse.store import SemanticStore

ExtractorLike = Union[RuleExtractor, DualPathExtractor, Any]


@dataclass
class PollResult:
    connector_id: str
    events: int
    landed: int
    deduplicated: int
    extracted: int
    residual_facts: int = 0
    watermark: Optional[str] = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "events": self.events,
            "landed": self.landed,
            "deduplicated": self.deduplicated,
            "extracted": self.extracted,
            "residual_facts": self.residual_facts,
            "watermark": self.watermark,
            "errors": self.errors,
        }


class ConnectorRunner:
    def __init__(
        self,
        store: SemanticStore,
        registry: ConnectorRegistry,
        *,
        ingestion: Optional[IngestionService] = None,
        extractor: Optional[ExtractorLike] = None,
        dual_path: Optional[DualPathExtractor] = None,
        domain: str = "infra_ops",
        use_dual_path: bool = True,
    ) -> None:
        self.store = store
        self.registry = registry
        self.ingestion = ingestion or IngestionService(store, domain=domain)
        # Prefer dual-path (rules + residual) for POC
        if dual_path is not None:
            self.dual_path = dual_path
        elif use_dual_path:
            self.dual_path = DualPathExtractor(store)
        else:
            self.dual_path = None
        self.extractor = extractor or RuleExtractor(store)

    def poll_one(self, connector_id: str) -> PollResult:
        connector = self.registry.get(connector_id)
        return self._poll_connector(connector)

    def poll_all(self) -> list[PollResult]:
        return [self._poll_connector(c) for c in self.registry.connectors.values()]

    def _extract(self, episode, raw) -> tuple[bool, int]:
        """Returns (extracted_entity, residual_fact_count)."""
        if self.dual_path is not None:
            out = self.dual_path.extract(episode, raw)
            return bool(out.entity_name), len(out.residual_facts)
        ext = self.extractor.extract_from_episode(episode, raw)
        return ext is not None, 0

    def _poll_connector(self, connector: Connector) -> PollResult:
        with METRICS.timer("connector.poll"):
            wm = self.registry.watermark(connector.connector_id)
            events = connector.poll(wm)
            result = PollResult(
                connector_id=connector.connector_id,
                events=len(events),
                landed=0,
                deduplicated=0,
                extracted=0,
                residual_facts=0,
            )
            processed: list[ChangeEvent] = []
            for ev in events:
                if ev.op == "delete":
                    self.store.audit.record(
                        "connector.delete_skipped",
                        actor=f"connector:{connector.connector_id}",
                        detail={"event_id": ev.event_id},
                    )
                    processed.append(ev)
                    continue
                try:
                    ing = self.ingestion.land(
                        ev.source_system,
                        ev.payload,
                        ev.acl_tags,
                        source_uri=ev.source_uri,
                        actor=f"connector:{connector.connector_id}",
                    )
                    if getattr(ing, "dropped", False):
                        processed.append(ev)
                        continue
                    if ing.deduplicated:
                        result.deduplicated += 1
                    else:
                        result.landed += 1
                    extracted, residual_n = self._extract(ing.episode, ing.raw)
                    if extracted:
                        result.extracted += 1
                    result.residual_facts += residual_n
                    processed.append(ev)
                except Exception as exc:
                    result.errors.append(f"{ev.event_id}: {exc}")

            if processed:
                new_wm = connector.advance(processed)
                self.registry.set_watermark(new_wm)
                result.watermark = new_wm.position
            elif wm:
                result.watermark = wm.position

            METRICS.inc("connector.events", result.events)
            METRICS.inc("connector.landed", result.landed)
            self.store.audit.record(
                "connector.poll",
                actor=f"connector:{connector.connector_id}",
                detail=result.to_dict(),
            )
            return result
