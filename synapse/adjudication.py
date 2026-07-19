"""
Human adjudication write path.

Experts can pin, accept-plural, or reopen conflicts. Pins create higher-trust edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from synapse.models import Conflict, ConflictResolution, ConflictStatus
from synapse.store import SemanticStore


class AdjudicationError(ValueError):
    pass


@dataclass
class PinResult:
    conflict: Conflict
    previous_status: str


class AdjudicationService:
    """Human-in-the-loop write API for conflict records."""

    def __init__(self, store: SemanticStore) -> None:
        self.store = store

    def get_conflict(self, conflict_id: str) -> Conflict:
        conflict = self.store.conflicts.get(conflict_id)
        if conflict is None:
            raise AdjudicationError(f"Unknown conflict_id: {conflict_id}")
        return conflict

    def human_pin(
        self,
        conflict_id: str,
        *,
        chosen_fact_id: str,
        adjudicator: str,
        reason: str,
    ) -> PinResult:
        """
        Resolve a conflict by pinning one competing fact as canonical.

        Raises if fact is not in competing_fact_ids.
        """
        conflict = self.get_conflict(conflict_id)
        if chosen_fact_id not in conflict.competing_fact_ids:
            raise AdjudicationError(
                f"chosen_fact_id {chosen_fact_id} is not among competing facts"
            )
        if not adjudicator.strip():
            raise AdjudicationError("adjudicator is required")
        if not reason.strip():
            raise AdjudicationError("reason is required")

        previous = conflict.status.value
        conflict.status = ConflictStatus.RESOLVED
        conflict.resolution = ConflictResolution(
            method="human_pin",
            chosen_fact_id=chosen_fact_id,
            adjudicator=adjudicator.strip(),
            reason=reason.strip(),
        )
        self.store.put_conflict(conflict)
        self.store.audit.record(
            "adjudication.human_pin",
            actor=adjudicator.strip(),
            detail={
                "conflict_id": conflict.conflict_id,
                "chosen_fact_id": chosen_fact_id,
                "predicate": conflict.predicate,
                "previous_status": previous,
                "reason": reason.strip(),
            },
        )
        return PinResult(conflict=conflict, previous_status=previous)

    def accept_plural(
        self,
        conflict_id: str,
        *,
        adjudicator: str,
        reason: str,
    ) -> PinResult:
        """Mark multi-value truth as intentionally plural (e.g. regional names)."""
        conflict = self.get_conflict(conflict_id)
        previous = conflict.status.value
        conflict.status = ConflictStatus.ACCEPTED_PLURAL
        conflict.resolution = ConflictResolution(
            method="accepted_plural",
            chosen_fact_id=None,
            adjudicator=adjudicator.strip(),
            reason=reason.strip(),
        )
        self.store.put_conflict(conflict)
        self.store.audit.record(
            "adjudication.accept_plural",
            actor=adjudicator.strip(),
            detail={
                "conflict_id": conflict.conflict_id,
                "previous_status": previous,
                "reason": reason.strip(),
            },
        )
        return PinResult(conflict=conflict, previous_status=previous)

    def reopen(
        self,
        conflict_id: str,
        *,
        adjudicator: str,
        reason: str,
    ) -> PinResult:
        """Clear a prior resolution and reopen the conflict."""
        conflict = self.get_conflict(conflict_id)
        previous = conflict.status.value
        conflict.status = ConflictStatus.OPEN
        conflict.resolution = ConflictResolution(
            method="reopen",
            chosen_fact_id=None,
            adjudicator=adjudicator.strip(),
            reason=reason.strip(),
        )
        self.store.put_conflict(conflict)
        self.store.audit.record(
            "adjudication.reopen",
            actor=adjudicator.strip(),
            detail={
                "conflict_id": conflict.conflict_id,
                "previous_status": previous,
                "reason": reason.strip(),
            },
        )
        return PinResult(conflict=conflict, previous_status=previous)

    def list_open(self, entity_id: Optional[str] = None) -> list[Conflict]:
        out = [
            c
            for c in self.store.conflicts.values()
            if c.status == ConflictStatus.OPEN
        ]
        if entity_id:
            out = [c for c in out if c.subject_entity_id == entity_id]
        return out
