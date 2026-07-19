"""
Cost & latency envelopes by query class (H3/H12) — spreadsheet-level POC model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from synapse.budget import BudgetClass


@dataclass(frozen=True)
class CostEnvelope:
    budget_class: str
    latency_target: str
    max_tokens_est: int
    max_llm_calls: int
    max_engines: int
    usd_per_1k_queries_free_tier: float  # 0 on free tier if within quota
    usd_per_1k_queries_paid_est: float
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ENVELOPES: dict[str, CostEnvelope] = {
    BudgetClass.INTERACTIVE.value: CostEnvelope(
        budget_class="interactive",
        latency_target="< 3s local / < 8s with graph read",
        max_tokens_est=800,
        max_llm_calls=0,  # prefer no LLM on hot path
        max_engines=1,
        usd_per_1k_queries_free_tier=0.0,
        usd_per_1k_queries_paid_est=0.05,
        notes="Entity card / high-IDF path; rules + store only.",
    ),
    BudgetClass.STANDARD.value: CostEnvelope(
        budget_class="standard",
        latency_target="< 30s",
        max_tokens_est=4000,
        max_llm_calls=1,
        max_engines=3,
        usd_per_1k_queries_free_tier=0.0,
        usd_per_1k_queries_paid_est=0.80,
        notes="Hybrid entity + PageIndex; optional residual LLM.",
    ),
    BudgetClass.DEEP.value: CostEnvelope(
        budget_class="deep",
        latency_target="async-capable (minutes OK)",
        max_tokens_est=20000,
        max_llm_calls=5,
        max_engines=4,
        usd_per_1k_queries_free_tier=0.0,
        usd_per_1k_queries_paid_est=4.50,
        notes="Themes/GraphRAG + multi-engine fuse; Graphiti push separate budget.",
    ),
}


def estimate_query_cost(
    budget_class: str,
    *,
    qps: float = 1.0,
    hours_per_day: float = 8.0,
) -> dict[str, Any]:
    env = ENVELOPES.get(budget_class) or ENVELOPES["standard"]
    daily_q = qps * 3600 * hours_per_day
    return {
        "envelope": env.to_dict(),
        "assumptions": {
            "qps": qps,
            "hours_per_day": hours_per_day,
            "daily_queries": daily_q,
        },
        "daily_usd_free_tier_if_in_quota": 0.0,
        "daily_usd_paid_est": round(
            (daily_q / 1000.0) * env.usd_per_1k_queries_paid_est, 4
        ),
        "monthly_usd_paid_est": round(
            (daily_q / 1000.0) * env.usd_per_1k_queries_paid_est * 22, 2
        ),
    }


def describe_cost_model() -> dict[str, Any]:
    return {
        "envelopes": {k: v.to_dict() for k, v in ENVELOPES.items()},
        "policy": {
            "free_tier_throttle_rpm": 12,
            "free_tier_throttle_rpd": 900,
            "prefer_rules_over_llm": True,
            "graphiti_push_budget_separate": True,
        },
        "examples": {
            "interactive_10qps": estimate_query_cost("interactive", qps=10),
            "standard_1qps": estimate_query_cost("standard", qps=1),
            "deep_0.1qps": estimate_query_cost("deep", qps=0.1),
        },
    }
