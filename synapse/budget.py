"""
Query budget governor (org-wide design H12 / query lifecycle step 2–4).

Every ask has a cost/latency envelope. Exhaustion → partial answer + continue hint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

from synapse.control_plane import LatencyClass


class BudgetClass(str, Enum):
    INTERACTIVE = "interactive"  # seconds, cheap
    STANDARD = "standard"  # tens of seconds
    DEEP = "deep"  # minutes / async-capable


# Units are abstract "work units" for POC metering (not dollars)
_DEFAULTS: dict[BudgetClass, dict[str, int]] = {
    BudgetClass.INTERACTIVE: {
        "max_engines": 1,
        "max_facts": 40,
        "max_doc_hits": 2,
        "max_communities": 1,
        "max_tokens_estimate": 800,
    },
    BudgetClass.STANDARD: {
        "max_engines": 3,
        "max_facts": 120,
        "max_doc_hits": 5,
        "max_communities": 3,
        "max_tokens_estimate": 4000,
    },
    BudgetClass.DEEP: {
        "max_engines": 4,
        "max_facts": 400,
        "max_doc_hits": 12,
        "max_communities": 8,
        "max_tokens_estimate": 20000,
    },
}


def budget_class_for_latency(lc: LatencyClass | str) -> BudgetClass:
    name = lc.value if isinstance(lc, LatencyClass) else str(lc)
    if name == LatencyClass.INTERACTIVE.value:
        return BudgetClass.INTERACTIVE
    if name == LatencyClass.DEEP.value:
        return BudgetClass.DEEP
    return BudgetClass.STANDARD


@dataclass
class BudgetLedger:
    """Mutable spend tracker for one query."""

    budget_class: BudgetClass
    limits: dict[str, int] = field(default_factory=dict)
    spent_engines: int = 0
    spent_facts: int = 0
    spent_doc_hits: int = 0
    spent_communities: int = 0
    spent_tokens: int = 0
    exhausted: bool = False
    skip_reasons: list[str] = field(default_factory=list)

    @classmethod
    def open(
        cls,
        budget_class: BudgetClass | str = BudgetClass.STANDARD,
        *,
        overrides: Optional[dict[str, int]] = None,
    ) -> "BudgetLedger":
        bc = (
            budget_class
            if isinstance(budget_class, BudgetClass)
            else BudgetClass(str(budget_class))
        )
        limits = dict(_DEFAULTS[bc])
        if overrides:
            limits.update(overrides)
        return cls(budget_class=bc, limits=limits)

    def allow_engine(self, name: str) -> bool:
        if self.spent_engines >= self.limits["max_engines"]:
            self.exhausted = True
            self.skip_reasons.append(f"engine_cap:{name}")
            return False
        self.spent_engines += 1
        return True

    def charge_facts(self, n: int) -> int:
        room = max(0, self.limits["max_facts"] - self.spent_facts)
        take = min(n, room)
        self.spent_facts += take
        if take < n:
            self.exhausted = True
            self.skip_reasons.append("facts_cap")
        return take

    def charge_doc_hits(self, n: int) -> int:
        room = max(0, self.limits["max_doc_hits"] - self.spent_doc_hits)
        take = min(n, room)
        self.spent_doc_hits += take
        if take < n:
            self.exhausted = True
            self.skip_reasons.append("doc_hits_cap")
        return take

    def charge_communities(self, n: int) -> int:
        room = max(0, self.limits["max_communities"] - self.spent_communities)
        take = min(n, room)
        self.spent_communities += take
        if take < n:
            self.exhausted = True
            self.skip_reasons.append("communities_cap")
        return take

    def charge_tokens(self, n: int) -> int:
        room = max(0, self.limits["max_tokens_estimate"] - self.spent_tokens)
        take = min(n, room)
        self.spent_tokens += take
        if take < n:
            self.exhausted = True
            self.skip_reasons.append("tokens_cap")
        return take

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["budget_class"] = self.budget_class.value
        d["remaining"] = {
            k: max(0, self.limits[k] - getattr(self, f"spent_{k.replace('max_', '')}", 0))
            for k in self.limits
            if k.startswith("max_")
        }
        # Fix remaining keys more carefully
        d["remaining"] = {
            "engines": max(0, self.limits["max_engines"] - self.spent_engines),
            "facts": max(0, self.limits["max_facts"] - self.spent_facts),
            "doc_hits": max(0, self.limits["max_doc_hits"] - self.spent_doc_hits),
            "communities": max(0, self.limits["max_communities"] - self.spent_communities),
            "tokens": max(0, self.limits["max_tokens_estimate"] - self.spent_tokens),
        }
        return d
