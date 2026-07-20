"""
Multi-engine query lifecycle (ORG_WIDE §6).

1. Authenticate + policy context (Principal)
2. Parse intent → query class + budget class
3. Policy-scoped retrieval plan (IDF router)
4. Parallel fetch under budget: graph / doc trees / communities
5. Conflict-aware fusion
6. Structured answer + citations + confidence + gaps
7. Cache claim (store) + telemetry
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from synapse.budget import BudgetClass, BudgetLedger, budget_class_for_latency
from synapse.claim_cache import ClaimCache
from synapse.control_plane import ControlPlane, RouteDecision, RouteTarget
from synapse.engines import EngineRegistry
from synapse.metrics import METRICS
from synapse.models import Claim
from synapse.ontology import OntologyRegistry
from synapse.query import QueryResult, QueryService
from synapse.security import Principal
from synapse.store import SemanticStore


_ENTITY_HINT = re.compile(
    r"(?:what\s+is|status\s+of|tell\s+me\s+about|lookup|find)\s+([A-Za-z0-9][A-Za-z0-9 _./-]{1,60})",
    re.I,
)
_THEMATIC = re.compile(
    r"\b(theme|themes|global|across|overall|failure\s*modes?|top\s+failure|summary\s+of\s+all)\b",
    re.I,
)
_DOC = re.compile(
    r"\b(section|document|heading|page\s+\d|runbook|contract|pdf)\b",
    re.I,
)
_TEMPORAL = re.compile(
    r"\b(what\s+changed|history|over\s+time|timeline|valid_from|superseded)\b",
    re.I,
)


@dataclass
class IntentParse:
    intent: str
    entity_hint: Optional[str] = None
    budget_class: BudgetClass = BudgetClass.STANDARD
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "entity_hint": self.entity_hint,
            "budget_class": self.budget_class.value,
            "signals": list(self.signals),
        }


@dataclass
class OrchestratedAnswer:
    """Full multi-engine answer packet."""

    allowed: bool
    principal_id: str
    question: str
    intent: IntentParse
    route: Optional[RouteDecision]
    budget: BudgetLedger
    entity_result: Optional[QueryResult] = None
    engine_hits: dict[str, Any] = field(default_factory=dict)
    statement: str = ""
    confidence: float = 0.0
    gaps: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    claim: Optional[Claim] = None
    denial_reason: Optional[str] = None
    continue_hint: Optional[str] = None
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "principal_id": self.principal_id,
            "question": self.question,
            "intent": self.intent.to_dict(),
            "route": {
                "idf": self.route.idf,
                "route": self.route.route.value,
                "latency_class": self.route.latency_class.value,
                "reason": self.route.reason,
            }
            if self.route
            else None,
            "budget": self.budget.to_dict(),
            "entity": self.entity_result.to_dict() if self.entity_result else None,
            "engine_hits": self.engine_hits,
            "statement": self.statement,
            "confidence": self.confidence,
            "gaps": list(self.gaps),
            "citations": list(self.citations),
            "claim": self.claim.to_dict() if self.claim else None,
            "denial_reason": self.denial_reason,
            "continue_hint": self.continue_hint,
            "cache_hit": self.cache_hit,
        }


class QueryOrchestrator:
    """Budgeted multi-engine fan-out + fusion."""

    def __init__(
        self,
        store: SemanticStore,
        control_plane: ControlPlane,
        query: QueryService,
        engines: EngineRegistry,
        *,
        ontology: Optional[OntologyRegistry] = None,
        claim_cache: Optional[ClaimCache] = None,
        use_cache: bool = True,
    ) -> None:
        self.store = store
        self.control_plane = control_plane
        self.query = query
        self.engines = engines
        self.ontology = ontology or OntologyRegistry.default()
        self.claim_cache = claim_cache or ClaimCache()
        self.use_cache = use_cache

    def parse_intent(self, question: str, *, intent: Optional[str] = None) -> IntentParse:
        q = (question or "").strip()
        signals: list[str] = []
        entity_hint: Optional[str] = None

        m = _ENTITY_HINT.search(q)
        if m:
            entity_hint = m.group(1).strip().rstrip("?.!")
            signals.append("entity_phrase")

        # Exact entity name match against store
        if not entity_hint:
            ql = q.lower()
            for e in self.store.entities.values():
                name = (e.canonical_name or "").lower()
                if name and name in ql and len(name) >= 3:
                    entity_hint = e.canonical_name
                    signals.append("entity_store_match")
                    break

        if intent:
            chosen = intent
            signals.append(f"explicit:{intent}")
        elif _THEMATIC.search(q):
            chosen = "themes"
            signals.append("thematic")
        elif _DOC.search(q):
            chosen = "document"
            signals.append("document")
        elif _TEMPORAL.search(q):
            chosen = "temporal"
            signals.append("temporal")
        elif entity_hint:
            chosen = "entity_lookup"
            signals.append("entity_lookup")
        else:
            chosen = "hybrid"
            signals.append("hybrid_default")

        # Budget class from intent heuristics
        if chosen in {"themes", "global_summary", "failure_modes"}:
            bc = BudgetClass.DEEP
        elif chosen in {"document", "pageindex"}:
            bc = BudgetClass.STANDARD
        elif chosen == "entity_lookup":
            bc = BudgetClass.INTERACTIVE
        else:
            bc = BudgetClass.STANDARD

        return IntentParse(
            intent=chosen,
            entity_hint=entity_hint,
            budget_class=bc,
            signals=signals,
        )

    def ask(
        self,
        principal: Principal,
        question: str,
        *,
        intent: Optional[str] = None,
        entity_name: Optional[str] = None,
        budget_class: Optional[str] = None,
        as_of: Optional[str] = None,
        early_exit_confidence: float = 0.92,
    ) -> OrchestratedAnswer:
        with METRICS.timer("orchestrator.ask"):
            return self._ask(
                principal,
                question,
                intent=intent,
                entity_name=entity_name,
                budget_class=budget_class,
                as_of=as_of,
                early_exit_confidence=early_exit_confidence,
            )

    def _ask(
        self,
        principal: Principal,
        question: str,
        *,
        intent: Optional[str] = None,
        entity_name: Optional[str] = None,
        budget_class: Optional[str] = None,
        as_of: Optional[str] = None,
        early_exit_confidence: float = 0.92,
    ) -> OrchestratedAnswer:
        parsed = self.parse_intent(question, intent=intent)
        if entity_name:
            parsed.entity_hint = entity_name
            if "entity_explicit" not in parsed.signals:
                parsed.signals.append("entity_explicit")

        if budget_class:
            try:
                parsed.budget_class = BudgetClass(budget_class)
            except ValueError:
                pass

        # ACL-bound claim cache (H2/H3) — key includes as_of
        if self.use_cache:
            ckey = ClaimCache.make_key(
                question,
                principal_attrs=list(principal.attributes),
                intent=parsed.intent,
                entity=parsed.entity_hint or entity_name,
                budget_class=f"{parsed.budget_class.value}|as_of={as_of or ''}",
                data_revision=self.store.revision,
            )
            cached = self.claim_cache.get(ckey)
            if cached is not None:
                METRICS.inc("orchestrator.cache_hit")
                cached = dict(cached)
                cached["cache_hit"] = True
                # Rehydrate minimal OrchestratedAnswer from dict
                return self._from_cached_dict(cached, principal, question, parsed)
        else:
            ckey = None

        budget = BudgetLedger.open(parsed.budget_class)
        gaps: list[str] = []
        citations: list[str] = []
        engine_hits: dict[str, Any] = {}
        parts: list[str] = []
        confidences: list[float] = []
        entity_result: Optional[QueryResult] = None

        # IDF route using store-wide predicate density as cheap signal
        pred_count = len({f.predicate for f in self.store.facts.values() if f.valid_to is None})
        token_est = sum(
            int(ep.quality_signals.get("token_estimate", max(1, len((ep.payload_text or "").split()))))
            for ep in self.store.episodes.values()
        ) or 1
        route = self.control_plane.route(
            pred_count,
            max(token_est, 1),
            intent=parsed.intent,
        )
        # Align budget with router latency when not forced
        if not budget_class:
            parsed.budget_class = budget_class_for_latency(route.latency_class)
            budget = BudgetLedger.open(parsed.budget_class)

        # --- Engine fan-out under budget ---
        want_entity = parsed.intent in {
            "entity_lookup",
            "hybrid",
            "temporal",
        } or bool(parsed.entity_hint)
        want_themes = parsed.intent in {
            "themes",
            "global_summary",
            "failure_modes",
            "hybrid",
        } or route.route == RouteTarget.GRAPHRAG_COMMUNITY
        want_docs = parsed.intent in {
            "document",
            "doc",
            "pageindex",
            "hybrid",
        } or route.route == RouteTarget.PAGEINDEX_LEAF

        early_exit = False
        if want_entity and parsed.entity_hint and budget.allow_engine("semantic_query"):
            entity_result = self.query.ask(
                principal,
                entity_name=parsed.entity_hint,
                intent=parsed.intent if parsed.intent != "hybrid" else "entity_lookup",
                as_of=as_of,
            )
            engine_hits["semantic_query"] = {
                "allowed": entity_result.allowed,
                "denial_reason": entity_result.denial_reason,
                "as_of": as_of,
            }
            if entity_result.allowed and entity_result.claim:
                n = budget.charge_facts(len(entity_result.claim.supporting_fact_ids))
                parts.append(entity_result.claim.statement)
                confidences.append(entity_result.claim.confidence)
                citations.extend(entity_result.claim.raw_citations[:n])
                if entity_result.claim.uncertainty_notes:
                    gaps.extend(entity_result.claim.uncertainty_notes)
                open_c = []
                if entity_result.conflict_views:
                    open_c = [
                        v
                        for v in entity_result.conflict_views
                        if v.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT"
                    ]
                    if open_c:
                        gaps.append(
                            f"{len(open_c)} open scalar conflict(s) surfaced with validity weights."
                        )
                # Ontology annotation
                if entity_result.entity:
                    ot = self.ontology.map_entity_type(entity_result.entity.entity_type)
                    engine_hits["ontology"] = ot.to_dict()
                # Early-exit (H2): high-confidence entity answer, no open conflicts,
                # interactive budget — skip expensive engines
                if (
                    parsed.budget_class == BudgetClass.INTERACTIVE
                    and entity_result.claim.confidence >= early_exit_confidence
                    and not open_c
                    and parsed.intent in {"entity_lookup", "temporal"}
                ):
                    early_exit = True
                    engine_hits["early_exit"] = {
                        "reason": "confidence_threshold",
                        "confidence": entity_result.claim.confidence,
                        "threshold": early_exit_confidence,
                    }
                    METRICS.inc("orchestrator.early_exit")
                    want_themes = False
                    want_docs = False
            elif not entity_result.allowed:
                gaps.append(entity_result.denial_reason or "entity path denied")
        elif want_entity and not parsed.entity_hint:
            gaps.append("No entity resolved from question; entity path skipped.")

        if want_themes and budget.allow_engine("graphrag"):
            self.engines.rebuild_communities()
            theme = self.engines.route_query(question, intent="themes")
            hits = theme.get("hits") or []
            take = budget.charge_communities(len(hits))
            hits = hits[:take]
            engine_hits["graphrag"] = {
                "engine": theme.get("engine"),
                "hits": hits,
            }
            if hits:
                excerpts = [h.get("answer_excerpt") or h.get("community", {}).get("summary", "") for h in hits]
                parts.append("Global themes: " + " | ".join(e for e in excerpts if e)[:900])
                confidences.append(0.72)
            else:
                gaps.append("GraphRAG returned no community hits.")

        if want_docs and budget.allow_engine("pageindex"):
            if not self.engines._doc_trees:
                self.engines.index_episode_docs()
            doc = self.engines.route_query(question, intent="document")
            hits = doc.get("hits") or []
            take = budget.charge_doc_hits(len(hits))
            hits = hits[:take]
            engine_hits["pageindex"] = {
                "engine": doc.get("engine"),
                "hits": hits,
            }
            if hits:
                leaves = []
                for h in hits:
                    node = h.get("node") or {}
                    title = node.get("title") or "section"
                    preview = (node.get("preview") or "")[:120]
                    leaves.append(f"{title}: {preview}")
                    if h.get("doc_id"):
                        citations.append(str(h["doc_id"]))
                parts.append("Document sections: " + " || ".join(leaves)[:700])
                confidences.append(0.68)
            else:
                gaps.append("PageIndex found no matching document leaves.")

        # Fuse
        if not parts:
            statement = "Insufficient evidence under current policy/budget."
            conf = 0.2
            gaps.append("No engine produced answer content.")
            allowed = False
            denial = "no_evidence"
        else:
            statement = " ".join(parts)
            conf = sum(confidences) / len(confidences) if confidences else 0.5
            # Conflict honesty: lower confidence if open conflicts
            if entity_result and entity_result.conflict_views:
                open_n = sum(
                    1
                    for v in entity_result.conflict_views
                    if v.surface_policy == "SURFACED_AMBIGUOUS_CONFLICT"
                )
                if open_n:
                    conf *= 0.85
            allowed = True
            denial = None

        continue_hint = None
        if budget.exhausted:
            gaps.append("Budget exhausted; answer may be partial.")
            continue_hint = (
                "Re-run with budget_class=deep for fuller multi-engine synthesis."
            )

        claim = None
        if allowed:
            claim = Claim.create(
                statement,
                supporting_fact_ids=(
                    entity_result.claim.supporting_fact_ids
                    if entity_result and entity_result.claim
                    else []
                ),
                raw_citations=list(dict.fromkeys(citations)),
                confidence=conf,
                uncertainty_notes=list(dict.fromkeys(gaps)),
                policy_filtered=bool(
                    entity_result and entity_result.claim and entity_result.claim.policy_filtered
                ),
                conflict_ids=(
                    entity_result.claim.conflict_ids
                    if entity_result and entity_result.claim
                    else []
                ),
                route_used=route.route.value,
                idf=route.idf,
            )
            self.store.put_claim(claim)

        self.store.audit.record(
            "orchestrator.ask",
            actor=principal.principal_id,
            detail={
                "intent": parsed.intent,
                "budget_class": budget.budget_class.value,
                "exhausted": budget.exhausted,
                "engines": list(engine_hits.keys()),
                "allowed": allowed,
                "claim_id": claim.claim_id if claim else None,
            },
        )
        METRICS.inc("orchestrator.ask")
        if allowed:
            METRICS.inc("orchestrator.allowed")
        else:
            METRICS.inc("orchestrator.denied")
        if budget.exhausted:
            METRICS.inc("orchestrator.budget_exhausted")

        ans = OrchestratedAnswer(
            allowed=allowed,
            principal_id=principal.principal_id,
            question=question,
            intent=parsed,
            route=route,
            budget=budget,
            entity_result=entity_result,
            engine_hits=engine_hits,
            statement=statement,
            confidence=round(conf, 4),
            gaps=list(dict.fromkeys(gaps)),
            citations=list(dict.fromkeys(citations)),
            claim=claim,
            denial_reason=denial,
            continue_hint=continue_hint,
            cache_hit=False,
        )
        if self.use_cache and ckey and allowed:
            # Cache a lightweight dict (no full entity_result tree to keep small)
            light = ans.to_dict()
            light["entity"] = None  # drop bulky subtree
            self.claim_cache.put(
                ckey, light, principal_attrs=list(principal.attributes)
            )
        return ans

    def _from_cached_dict(
        self,
        data: dict[str, Any],
        principal: Principal,
        question: str,
        parsed: IntentParse,
    ) -> OrchestratedAnswer:
        from synapse.control_plane import LatencyClass

        route_d = data.get("route") or {}
        route = None
        if route_d:
            try:
                route = RouteDecision(
                    idf=float(route_d.get("idf") or 0),
                    route=RouteTarget(route_d.get("route") or RouteTarget.HYBRID_RETRIEVAL.value),
                    latency_class=LatencyClass(
                        route_d.get("latency_class") or LatencyClass.STANDARD.value
                    ),
                    reason=route_d.get("reason") or "cache",
                )
            except Exception:
                route = None
        budget_d = data.get("budget") or {}
        bc = budget_d.get("budget_class") or parsed.budget_class.value
        try:
            budget = BudgetLedger.open(bc)
        except Exception:
            budget = BudgetLedger.open(parsed.budget_class)
        budget.exhausted = bool(budget_d.get("exhausted"))
        return OrchestratedAnswer(
            allowed=bool(data.get("allowed")),
            principal_id=principal.principal_id,
            question=question,
            intent=parsed,
            route=route,
            budget=budget,
            entity_result=None,
            engine_hits=dict(data.get("engine_hits") or {}),
            statement=str(data.get("statement") or ""),
            confidence=float(data.get("confidence") or 0),
            gaps=list(data.get("gaps") or []),
            citations=list(data.get("citations") or []),
            claim=None,
            denial_reason=data.get("denial_reason"),
            continue_hint=data.get("continue_hint"),
            cache_hit=True,
        )
