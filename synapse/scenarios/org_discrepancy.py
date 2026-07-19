"""
Multi-domain discrepancy corpus — org-wide realism POC.

Seeds infra + revenue + identity into one store and adds cross-domain
nasty payloads (same human mentioned in incident + IdP + support; same
customer tied to service impact).

Not a full sim of petabyte org data — a *nasty small corpus* that proves
discrepancy + multi-domain ABAC + multi-engine routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from synapse.scenarios.billing_customer import BillingCustomerScenario
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.scenarios.identity_access import IdentityAccessScenario
from synapse.store import SemanticStore


# Extra cross-domain / drift / contradiction payloads
EXTRA_PAYLOADS: list[dict[str, Any]] = [
    {
        "source_system": "Support-Zendesk",
        "domain": "support",
        "payload": (
            "# Support Runbook — Checkout Impact\n"
            "## Customer Impact\n"
            "Acme Corp reports checkout failures since canary.\n"
            "## Failure Modes\n"
            "CrashLoopBackOff on checkout-service after v2.4.1.\n"
            "## Owner\n"
            "Escalate to Jane Doe (IdP active) and on-call SRE.\n"
        ),
        "acl_tags": ["domain:support", "domain:sre", "domain:revenue", "clearance:l2", "channel:support"],
    },
    {
        "source_system": "ITSM-ServiceNow",
        "domain": "support",
        "payload": (
            "TICKET INC-9001: checkout-service degradation. "
            "Related customer: Acme Corp. Assigned person: Jane Doe. "
            "Status=open priority=high."
        ),
        "acl_tags": ["domain:support", "domain:identity", "domain:sre", "clearance:l2", "channel:itsm"],
    },
    {
        "source_system": "CRM-Salesforce",
        "domain": "revenue",
        "payload": (
            "Customer Acme Corp annual_revenue=$12.5M (Q2 forecast). "
            "Note: Billing system shows different ARR — discrepancy open."
        ),
        "acl_tags": ["domain:revenue", "clearance:l2"],
    },
    {
        "source_system": "K8s-Cluster-Alpha",
        "domain": "infra_ops",
        "payload": (
            "# Deploy Timeline\n"
            "## Attempt v2.4.1\n"
            "Canary 5% — error rate spike.\n"
            "## Rollback\n"
            "Pinned checkout-service to v2.4.0 CrashLoopBackOff mitigated.\n"
        ),
        "acl_tags": ["domain:sre", "clearance:l2"],
    },
    {
        "source_system": "IdP-Okta",
        "domain": "identity",
        "payload": (
            "Person Jane Doe account_status=active mfa_enabled=true. "
            "Last login during INC-9001 window."
        ),
        "acl_tags": ["domain:identity", "clearance:l2"],
    },
    {
        "source_system": "HR-Workday",
        "domain": "identity",
        "payload": (
            "Person Jane Doe account_status=leave_of_absence per HR export "
            "(stale feed suspected vs IdP)."
        ),
        "acl_tags": ["domain:identity", "clearance:l2"],
    },
]


@dataclass
class OrgCorpusBundle:
    store: SemanticStore
    entity_names: list[str]
    domains: list[str]
    extra_ingested: int


class OrgDiscrepancyCorpus:
    """Compose all three scenario packs + cross-domain extras."""

    def __init__(self, store: Optional[SemanticStore] = None) -> None:
        self.store = store if store is not None else SemanticStore()

    def seed(self, *, skip_if_populated: bool = False) -> OrgCorpusBundle:
        if skip_if_populated and len(self.store.entities) >= 3:
            return OrgCorpusBundle(
                store=self.store,
                entity_names=sorted(
                    e.canonical_name or e.entity_id
                    for e in self.store.entities.values()
                    if e.status.value == "active"
                ),
                domains=["infra_ops", "revenue", "identity", "support"],
                extra_ingested=0,
            )

        CheckoutIncidentScenario(store=self.store).seed(skip_if_populated=False)
        BillingCustomerScenario(store=self.store).seed(skip_if_populated=False)
        IdentityAccessScenario(store=self.store).seed(skip_if_populated=False)

        from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
        from synapse.ingestion import IngestionService

        # Offline residual only — do not burn free-tier Gemini while seeding corpora
        dual = DualPathExtractor(
            self.store,
            residual=HeuristicResidualExtractor(),
            enable_residual=True,
        )
        extra = 0
        for row in EXTRA_PAYLOADS:
            domain = row.get("domain", "infra_ops")
            ing = IngestionService(self.store, domain=domain)
            result = ing.land(
                row["source_system"],
                row["payload"],
                list(row["acl_tags"]),
                actor="corpus:org_discrepancy",
            )
            if result.deduplicated or result.dropped:
                continue
            dual.extract(result.episode, result.raw)
            extra += 1

        names = sorted(
            {
                e.canonical_name or e.entity_id
                for e in self.store.entities.values()
                if e.status.value == "active" and e.canonical_name
            }
        )
        return OrgCorpusBundle(
            store=self.store,
            entity_names=names,
            domains=["infra_ops", "revenue", "identity", "support"],
            extra_ingested=extra,
        )
