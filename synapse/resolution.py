"""Conflict detection and validity-weight ranking (discrepancy is first-class)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from synapse.control_plane import ControlPlane
from synapse.models import Conflict, ConflictStatus, Fact
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore


@dataclass
class RankedFact:
    fact: Fact
    validity_weight: float
    lineage_proximity: float
    ontology_boost: float = 0.0


@dataclass
class ConflictView:
    conflict: Conflict
    ranked: list[RankedFact]
    preferred: Optional[RankedFact]
    surface_policy: str


class ConflictResolver:
    """
    Detects scalar clashes on (entity, predicate) and ranks competitors with Wv.
    Does not silently pick a winner for open conflicts — returns AMBIGUOUS surface.
    Respects human_pin / accepted_plural resolutions.

    H8: ontology_boost adds domain-overlap SoR preference on top of Ar·e^(-λΔt)+Lp.
    """

    def __init__(
        self,
        store: SemanticStore,
        control_plane: ControlPlane,
        *,
        ontology: Optional[OntologyRegistry] = None,
    ) -> None:
        self.store = store
        self.control_plane = control_plane
        self.ontology = ontology or OntologyRegistry.default()

    def _lineage_proximity(self, fact: Fact) -> float:
        return min(0.15, 0.03 * max(1, len(fact.evidence_refs)))

    def rank_fact(
        self,
        fact: Fact,
        *,
        entity_ontology_type: Optional[str] = None,
    ) -> RankedFact:
        ingest_ts = fact.valid_from
        if fact.evidence_refs:
            raw_id = fact.evidence_refs[0]
            raw = self.store.raw_objects.get(raw_id)
            if raw:
                ingest_ts = raw.ingested_at

        lp = self._lineage_proximity(fact)
        wv = self.control_plane.validity_weight(
            fact.source_system,
            lp,
            ingest_ts,
        )
        # Domain-overlap authority map (H8) — additive boost for preferred SoR
        o_boost = self.ontology.predicate_source_boost(
            fact.predicate, fact.source_system
        )
        # Soft demote predicates outside type scope (does not drop — surfaces still)
        if entity_ontology_type and not self.ontology.is_predicate_in_scope(
            entity_ontology_type, fact.predicate
        ):
            o_boost -= 0.03
        wv = float(wv) + o_boost
        return RankedFact(
            fact=fact,
            validity_weight=wv,
            lineage_proximity=lp,
            ontology_boost=o_boost,
        )

    def _find_conflict(self, entity_id: str, predicate: str) -> Optional[Conflict]:
        for c in self.store.conflicts.values():
            if c.subject_entity_id == entity_id and c.predicate == predicate:
                return c
        return None

    def detect_scalar_conflicts(self, entity_id: str) -> list[ConflictView]:
        # Only temporally current facts (valid_to is None) participate in clashes
        facts = [
            f
            for f in self.store.facts_for_entity(entity_id)
            if f.valid_to is None
        ]
        ent = self.store.entities.get(entity_id)
        ont_type = ent.ontology_type if ent else None
        by_pred: dict[str, list[Fact]] = {}
        for f in facts:
            by_pred.setdefault(f.predicate, []).append(f)

        views: list[ConflictView] = []
        for predicate, group in by_pred.items():
            values = {str(f.object) for f in group}
            if len(values) <= 1:
                continue

            ranked = sorted(
                (
                    self.rank_fact(f, entity_ontology_type=ont_type)
                    for f in group
                ),
                key=lambda r: r.validity_weight,
                reverse=True,
            )

            existing = self._find_conflict(entity_id, predicate)

            # Respect prior human adjudication — do not re-open
            if existing and existing.status == ConflictStatus.RESOLVED:
                preferred = None
                if existing.resolution and existing.resolution.chosen_fact_id:
                    for r in ranked:
                        if r.fact.fact_id == existing.resolution.chosen_fact_id:
                            preferred = r
                            break
                existing.competing_fact_ids = [f.fact_id for f in group]
                self.store.put_conflict(existing)
                views.append(
                    ConflictView(
                        conflict=existing,
                        ranked=ranked,
                        preferred=preferred or (ranked[0] if ranked else None),
                        surface_policy="RESOLVED_HUMAN_PIN",
                    )
                )
                continue

            if existing and existing.status == ConflictStatus.ACCEPTED_PLURAL:
                existing.competing_fact_ids = [f.fact_id for f in group]
                self.store.put_conflict(existing)
                views.append(
                    ConflictView(
                        conflict=existing,
                        ranked=ranked,
                        preferred=None,
                        surface_policy="ACCEPTED_PLURAL",
                    )
                )
                continue

            if existing is None:
                conflict = Conflict.open(
                    subject_entity_id=entity_id,
                    predicate=predicate,
                    competing_fact_ids=[f.fact_id for f in group],
                )
                self.store.put_conflict(conflict)
            else:
                conflict = existing
                conflict.competing_fact_ids = [f.fact_id for f in group]
                conflict.status = ConflictStatus.OPEN
                self.store.put_conflict(conflict)

            views.append(
                ConflictView(
                    conflict=conflict,
                    ranked=ranked,
                    preferred=ranked[0] if ranked else None,
                    surface_policy="SURFACED_AMBIGUOUS_CONFLICT",
                )
            )
        return views
