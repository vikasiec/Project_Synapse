"""Control-plane math: IDF routing, validity weight, budget classes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional


class RouteTarget(str, Enum):
    LOCAL_CROSS_ENCODER = "LOCAL_CROSS_ENCODER_RERANKER"
    HYBRID_RETRIEVAL = "HYBRID_RETRIEVAL"
    PAGEINDEX_LEAF = "PAGEINDEX_VISUAL_TREE_ISOLATION"
    GRAPHRAG_COMMUNITY = "GRAPHRAG_COMMUNITY_ASYNC"


class LatencyClass(str, Enum):
    INTERACTIVE = "interactive"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass(frozen=True)
class RouteDecision:
    idf: float
    route: RouteTarget
    latency_class: LatencyClass
    reason: str


def parse_iso_z(ts: str) -> datetime:
    cleaned = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class ControlPlane:
    """
    Mathematical guardrails from the master architecture:

      IDF = evaluated_predicates / total_tokens
      Wv  = (Ar * e^(-λ * Δt)) + Lp
    """

    def __init__(
        self,
        ontology_authority: Mapping[str, float],
        *,
        lambda_decay: float = 0.01,
        high_idf: float = 0.75,
        low_idf: float = 0.25,
    ) -> None:
        self.ontology_authority = dict(ontology_authority)
        self.lambda_decay = lambda_decay
        self.high_idf = high_idf
        self.low_idf = low_idf

    def calculate_idf(self, evaluated_predicates: int, total_tokens: int) -> float:
        if total_tokens <= 0:
            return 0.0
        return float(evaluated_predicates) / float(total_tokens)

    def route(
        self,
        evaluated_predicates: int,
        total_tokens: int,
        *,
        intent: str = "entity_lookup",
    ) -> RouteDecision:
        idf = self.calculate_idf(evaluated_predicates, total_tokens)

        if intent in {"themes", "global_summary", "failure_modes"}:
            return RouteDecision(
                idf=idf,
                route=RouteTarget.GRAPHRAG_COMMUNITY,
                latency_class=LatencyClass.DEEP,
                reason="Global/thematic intent prefers community synthesis (async-capable).",
            )

        if idf >= self.high_idf:
            return RouteDecision(
                idf=idf,
                route=RouteTarget.LOCAL_CROSS_ENCODER,
                latency_class=LatencyClass.INTERACTIVE,
                reason="High IDF: dense structured facts; bypass long-context LLM.",
            )
        if idf >= self.low_idf:
            return RouteDecision(
                idf=idf,
                route=RouteTarget.HYBRID_RETRIEVAL,
                latency_class=LatencyClass.STANDARD,
                reason="Mid IDF: hybrid graph + selective synthesis.",
            )
        return RouteDecision(
            idf=idf,
            route=RouteTarget.PAGEINDEX_LEAF,
            latency_class=LatencyClass.STANDARD,
            reason="Low IDF: sparse payload; isolate via structural/leaf retrieval.",
        )

    def validity_weight(
        self,
        source_system: str,
        lineage_proximity: float,
        ingest_timestamp: str,
        *,
        now: Optional[datetime] = None,
        lambda_decay: Optional[float] = None,
    ) -> float:
        """Wv = (Ar * e^(-λ * Δt_minutes)) + Lp"""
        a_r = float(self.ontology_authority.get(source_system, 0.5))
        lp = float(lineage_proximity)
        lam = self.lambda_decay if lambda_decay is None else lambda_decay

        now_dt = now or datetime.now(timezone.utc)
        ingest_dt = parse_iso_z(ingest_timestamp)
        delta_minutes = max(0.0, (now_dt - ingest_dt).total_seconds() / 60.0)
        temporal_decay = math.exp(-lam * delta_minutes)
        return float((a_r * temporal_decay) + lp)

    def authority_rank(self, source_system: str) -> float:
        return float(self.ontology_authority.get(source_system, 0.5))
