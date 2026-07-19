"""Query lifecycle: auth → route → filter → fuse → claim."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from synapse.control_plane import ControlPlane, RouteDecision
from synapse.metrics import METRICS
from synapse.models import Claim, Entity
from synapse.resolution import ConflictResolver, ConflictView
from synapse.security import Principal, filter_facts, filter_raw_objects
from synapse.store import SemanticStore
from synapse.temporal import TemporalService


@dataclass
class QueryResult:
    allowed: bool
    principal_id: str
    entity: Optional[Entity]
    route: Optional[RouteDecision]
    claim: Optional[Claim]
    conflict_views: list[ConflictView]
    denial_reason: Optional[str] = None
    as_of: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "principal_id": self.principal_id,
            "denial_reason": self.denial_reason,
            "as_of": self.as_of,
            "entity": self.entity.to_dict() if self.entity else None,
            "route": {
                "idf": self.route.idf,
                "route": self.route.route.value,
                "latency_class": self.route.latency_class.value,
                "reason": self.route.reason,
            }
            if self.route
            else None,
            "claim": self.claim.to_dict() if self.claim else None,
            "conflicts": [
                {
                    "surface_policy": v.surface_policy,
                    "conflict": v.conflict.to_dict(),
                    "ranked_facts": [
                        {
                            "fact_id": r.fact.fact_id,
                            "source_system": r.fact.source_system,
                            "object": r.fact.object,
                            "confidence": r.fact.confidence,
                            "validity_weight": round(r.validity_weight, 4),
                            "ontology_boost": round(
                                getattr(r, "ontology_boost", 0.0) or 0.0, 4
                            ),
                        }
                        for r in v.ranked
                    ],
                }
                for v in self.conflict_views
            ],
        }


class QueryService:
    def __init__(
        self,
        store: SemanticStore,
        control_plane: ControlPlane,
        resolver: ConflictResolver,
    ) -> None:
        self.store = store
        self.control_plane = control_plane
        self.resolver = resolver
        self.temporal = TemporalService(store)

    def ask(
        self,
        principal: Principal,
        *,
        entity_name: str,
        intent: str = "entity_lookup",
        as_of: Optional[str] = None,
    ) -> QueryResult:
        with METRICS.timer("query.ask"):
            return self._ask(
                principal, entity_name=entity_name, intent=intent, as_of=as_of
            )

    def _ask(
        self,
        principal: Principal,
        *,
        entity_name: str,
        intent: str = "entity_lookup",
        as_of: Optional[str] = None,
    ) -> QueryResult:
        entity = self.store.get_entity_by_name(entity_name)
        if entity is None:
            METRICS.inc("query.not_found")
            return QueryResult(
                allowed=False,
                principal_id=principal.principal_id,
                entity=None,
                route=None,
                claim=None,
                conflict_views=[],
                denial_reason=f"Entity not found: {entity_name}",
                as_of=as_of,
            )

        visible_raw = filter_raw_objects(principal, list(self.store.raw_objects.values()))
        if as_of:
            all_facts = self.temporal.facts_as_of(entity.entity_id, as_of)
            METRICS.inc("query.as_of")
        else:
            all_facts = self.store.facts_for_entity(entity.entity_id)
        visible_facts = filter_facts(principal, all_facts)

        if not visible_facts:
            self.store.audit.record(
                "query.denied",
                actor=principal.principal_id,
                detail={
                    "entity_name": entity_name,
                    "reason": "no_visible_facts",
                    "attributes": sorted(principal.attributes),
                    "as_of": as_of,
                },
            )
            METRICS.inc("query.denied")
            return QueryResult(
                allowed=False,
                principal_id=principal.principal_id,
                entity=entity,
                route=None,
                claim=None,
                conflict_views=[],
                denial_reason=(
                    "No facts visible under principal ABAC attributes"
                    + (f" at as_of={as_of}." if as_of else ".")
                ),
                as_of=as_of,
            )

        predicate_count = len({f.predicate for f in visible_facts})
        token_estimate = 0
        visible_raw_ids = {r.object_id for r in visible_raw}
        for ep in self.store.episodes.values():
            if any(rid in visible_raw_ids for rid in ep.raw_object_ids):
                token_estimate += int(ep.quality_signals.get("token_estimate", 0))
        token_estimate = max(token_estimate, 1)

        route = self.control_plane.route(
            predicate_count,
            token_estimate,
            intent=intent,
        )

        hidden_ids = {f.fact_id for f in all_facts} - {f.fact_id for f in visible_facts}
        as_of_ids = {f.fact_id for f in all_facts} if as_of else None
        conflict_views = self.resolver.detect_scalar_conflicts(entity.entity_id)

        filtered_views: list[ConflictView] = []
        for view in conflict_views:
            ranked = [r for r in view.ranked if r.fact.fact_id not in hidden_ids]
            if as_of_ids is not None:
                ranked = [r for r in ranked if r.fact.fact_id in as_of_ids]
            values = {str(r.fact.object) for r in ranked}
            # Keep resolved/plural views even if single visible value
            if len(values) > 1 or view.surface_policy in {
                "RESOLVED_HUMAN_PIN",
                "ACCEPTED_PLURAL",
            }:
                view.ranked = ranked
                if view.surface_policy == "RESOLVED_HUMAN_PIN" and view.conflict.resolution:
                    chosen = view.conflict.resolution.chosen_fact_id
                    view.preferred = next(
                        (r for r in ranked if r.fact.fact_id == chosen),
                        ranked[0] if ranked else None,
                    )
                elif view.surface_policy != "RESOLVED_HUMAN_PIN":
                    view.preferred = ranked[0] if ranked else None
                filtered_views.append(view)

        uncertainty: list[str] = []
        conflict_ids: list[str] = []
        statement_parts: list[str] = []
        confidences: list[float] = []

        # Prefer primary predicates for narrative
        primary_preds = (
            "current_version",
            "annual_revenue",
            "runtime_state",
            "account_status",
        )
        conflicted_preds = {v.conflict.predicate for v in filtered_views}
        if as_of:
            uncertainty.append(f"Point-in-time view as_of={as_of}.")

        for pred in primary_preds:
            view = next((v for v in filtered_views if v.conflict.predicate == pred), None)
            facts = [
                f
                for f in visible_facts
                if f.predicate == pred and (as_of or f.valid_to is None)
            ]
            if view and view.surface_policy == "RESOLVED_HUMAN_PIN":
                conflict_ids.append(view.conflict.conflict_id)
                pinned = view.preferred
                res = view.conflict.resolution
                if pinned:
                    statement_parts.append(
                        f"{entity.canonical_name} {pred}={pinned.fact.object} "
                        f"(HUMAN_PIN by {res.adjudicator if res else 'unknown'}: "
                        f"{res.reason if res else ''}; source={pinned.fact.source_system})."
                    )
                    confidences.append(min(1.0, pinned.fact.confidence + 0.05))
                uncertainty.append(
                    f"Conflict on {pred} resolved via human_pin; alternate sources retained."
                )
            elif view and view.surface_policy == "ACCEPTED_PLURAL":
                conflict_ids.append(view.conflict.conflict_id)
                vals = ", ".join(
                    f"{r.fact.object} ({r.fact.source_system})" for r in view.ranked
                )
                statement_parts.append(
                    f"{entity.canonical_name} {pred} accepted plural: {vals}."
                )
                confidences.append(0.8)
            elif view and view.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT":
                conflict_ids.append(view.conflict.conflict_id)
                uncertainty.append(
                    f"Open scalar conflict on {pred}; values returned with validity weights."
                )
                ranked_desc = ", ".join(
                    f"{r.fact.object} via {r.fact.source_system} (Wv={r.validity_weight:.3f})"
                    for r in view.ranked
                )
                statement_parts.append(
                    f"AMBIGUOUS {pred} for {entity.canonical_name}: {ranked_desc}."
                )
                confidences.append(
                    min(r.fact.confidence for r in view.ranked) * 0.7
                )
            elif facts:
                best = max(facts, key=lambda f: f.confidence)
                statement_parts.append(
                    f"{entity.canonical_name} {pred}={best.object} "
                    f"(source={best.source_system})."
                )
                confidences.append(best.confidence)

        for pred in (
            "deploy_status",
            "change_method",
            "related_incident",
            "deployed_version",
        ):
            if pred in conflicted_preds or pred in primary_preds:
                continue
            fs = [
                f
                for f in visible_facts
                if f.predicate == pred and (as_of or f.valid_to is None)
            ]
            if fs:
                f0 = fs[0]
                statement_parts.append(f"{pred}={f0.object} ({f0.source_system}).")

        if not statement_parts:
            # Generic, domain-blind fallback: the two loops above only know
            # a fixed set of infra/revenue/identity predicate names. Any
            # other domain's facts (healthcare, banking, ...) must still get
            # a real narrative, not a false "no facts" when facts exist.
            narrated_preds = (
                set(primary_preds)
                | {"deploy_status", "change_method", "related_incident", "deployed_version"}
                | conflicted_preds
            )
            generic_preds = sorted(
                {f.predicate for f in visible_facts if f.predicate not in narrated_preds}
            )
            for pred in generic_preds[:10]:
                facts = [
                    f
                    for f in visible_facts
                    if f.predicate == pred and (as_of or f.valid_to is None)
                ]
                if not facts:
                    continue
                best = max(facts, key=lambda f: f.confidence)
                statement_parts.append(
                    f"{entity.canonical_name} {pred}={best.object} "
                    f"(source={best.source_system})."
                )
                confidences.append(best.confidence)
            if len(generic_preds) > 10:
                uncertainty.append(
                    f"{len(generic_preds) - 10} additional fact(s) not narrated; "
                    "see supporting_fact_ids."
                )

        if not statement_parts:
            statement_parts.append(f"No primary facts visible for {entity.canonical_name}.")
            confidences.append(0.3)
            uncertainty.append("No primary facts.")

        conf = sum(confidences) / len(confidences) if confidences else 0.5

        claim = Claim.create(
            " ".join(statement_parts),
            supporting_fact_ids=[f.fact_id for f in visible_facts],
            raw_citations=[r.object_id for r in visible_raw],
            confidence=conf,
            uncertainty_notes=uncertainty,
            policy_filtered=len(hidden_ids) > 0,
            conflict_ids=conflict_ids,
            route_used=route.route.value,
            idf=route.idf,
        )
        self.store.put_claim(claim)
        self.store.audit.record(
            "query.allowed",
            actor=principal.principal_id,
            detail={
                "entity_name": entity_name,
                "claim_id": claim.claim_id,
                "route": route.route.value,
                "idf": route.idf,
                "as_of": as_of,
                "open_conflicts": len(
                    [v for v in filtered_views if v.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT"]
                ),
            },
        )
        METRICS.inc("query.allowed")
        if filtered_views:
            METRICS.inc("query.with_conflicts")

        return QueryResult(
            allowed=True,
            principal_id=principal.principal_id,
            entity=entity,
            route=route,
            claim=claim,
            conflict_views=filtered_views,
            as_of=as_of,
        )
