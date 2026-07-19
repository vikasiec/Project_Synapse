"""
Capability matrix — doability scoreboard mapped to live POC code (ORG_WIDE §8.2).
"""

from __future__ import annotations

from typing import Any

from synapse.integrations.availability import engine_availability


def capability_matrix() -> dict[str, Any]:
    eng = engine_availability()
    return {
        "version": "0.17",
        "engines": eng,
        "capabilities": [
            {
                "name": "Multi-format landing + prep",
                "feasibility": "High",
                "status": "pass",
                "owner": "operators + DataJuicerAdapter + connectors",
            },
            {
                "name": "Continuous temporal graph",
                "feasibility": "Medium-High",
                "status": "pass" if eng["graphiti"]["importable"] else "degraded",
                "owner": "graphiti_ops + Neo4j",
            },
            {
                "name": "Entity resolution",
                "feasibility": "Medium",
                "status": "pass",
                "owner": "entity_resolution",
            },
            {
                "name": "Conflict-aware truth",
                "feasibility": "Medium",
                "status": "pass",
                "owner": "resolution + adjudication + query",
            },
            {
                "name": "Structure-aware doc retrieval",
                "feasibility": "High",
                "status": "pass",
                "owner": "PageIndexAdapter",
            },
            {
                "name": "Global theme synthesis",
                "feasibility": "Medium",
                "status": "pass",
                "owner": "GraphRAGAdapter + orchestrator",
            },
            {
                "name": "ABAC on unstructured",
                "feasibility": "Medium",
                "status": "pass",
                "owner": "security + query filter",
            },
            {
                "name": "Deterministic numeric claims",
                "feasibility": "Medium",
                "status": "pass",
                "owner": "dual_path Path A + FactVerifier",
            },
            {
                "name": "Point-in-time as_of queries",
                "feasibility": "High",
                "status": "pass",
                "owner": "temporal.facts_as_of + query/orchestrator as_of",
            },
            {
                "name": "SaaS stub connector catalog",
                "feasibility": "High",
                "status": "pass",
                "owner": "crm/slack/metrics stubs + webhook + csv + jsonl",
            },
            {
                "name": "Early-exit high-confidence path",
                "feasibility": "High",
                "status": "pass",
                "owner": "orchestrator interactive early_exit",
            },
            {
                "name": "Interactive latency control",
                "feasibility": "Medium",
                "status": "pass",
                "owner": "budget + claim_cache + latency classes",
            },
            {
                "name": "Token cost control",
                "feasibility": "High",
                "status": "pass",
                "owner": "budget + cost_model + Gemini throttle",
            },
            {
                "name": "Idempotent reprocess",
                "feasibility": "High",
                "status": "pass",
                "owner": "reprocess + content_hash",
            },
            {
                "name": "Schema drift detect",
                "feasibility": "Medium",
                "status": "pass",
                "owner": "drift",
            },
            {
                "name": "BI materialize escape hatch",
                "feasibility": "High",
                "status": "pass",
                "owner": "materialize",
            },
            {
                "name": "Write-back with approval",
                "feasibility": "Medium",
                "status": "pass_sim",
                "owner": "action_bus (simulated execute only)",
            },
            {
                "name": "Full org single brain day-1",
                "feasibility": "Low",
                "status": "out_of_scope_poc",
                "owner": "phased multi-year platform",
            },
        ],
        "verdict": (
            "Doable as multi-year platform with phased domain rollout. "
            "POC proves trust loops, multi-engine routing, discrepancy, "
            "policy, budgets, reprocess, and BI emit on a small nasty corpus."
        ),
    }
