"""
Graphiti adapter status surface — real graphiti-core is already live elsewhere.

Blueprint role: Continuous Context & Temporal Relation Modeler.
Live ops live in synapse.graphiti_ops / graphiti_factory; this module only
reports package + runtime readiness for the engines facade.
"""

from __future__ import annotations

from typing import Any


def graphiti_status() -> dict[str, Any]:
    package_ok = False
    version = None
    error = None
    try:
        import graphiti_core

        package_ok = True
        version = getattr(graphiti_core, "__version__", None)
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"

    runtime: dict[str, Any] = {}
    try:
        from synapse.graphiti_ops import GraphitiOps

        runtime = GraphitiOps().status()
    except Exception as e:  # noqa: BLE001
        runtime = {"error": str(e)[:200]}

    backend = "graphiti_core" if package_ok else "local_stub"
    if runtime.get("neo4j_ready"):
        backend = "graphiti_core+neo4j_live"
    elif runtime.get("graphiti_enabled") and package_ok:
        backend = "graphiti_core+neo4j_configured"

    return {
        "backend": backend,
        "package": "graphiti-core",
        "package_importable": package_ok,
        "version": version,
        "error": error,
        "role": "Continuous Context & Temporal Relation Modeler",
        "runtime": runtime,
    }
