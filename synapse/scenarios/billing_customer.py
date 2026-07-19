"""
Billing / CRM discrepancy vertical.

CRM reports Customer "Acme Corp" annual_revenue = 1,200,000
Billing reports Customer "ACME CORP" ARR = 950,000
Support notes mention the same customer under mixed casing.

Entity resolution should collapse to one Customer via normalized name.
Scalar conflict remains on annual_revenue until human pin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from synapse.adjudication import AdjudicationService
from synapse.control_plane import ControlPlane
from synapse.entity_resolution import EntityResolutionService
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.query import QueryService
from synapse.resolution import ConflictResolver
from synapse.security import Principal
from synapse.store import SemanticStore

DEFAULT_AUTHORITY = {
    "CRM-Salesforce": 0.75,
    "Billing-Zuora": 0.92,
    "Support-Zendesk": 0.60,
}

PAYLOADS = [
    {
        "source_system": "CRM-Salesforce",
        "payload": (
            "Customer: Acme Corp\n"
            "annual_revenue: 1200000\n"
            "account_status: active\n"
            "owner: AE-12"
        ),
        "acl_tags": ["domain:revenue", "clearance:l2"],
    },
    {
        "source_system": "Billing-Zuora",
        "payload": (
            "customer: ACME CORP\n"
            "ARR: 950000\n"
            "account_status: active\n"
            "currency: USD"
        ),
        "acl_tags": ["domain:revenue", "clearance:l2"],
    },
    {
        "source_system": "Support-Zendesk",
        "payload": (
            "Ticket #8821 for Customer Acme Corp — billing dispute on annual revenue figure."
        ),
        "acl_tags": ["domain:revenue", "clearance:l2", "channel:support"],
    },
]


@dataclass
class BillingScenarioBundle:
    store: SemanticStore
    control_plane: ControlPlane
    query: QueryService
    adjudication: AdjudicationService
    resolver: ConflictResolver
    er: EntityResolutionService
    entity_name: str = "Acme Corp"


class BillingCustomerScenario:
    def __init__(
        self,
        authority: dict[str, float] | None = None,
        *,
        store: Optional[SemanticStore] = None,
    ) -> None:
        self.store = store if store is not None else SemanticStore()
        self.control_plane = ControlPlane(authority or DEFAULT_AUTHORITY)
        self.ingestion = IngestionService(self.store, domain="revenue")
        self.extractor = RuleExtractor(self.store)
        self.resolver = ConflictResolver(self.store, self.control_plane)
        self.query = QueryService(self.store, self.control_plane, self.resolver)
        self.adjudication = AdjudicationService(self.store)
        self.er = EntityResolutionService(self.store)

    def seed(self, *, skip_if_populated: bool = False) -> BillingScenarioBundle:
        # Detect if this scenario already present
        if skip_if_populated and self.store.get_entity_by_name("Acme Corp"):
            return self._bundle()

        for item in PAYLOADS:
            result = self.ingestion.land(
                item["source_system"],
                item["payload"],
                item["acl_tags"],
            )
            self.extractor.extract_from_episode(result.episode, result.raw)

        return self._bundle()

    def _bundle(self) -> BillingScenarioBundle:
        return BillingScenarioBundle(
            store=self.store,
            control_plane=self.control_plane,
            query=self.query,
            adjudication=self.adjudication,
            resolver=self.resolver,
            er=self.er,
            entity_name="Acme Corp",
        )

    @staticmethod
    def principal_l2() -> Principal:
        return Principal.from_tags(
            "revops-l2",
            ["domain:revenue", "clearance:l2", "channel:support"],
        )

    @staticmethod
    def principal_l1() -> Principal:
        return Principal.from_tags("revops-l1", ["domain:revenue", "clearance:l1"])
