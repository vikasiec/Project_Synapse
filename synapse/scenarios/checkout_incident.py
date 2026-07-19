"""
Infrastructure & Operational Incidents vertical.

GitHub CI says deploy v2.4.1 succeeded.
Kubernetes reports CrashLoopBackOff and pins v2.4.0.
Slack records a manual bypass to keep v2.4.0 active.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from synapse.adjudication import AdjudicationService
from synapse.control_plane import ControlPlane
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.query import QueryService
from synapse.resolution import ConflictResolver
from synapse.security import Principal
from synapse.store import SemanticStore

DEFAULT_AUTHORITY = {
    "GitHub-CI": 0.90,
    "K8s-Cluster-Alpha": 0.95,
    "Slack-Incident-Feed": 0.70,
}

PAYLOADS = [
    {
        "source_system": "GitHub-CI",
        "payload": (
            "BUILD SUCCESSFUL: checkout-service deployed image tag v2.4.1 automatically."
        ),
        "acl_tags": ["domain:sre", "clearance:l2"],
    },
    {
        "source_system": "K8s-Cluster-Alpha",
        "payload": (
            "ALERT: checkout-service-pod-xyz state changed to CrashLoopBackOff. "
            "Traffic pinned to local fallback v2.4.0."
        ),
        "acl_tags": ["domain:sre", "clearance:l2"],
    },
    {
        "source_system": "Slack-Incident-Feed",
        "payload": (
            "[Incident-104] Vikas Sharma: I have manually bypassed the target image "
            "to maintain v2.4.0 active on checkout-service."
        ),
        "acl_tags": ["domain:sre", "clearance:l2", "channel:incidents"],
    },
]


@dataclass
class ScenarioBundle:
    store: SemanticStore
    control_plane: ControlPlane
    query: QueryService
    adjudication: AdjudicationService
    resolver: ConflictResolver
    entity_name: str = "checkout-service"


class CheckoutIncidentScenario:
    """Load the standard discrepancy-laden incident into a store."""

    def __init__(
        self,
        authority: dict[str, float] | None = None,
        *,
        store: Optional[SemanticStore] = None,
    ) -> None:
        self.store = store if store is not None else SemanticStore()
        self.control_plane = ControlPlane(authority or DEFAULT_AUTHORITY)
        self.ingestion = IngestionService(self.store, domain="infra_ops")
        self.extractor = RuleExtractor(self.store)
        self.resolver = ConflictResolver(self.store, self.control_plane)
        self.query = QueryService(self.store, self.control_plane, self.resolver)
        self.adjudication = AdjudicationService(self.store)

    def seed(self, *, skip_if_populated: bool = False) -> ScenarioBundle:
        if skip_if_populated and self.store.raw_objects:
            return ScenarioBundle(
                store=self.store,
                control_plane=self.control_plane,
                query=self.query,
                adjudication=self.adjudication,
                resolver=self.resolver,
                entity_name="checkout-service",
            )
        for item in PAYLOADS:
            result = self.ingestion.land(
                item["source_system"],
                item["payload"],
                item["acl_tags"],
            )
            self.extractor.extract_from_episode(result.episode, result.raw)
        return ScenarioBundle(
            store=self.store,
            control_plane=self.control_plane,
            query=self.query,
            adjudication=self.adjudication,
            resolver=self.resolver,
            entity_name="checkout-service",
        )

    @staticmethod
    def principal_l1() -> Principal:
        return Principal.from_tags("user-l1", ["domain:sre", "clearance:l1"])

    @staticmethod
    def principal_l2() -> Principal:
        return Principal.from_tags(
            "user-l2",
            ["domain:sre", "clearance:l2", "channel:incidents"],
        )
