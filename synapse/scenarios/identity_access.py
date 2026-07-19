"""
Identity / access review vertical.

HR says employee is active.
IdP says account is deprovisioned.
ITSM ticket claims temporary re-enable.

Discrepancy on account_status for the same Person entity.
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
    "HR-Workday": 0.88,
    "IdP-Okta": 0.95,
    "ITSM-ServiceNow": 0.70,
}

PAYLOADS = [
    {
        "source_system": "HR-Workday",
        "payload": (
            "employee: Jane Doe\n"
            "employee_id: E-10442\n"
            "account_status: active\n"
            "department: Engineering"
        ),
        "acl_tags": ["domain:identity", "clearance:l2"],
    },
    {
        "source_system": "IdP-Okta",
        "payload": (
            "user: Jane Doe\n"
            "employee_id: E-10442\n"
            "account_status: deprovisioned\n"
            "last_login: 2026-01-02T10:00:00Z"
        ),
        "acl_tags": ["domain:identity", "clearance:l2"],
    },
    {
        "source_system": "ITSM-ServiceNow",
        "payload": (
            "Ticket INC-5501 for employee Jane Doe (E-10442): "
            "temporary re-enable requested; account_status: active pending manager approval."
        ),
        "acl_tags": ["domain:identity", "clearance:l2", "channel:itsm"],
    },
]


@dataclass
class IdentityScenarioBundle:
    store: SemanticStore
    control_plane: ControlPlane
    query: QueryService
    adjudication: AdjudicationService
    resolver: ConflictResolver
    er: EntityResolutionService
    entity_name: str = "Jane Doe"


class IdentityAccessScenario:
    def __init__(
        self,
        authority: dict[str, float] | None = None,
        *,
        store: Optional[SemanticStore] = None,
    ) -> None:
        self.store = store if store is not None else SemanticStore()
        self.control_plane = ControlPlane(authority or DEFAULT_AUTHORITY)
        self.ingestion = IngestionService(self.store, domain="identity")
        self.extractor = RuleExtractor(self.store)
        self.resolver = ConflictResolver(self.store, self.control_plane)
        self.query = QueryService(self.store, self.control_plane, self.resolver)
        self.adjudication = AdjudicationService(self.store)
        self.er = EntityResolutionService(self.store)

    def seed(self, *, skip_if_populated: bool = False) -> IdentityScenarioBundle:
        if skip_if_populated and self.store.get_entity_by_name("Jane Doe"):
            return self._bundle()

        for item in PAYLOADS:
            result = self.ingestion.land(
                item["source_system"],
                item["payload"],
                item["acl_tags"],
            )
            self.extractor.extract_from_episode(result.episode, result.raw)

        return self._bundle()

    def _bundle(self) -> IdentityScenarioBundle:
        return IdentityScenarioBundle(
            store=self.store,
            control_plane=self.control_plane,
            query=self.query,
            adjudication=self.adjudication,
            resolver=self.resolver,
            er=self.er,
            entity_name="Jane Doe",
        )

    @staticmethod
    def principal_l2() -> Principal:
        return Principal.from_tags(
            "iam-l2",
            ["domain:identity", "clearance:l2", "channel:itsm"],
        )

    @staticmethod
    def principal_l1() -> Principal:
        return Principal.from_tags("iam-l1", ["domain:identity", "clearance:l1"])
