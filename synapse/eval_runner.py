"""
Golden-set evaluation packs for schema-on-read answers.

Packs:
  - checkout  (infra incident)
  - billing   (CRM vs Billing revenue)
  - identity  (HR vs IdP account status)
  - all       (suite)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from synapse.graph_memory import LocalGraphitiStub, create_graph_adapter
from synapse.scenarios.billing_customer import BillingCustomerScenario
from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
from synapse.scenarios.identity_access import IdentityAccessScenario
from synapse.store import SemanticStore


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class EvalReport:
    scenario: str
    passed: int
    failed: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "passed": self.passed,
            "failed": self.failed,
            "ok": self.ok,
            "checks": [asdict(c) for c in self.checks],
        }


@dataclass
class SuiteReport:
    reports: list[EvalReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.reports)

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.reports)

    @property
    def failed(self) -> int:
        return sum(r.failed for r in self.reports)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": "all",
            "ok": self.ok,
            "passed": self.passed,
            "failed": self.failed,
            "scenarios": [r.to_dict() for r in self.reports],
        }


class _Checks:
    def __init__(self) -> None:
        self.items: list[CheckResult] = []

    def check(self, name: str, passed: bool, detail: str) -> None:
        self.items.append(CheckResult(name=name, passed=passed, detail=detail))

    def report(self, scenario: str) -> EvalReport:
        passed = sum(1 for c in self.items if c.passed)
        failed = sum(1 for c in self.items if not c.passed)
        return EvalReport(
            scenario=scenario, passed=passed, failed=failed, checks=list(self.items)
        )


def evaluate_checkout_incident(store: Optional[SemanticStore] = None) -> EvalReport:
    """Backward-compatible entry for checkout golden set."""
    return _eval_checkout(store)


def _eval_checkout(store: Optional[SemanticStore] = None) -> EvalReport:
    c = _Checks()
    scenario = CheckoutIncidentScenario(store=store or SemanticStore())
    bundle = scenario.seed(skip_if_populated=bool(store and store.raw_objects))

    c.check(
        "raw_count_3",
        len(bundle.store.raw_objects) >= 3,
        f"raw_objects={len(bundle.store.raw_objects)}",
    )
    entity = bundle.store.get_entity_by_name("checkout-service")
    c.check("entity_checkout_service", entity is not None, "entity present")

    if entity:
        versions = {
            str(f.object)
            for f in bundle.store.facts_for_entity(entity.entity_id, "current_version")
            if f.valid_to is None
        }
        c.check(
            "versions_include_both",
            "v2.4.0" in versions and "v2.4.1" in versions,
            f"versions={sorted(versions)}",
        )
    else:
        c.check("versions_include_both", False, "no entity")

    l1 = bundle.query.ask(
        CheckoutIncidentScenario.principal_l1(), entity_name="checkout-service"
    )
    l2 = bundle.query.ask(
        CheckoutIncidentScenario.principal_l2(), entity_name="checkout-service"
    )
    c.check("abac_l1_denied", l1.allowed is False, f"allowed={l1.allowed}")
    c.check("abac_l2_allowed", l2.allowed is True, f"allowed={l2.allowed}")

    version_view = None
    if l2.allowed:
        version_view = next(
            (v for v in l2.conflict_views if v.conflict.predicate == "current_version"),
            None,
        )
    c.check(
        "open_version_conflict",
        version_view is not None
        and version_view.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT",
        f"policy={version_view.surface_policy if version_view else None}",
    )
    if version_view and version_view.preferred:
        c.check(
            "k8s_preferred_by_wv",
            version_view.preferred.fact.source_system == "K8s-Cluster-Alpha",
            f"preferred={version_view.preferred.fact.source_system}",
        )
    else:
        c.check("k8s_preferred_by_wv", False, "no preferred")

    if version_view and version_view.preferred:
        k8s = next(
            (
                r
                for r in version_view.ranked
                if r.fact.source_system == "K8s-Cluster-Alpha"
            ),
            version_view.preferred,
        )
        bundle.adjudication.human_pin(
            version_view.conflict.conflict_id,
            chosen_fact_id=k8s.fact.fact_id,
            adjudicator="eval@synapse",
            reason="golden-set pin",
        )
        post = bundle.query.ask(
            CheckoutIncidentScenario.principal_l2(),
            entity_name="checkout-service",
        )
        stmt = post.claim.statement if post.claim else ""
        c.check("post_pin_human_marker", "HUMAN_PIN" in stmt, stmt[:120])
        c.check("post_pin_version_240", "v2.4.0" in stmt, stmt[:120])
        c.check(
            "post_pin_policy",
            any(v.surface_policy == "RESOLVED_HUMAN_PIN" for v in post.conflict_views),
            str([v.surface_policy for v in post.conflict_views]),
        )
    else:
        c.check("post_pin_human_marker", False, "skipped")
        c.check("post_pin_version_240", False, "skipped")
        c.check("post_pin_policy", False, "skipped")

    audit_types = {e.event_type for e in bundle.store.audit.events}
    c.check(
        "audit_has_query_events",
        "query.allowed" in audit_types or "query.denied" in audit_types,
        f"types={sorted(audit_types)}",
    )

    # Graph adapter smoke
    g = create_graph_adapter()
    snap = g.sync_from_store(bundle.store)
    c.check("graph_has_nodes", len(snap.nodes) >= 1, f"nodes={len(snap.nodes)}")
    c.check("graph_has_edges", len(snap.edges) >= 1, f"edges={len(snap.edges)}")

    return c.report("checkout")


def _eval_billing(store: Optional[SemanticStore] = None) -> EvalReport:
    c = _Checks()
    # Always use fresh store for isolated pack when store is None
    scenario = BillingCustomerScenario(store=store or SemanticStore())
    if store is None:
        bundle = scenario.seed()
    else:
        bundle = scenario.seed(skip_if_populated=bool(store.get_entity_by_name("Acme Corp")))

    c.check(
        "raw_at_least_3",
        len(bundle.store.raw_objects) >= 3,
        f"raw={len(bundle.store.raw_objects)}",
    )
    entity = bundle.store.get_entity_by_name("Acme Corp")
    c.check("entity_acme", entity is not None, "Acme Corp present")

    customers = [
        e
        for e in bundle.store.entities.values()
        if e.entity_type == "Customer" and e.status.value == "active"
    ]
    c.check("single_customer_er", len(customers) == 1, f"count={len(customers)}")

    if entity:
        revs = {
            str(f.object)
            for f in bundle.store.facts_for_entity(entity.entity_id, "annual_revenue")
            if f.valid_to is None
        }
        c.check(
            "revenue_both_values",
            any("1200000" in v for v in revs) and any("950000" in v for v in revs),
            f"revs={sorted(revs)}",
        )
    else:
        c.check("revenue_both_values", False, "no entity")

    l1 = bundle.query.ask(
        BillingCustomerScenario.principal_l1(), entity_name="Acme Corp"
    )
    l2 = bundle.query.ask(
        BillingCustomerScenario.principal_l2(), entity_name="Acme Corp"
    )
    c.check("abac_l1_denied", l1.allowed is False, f"allowed={l1.allowed}")
    c.check("abac_l2_allowed", l2.allowed is True, f"allowed={l2.allowed}")

    rev_view = None
    if l2.allowed:
        rev_view = next(
            (v for v in l2.conflict_views if v.conflict.predicate == "annual_revenue"),
            None,
        )
    c.check(
        "open_revenue_conflict",
        rev_view is not None
        and rev_view.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT",
        f"policy={rev_view.surface_policy if rev_view else None}",
    )
    if rev_view and rev_view.preferred:
        c.check(
            "billing_preferred_by_wv",
            rev_view.preferred.fact.source_system == "Billing-Zuora",
            f"preferred={rev_view.preferred.fact.source_system}",
        )
        # Pin billing figure
        chosen = next(
            (
                r
                for r in rev_view.ranked
                if r.fact.source_system == "Billing-Zuora"
            ),
            rev_view.preferred,
        )
        bundle.adjudication.human_pin(
            rev_view.conflict.conflict_id,
            chosen_fact_id=chosen.fact.fact_id,
            adjudicator="eval@synapse",
            reason="billing SoR for ARR",
        )
        post = bundle.query.ask(
            BillingCustomerScenario.principal_l2(), entity_name="Acme Corp"
        )
        stmt = post.claim.statement if post.claim else ""
        c.check("post_pin_human_marker", "HUMAN_PIN" in stmt, stmt[:120])
        c.check("post_pin_950k", "950000" in stmt, stmt[:120])
    else:
        c.check("billing_preferred_by_wv", False, "no preferred")
        c.check("post_pin_human_marker", False, "skipped")
        c.check("post_pin_950k", False, "skipped")

    return c.report("billing")


def _eval_identity(store: Optional[SemanticStore] = None) -> EvalReport:
    c = _Checks()
    scenario = IdentityAccessScenario(store=store or SemanticStore())
    if store is None:
        bundle = scenario.seed()
    else:
        bundle = scenario.seed(
            skip_if_populated=bool(store.get_entity_by_name("Jane Doe"))
        )

    c.check(
        "raw_at_least_3",
        len(bundle.store.raw_objects) >= 3,
        f"raw={len(bundle.store.raw_objects)}",
    )
    entity = bundle.store.get_entity_by_name("Jane Doe")
    c.check("entity_jane", entity is not None, "Jane Doe present")

    people = [
        e
        for e in bundle.store.entities.values()
        if e.entity_type == "Person" and e.status.value == "active"
    ]
    c.check("single_person_er", len(people) == 1, f"count={len(people)}")

    if entity:
        statuses = {
            str(f.object)
            for f in bundle.store.facts_for_entity(entity.entity_id, "account_status")
            if f.valid_to is None
        }
        c.check(
            "status_both_values",
            "active" in statuses and "deprovisioned" in statuses,
            f"statuses={sorted(statuses)}",
        )
    else:
        c.check("status_both_values", False, "no entity")

    l1 = bundle.query.ask(
        IdentityAccessScenario.principal_l1(), entity_name="Jane Doe"
    )
    l2 = bundle.query.ask(
        IdentityAccessScenario.principal_l2(), entity_name="Jane Doe"
    )
    c.check("abac_l1_denied", l1.allowed is False, f"allowed={l1.allowed}")
    c.check("abac_l2_allowed", l2.allowed is True, f"allowed={l2.allowed}")

    st_view = None
    if l2.allowed:
        st_view = next(
            (v for v in l2.conflict_views if v.conflict.predicate == "account_status"),
            None,
        )
    c.check(
        "open_status_conflict",
        st_view is not None
        and st_view.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT",
        f"policy={st_view.surface_policy if st_view else None}",
    )
    if st_view and st_view.preferred:
        c.check(
            "idp_preferred_by_wv",
            st_view.preferred.fact.source_system == "IdP-Okta",
            f"preferred={st_view.preferred.fact.source_system}",
        )
        chosen = next(
            (r for r in st_view.ranked if r.fact.source_system == "IdP-Okta"),
            st_view.preferred,
        )
        bundle.adjudication.human_pin(
            st_view.conflict.conflict_id,
            chosen_fact_id=chosen.fact.fact_id,
            adjudicator="eval@synapse",
            reason="IdP is access control plane of record",
        )
        post = bundle.query.ask(
            IdentityAccessScenario.principal_l2(), entity_name="Jane Doe"
        )
        stmt = post.claim.statement if post.claim else ""
        c.check("post_pin_human_marker", "HUMAN_PIN" in stmt, stmt[:120])
        c.check("post_pin_deprovisioned", "deprovisioned" in stmt, stmt[:120])
    else:
        c.check("idp_preferred_by_wv", False, "no preferred")
        c.check("post_pin_human_marker", False, "skipped")
        c.check("post_pin_deprovisioned", False, "skipped")

    g = LocalGraphitiStub()
    snap = g.sync_from_store(bundle.store)
    c.check("graph_has_person_edge", len(snap.edges) >= 1, f"edges={len(snap.edges)}")

    return c.report("identity")


def _eval_org(store: Optional[SemanticStore] = None) -> EvalReport:
    """Multi-domain discrepancy + orchestrator golden checks."""
    from synapse.engines import build_engine_registry
    from synapse.orchestrator import QueryOrchestrator
    from synapse.ontology import OntologyRegistry
    from synapse.scenarios.org_discrepancy import OrgDiscrepancyCorpus
    from synapse.security import Principal

    c = _Checks()
    corpus = OrgDiscrepancyCorpus(store=store or SemanticStore()).seed()
    st = corpus.store

    c.check(
        "multi_domain_raw",
        len(st.raw_objects) >= 10,
        f"raw={len(st.raw_objects)}",
    )
    c.check(
        "has_checkout",
        st.get_entity_by_name("checkout-service") is not None,
        "checkout-service",
    )
    c.check(
        "has_acme",
        st.get_entity_by_name("Acme Corp") is not None,
        "Acme Corp",
    )
    c.check(
        "has_jane",
        st.get_entity_by_name("Jane Doe") is not None,
        "Jane Doe",
    )
    c.check(
        "extra_payloads",
        corpus.extra_ingested >= 3,
        f"extra={corpus.extra_ingested}",
    )

    # Wire orchestrator like session
    from synapse.control_plane import ControlPlane
    from synapse.query import QueryService
    from synapse.resolution import ConflictResolver
    from synapse.scenarios.checkout_incident import DEFAULT_AUTHORITY

    auth = dict(DEFAULT_AUTHORITY)
    auth.update(
        {
            "CRM-Salesforce": 0.75,
            "Billing-Zuora": 0.92,
            "Support-Zendesk": 0.60,
            "HR-Workday": 0.88,
            "IdP-Okta": 0.95,
            "ITSM-ServiceNow": 0.70,
        }
    )
    cp = ControlPlane(auth)
    resolver = ConflictResolver(st, cp)
    query = QueryService(st, cp, resolver)
    engines = build_engine_registry(st)
    engines.rebuild_communities()
    engines.index_episode_docs()
    orch = QueryOrchestrator(
        st, cp, query, engines, ontology=OntologyRegistry.default()
    )

    principal = Principal.from_tags(
        "eval-org-l2",
        [
            "domain:sre",
            "domain:revenue",
            "domain:identity",
            "domain:support",
            "clearance:l2",
            "channel:incidents",
            "channel:support",
            "channel:itsm",
        ],
    )

    ans_entity = orch.ask(
        principal,
        "What is checkout-service status?",
        entity_name="checkout-service",
        budget_class="interactive",
    )
    c.check(
        "orch_entity_allowed",
        ans_entity.allowed,
        ans_entity.denial_reason or ans_entity.statement[:100],
    )
    c.check(
        "orch_entity_engine",
        "semantic_query" in ans_entity.engine_hits,
        str(list(ans_entity.engine_hits.keys())),
    )
    c.check(
        "orch_gaps_or_conflicts",
        bool(ans_entity.gaps) or bool(ans_entity.claim and ans_entity.claim.conflict_ids),
        f"gaps={ans_entity.gaps[:2]}",
    )

    ans_themes = orch.ask(
        principal,
        "What are global themes and failure modes?",
        intent="themes",
        budget_class="deep",
    )
    c.check(
        "orch_themes_hits",
        bool(ans_themes.engine_hits.get("graphrag", {}).get("hits")),
        str(ans_themes.engine_hits.get("graphrag")),
    )

    ans_doc = orch.ask(
        principal,
        "Find section about CrashLoopBackOff failure modes",
        intent="document",
        budget_class="standard",
    )
    c.check(
        "orch_doc_engine",
        "pageindex" in ans_doc.engine_hits,
        str(list(ans_doc.engine_hits.keys())),
    )

    # Budget exhaustion path: interactive with hybrid forces multi-engine attempt
    ans_budget = orch.ask(
        principal,
        "hybrid summary of themes and document sections for checkout",
        intent="hybrid",
        entity_name="checkout-service",
        budget_class="interactive",
    )
    c.check(
        "orch_budget_tracked",
        ans_budget.budget.spent_engines >= 1,
        ans_budget.budget.to_dict(),
    )

    ont = OntologyRegistry.default()
    c.check("ontology_l0", "Person" in ont.types and "Service" in ont.types, "L0 types")
    c.check("ontology_l1", "InfraService" in ont.types, "L1 packs")

    return c.report("org")


_PACKS: dict[str, Callable[[Optional[SemanticStore]], EvalReport]] = {
    "checkout": _eval_checkout,
    "billing": _eval_billing,
    "identity": _eval_identity,
    "org": _eval_org,
}


def evaluate_pack(
    name: str = "checkout",
    store: Optional[SemanticStore] = None,
) -> EvalReport | SuiteReport:
    """Run one pack or the full suite (`all`)."""
    key = (name or "checkout").lower()
    if key in ("all", "suite", "*"):
        return evaluate_all()
    if key not in _PACKS:
        raise ValueError(f"Unknown eval pack '{name}'. Choose: {sorted(_PACKS)}|all")
    # Isolated fresh stores per pack unless caller injects one
    return _PACKS[key](store)


def evaluate_all() -> SuiteReport:
    """Run all golden packs on isolated stores."""
    reports = [
        _PACKS[name](None) for name in ("checkout", "billing", "identity", "org")
    ]
    return SuiteReport(reports=reports)


def list_packs() -> list[str]:
    return sorted(_PACKS.keys()) + ["all"]
