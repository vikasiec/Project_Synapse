"""
Optional write-back / activation bus (H15).

Synapse is read-mostly. High-risk actions require human approval.
Never silently mutate systems of record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

from synapse.models import new_id, utc_now_iso
from synapse.store import SemanticStore


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed_sim"  # POC never hits real SaaS
    CANCELLED = "cancelled"


@dataclass
class ActionProposal:
    action_id: str
    action_type: str  # create_ticket | update_crm | notify
    payload: dict[str, Any]
    risk: str  # low | medium | high
    status: ActionStatus
    proposed_by: str
    proposed_at: str
    approved_by: Optional[str] = None
    decided_at: Optional[str] = None
    reason: Optional[str] = None
    execution_result: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class ActionBus:
    """In-store action queue with mandatory approval for high risk."""

    def __init__(self, store: SemanticStore) -> None:
        self.store = store
        # Side bag on store via audit + local dict
        self._actions: dict[str, ActionProposal] = {}

    def propose(
        self,
        action_type: str,
        payload: dict[str, Any],
        *,
        proposed_by: str,
        risk: str = "high",
    ) -> ActionProposal:
        a = ActionProposal(
            action_id=new_id(),
            action_type=action_type,
            payload=dict(payload),
            risk=risk.lower(),
            status=ActionStatus.PROPOSED,
            proposed_by=proposed_by,
            proposed_at=utc_now_iso(),
        )
        # Auto-approve only explicit low risk
        if a.risk == "low":
            a.status = ActionStatus.APPROVED
            a.approved_by = "policy:auto_low_risk"
            a.decided_at = utc_now_iso()
            a.reason = "auto-approved low risk"
        self._actions[a.action_id] = a
        self.store.audit.record(
            "action.proposed",
            actor=proposed_by,
            detail=a.to_dict(),
        )
        return a

    def approve(
        self,
        action_id: str,
        *,
        by: str,
        reason: str,
    ) -> ActionProposal:
        a = self._require(action_id)
        if a.status not in {ActionStatus.PROPOSED, ActionStatus.APPROVED}:
            raise ValueError(f"Cannot approve action in status {a.status.value}")
        a.status = ActionStatus.APPROVED
        a.approved_by = by
        a.decided_at = utc_now_iso()
        a.reason = reason
        self.store.audit.record(
            "action.approved", actor=by, detail={"action_id": action_id, "reason": reason}
        )
        return a

    def reject(
        self,
        action_id: str,
        *,
        by: str,
        reason: str,
    ) -> ActionProposal:
        a = self._require(action_id)
        a.status = ActionStatus.REJECTED
        a.approved_by = by
        a.decided_at = utc_now_iso()
        a.reason = reason
        self.store.audit.record(
            "action.rejected", actor=by, detail={"action_id": action_id, "reason": reason}
        )
        return a

    def execute(self, action_id: str, *, by: str = "system:action_bus") -> ActionProposal:
        """POC execute = simulated only; never calls external SaaS."""
        a = self._require(action_id)
        if a.status != ActionStatus.APPROVED:
            raise ValueError("Action must be approved before execute")
        a.status = ActionStatus.EXECUTED
        a.execution_result = {
            "mode": "simulated",
            "message": (
                f"Simulated {a.action_type}; real write-back disabled in POC "
                "(never silent SoR mutation)."
            ),
            "payload_echo": a.payload,
            "executed_at": utc_now_iso(),
            "executed_by": by,
        }
        self.store.audit.record(
            "action.executed_sim",
            actor=by,
            detail={"action_id": action_id, "action_type": a.action_type},
        )
        return a

    def list(self, *, status: Optional[str] = None) -> list[dict[str, Any]]:
        rows = [a.to_dict() for a in self._actions.values()]
        if status:
            rows = [r for r in rows if r["status"] == status]
        return rows

    def _require(self, action_id: str) -> ActionProposal:
        a = self._actions.get(action_id)
        if not a:
            raise KeyError(f"Unknown action_id: {action_id}")
        return a
