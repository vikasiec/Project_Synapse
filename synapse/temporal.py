"""
Temporal supersession for same-source operational facts.

When the same source_system asserts the same predicate on the same entity
at a later valid_from, older facts get valid_to set (history retained).
Cross-source disagreements remain conflicts (not auto-resolved).
"""

from __future__ import annotations

from dataclasses import dataclass

from synapse.control_plane import parse_iso_z
from synapse.models import Fact
from synapse.store import SemanticStore


@dataclass
class SupersessionResult:
    closed: int  # facts that received valid_to


class TemporalService:
    def __init__(self, store: SemanticStore) -> None:
        self.store = store

    def apply_for_entity(self, entity_id: str) -> SupersessionResult:
        # Applies to every predicate, not a hardcoded infra/revenue-domain
        # whitelist (Active_File.md row 14, Codex review) -- a hardcoded
        # OPERATIONAL_PREDICATES set here meant temporal supersession never
        # applied to any healthcare/banking predicate (e.g. "result"),
        # letting the same patient's repeated lab result over time look
        # like an open cross-source conflict instead of a legitimate
        # updated value. The (predicate, source_system) grouping below is
        # what makes this safe: only the SAME source reporting the SAME
        # predicate again gets superseded -- two DIFFERENT sources
        # disagreeing on a predicate still correctly stay separate as an
        # open conflict, regardless of which predicate it is.
        facts = [f for f in self.store.facts.values() if f.subject_entity_id == entity_id]
        # Group by (predicate, source_system)
        groups: dict[tuple[str, str], list[Fact]] = {}
        for f in facts:
            groups.setdefault((f.predicate, f.source_system), []).append(f)

        closed = 0
        for (_pred, _src), group in groups.items():
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda f: parse_iso_z(f.valid_from))
            latest = ordered[-1]
            for older in ordered[:-1]:
                if older.valid_to is None:
                    older.valid_to = latest.valid_from
                    self.store.put_fact(older)
                    closed += 1

        if closed:
            self.store.audit.record(
                "temporal.supersession",
                actor="system:temporal",
                detail={"entity_id": entity_id, "facts_closed": closed},
            )
        return SupersessionResult(closed=closed)

    def current_facts(self, entity_id: str, predicate: str | None = None) -> list[Fact]:
        """Facts that are not temporally closed (valid_to is None)."""
        out = []
        for f in self.store.facts_for_entity(entity_id, predicate):
            if f.valid_to is None:
                out.append(f)
        return out

    def facts_as_of(
        self,
        entity_id: str,
        as_of: str,
        *,
        predicate: str | None = None,
    ) -> list[Fact]:
        """
        Facts valid at a point in time (H7 as_of).

        valid_from <= as_of AND (valid_to is None OR valid_to > as_of)
        """
        t = parse_iso_z(as_of)
        out: list[Fact] = []
        for f in self.store.facts_for_entity(entity_id, predicate):
            try:
                vf = parse_iso_z(f.valid_from)
            except Exception:
                continue
            if vf > t:
                continue
            if f.valid_to is not None:
                try:
                    vt = parse_iso_z(f.valid_to)
                except Exception:
                    continue
                if vt <= t:
                    continue
            out.append(f)
        return out

    def timeline(
        self,
        entity_id: str,
        *,
        predicate: str | None = None,
    ) -> list[dict]:
        """Ordered history for UI/CLI (valid_from ascending)."""
        facts = self.store.facts_for_entity(entity_id, predicate)
        facts = sorted(facts, key=lambda f: parse_iso_z(f.valid_from))
        return [
            {
                "fact_id": f.fact_id,
                "predicate": f.predicate,
                "object": f.object,
                "source_system": f.source_system,
                "valid_from": f.valid_from,
                "valid_to": f.valid_to,
                "confidence": f.confidence,
                "active": f.valid_to is None,
            }
            for f in facts
        ]
