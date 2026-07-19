"""
Fact verifier stage (H1) — range/unit/format checks after extract.

Numeric / structured claims get confidence demotion or rejection notes
when they fail deterministic checks. Never invent values.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from synapse.models import Fact


_VERSION = re.compile(r"^v?\d+\.\d+(\.\d+)?([-+][A-Za-z0-9.]+)?$", re.I)
_MONEY = re.compile(r"^\$?[\d,]+(\.\d{1,2})?$")
_STATUS = frozenset(
    {
        "active",
        "inactive",
        "deprovisioned",
        "leave_of_absence",
        "suspended",
        "pending",
        "open",
        "closed",
        "success",
        "failed",
        "crashloopbackoff",
        "running",
        "healthy",
        "degraded",
    }
)


@dataclass
class VerifyResult:
    fact_id: str
    predicate: str
    ok: bool
    adjusted_confidence: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FactVerifier:
    """Deterministic checks keyed by predicate family."""

    REGULATED = frozenset(
        {"annual_revenue", "arr", "account_status", "current_version", "result"}
    )

    def verify_fact(self, fact: Fact) -> VerifyResult:
        notes: list[str] = []
        conf = float(fact.confidence)
        ok = True
        pred = (fact.predicate or "").lower()
        obj = fact.object
        s = str(obj).strip() if obj is not None else ""

        if pred in {"annual_revenue", "arr", "revenue"}:
            ok, conf, notes = self._money(s, conf, notes)
        elif pred in {"current_version", "deployed_version"}:
            ok, conf, notes = self._version(s, conf, notes)
        elif pred == "result":
            # Lab numeric or qualitative result — both valid
            try:
                float(s.replace(",", ""))
                ok, conf, notes = True, conf, notes
            except ValueError:
                if not s:
                    ok, conf, notes = False, min(conf, 0.25), notes + ["empty_lab_result"]
                else:
                    ok, conf, notes = True, conf, notes
        elif pred in {"result_status"}:
            ok = bool(s)
            if not ok:
                conf = min(conf, 0.25)
                notes.append("empty_result_status")
        elif pred in {"account_status", "deploy_status", "runtime_state", "ticket_status"}:
            ok, conf, notes = self._status(s, conf, notes)
        elif pred in {"mfa_enabled"}:
            if s.lower() not in {"true", "false", "1", "0", "yes", "no"}:
                ok = False
                conf = min(conf, 0.35)
                notes.append("mfa_enabled not boolean-like")
        else:
            if not s:
                ok = False
                conf = min(conf, 0.2)
                notes.append("empty object")

        if pred in self.REGULATED and conf < 0.5:
            notes.append("regulated_predicate_low_confidence")

        return VerifyResult(
            fact_id=fact.fact_id,
            predicate=fact.predicate,
            ok=ok,
            adjusted_confidence=round(max(0.0, min(1.0, conf)), 4),
            notes=notes,
        )

    def apply(self, fact: Fact) -> tuple[Fact, VerifyResult]:
        """Mutate confidence in-place when checks demote trust."""
        result = self.verify_fact(fact)
        if result.adjusted_confidence != fact.confidence:
            fact.confidence = result.adjusted_confidence
        return fact, result

    def verify_many(self, facts: list[Fact]) -> list[VerifyResult]:
        out = []
        for f in facts:
            _, r = self.apply(f)
            out.append(r)
        return out

    def _money(
        self, s: str, conf: float, notes: list[str]
    ) -> tuple[bool, float, list[str]]:
        if not s or not _MONEY.match(s.replace(" ", "")):
            notes.append("revenue_not_numeric")
            return False, min(conf, 0.3), notes
        try:
            n = float(s.replace("$", "").replace(",", ""))
        except ValueError:
            notes.append("revenue_parse_fail")
            return False, min(conf, 0.25), notes
        if n < 0:
            notes.append("revenue_negative")
            return False, min(conf, 0.2), notes
        if n > 1e12:
            notes.append("revenue_unreasonably_large")
            return True, min(conf, 0.55), notes
        return True, conf, notes

    def _version(
        self, s: str, conf: float, notes: list[str]
    ) -> tuple[bool, float, list[str]]:
        if not s or not _VERSION.match(s):
            notes.append("version_format_invalid")
            return False, min(conf, 0.35), notes
        return True, conf, notes

    def _status(
        self, s: str, conf: float, notes: list[str]
    ) -> tuple[bool, float, list[str]]:
        if not s:
            notes.append("status_empty")
            return False, min(conf, 0.2), notes
        if s.lower() not in _STATUS and len(s) > 40:
            notes.append("status_unusual")
            return True, min(conf, 0.6), notes
        return True, conf, notes
