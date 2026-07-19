"""Detect which blueprint packages are installed *and* importable."""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any


def _has_spec(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ModuleNotFoundError, ValueError, ImportError):
        return False


def _try_import(mod: str) -> tuple[bool, str | None]:
    """Return (ok, error_message)."""
    if not _has_spec(mod):
        return False, "not_installed"
    try:
        importlib.import_module(mod)
        return True, None
    except Exception as e:  # noqa: BLE001 — surface honest status
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def _pkg_version(mod: str) -> str | None:
    try:
        m = importlib.import_module(mod)
        return getattr(m, "__version__", None) or getattr(m, "VERSION", None)
    except Exception:
        return None


def engine_availability() -> dict[str, Any]:
    """
    Blueprint four-engine inventory.

    Distinguishes:
      - installed (distribution present / find_spec)
      - importable (import succeeds)
      - notes (why fallback may be used)
    """
    g_ok, g_err = _try_import("graphiti_core")
    r_ok, r_err = _try_import("graphrag")
    # Full GraphRAG pipeline needs graphrag.api (spacy/typer/lancedb stack)
    api_ok, api_err = (False, "skipped")
    if r_ok:
        api_ok, api_err = _try_import("graphrag.api")
    j_ok, j_err = _try_import("data_juicer")
    ops_ok, ops_err = (False, "skipped")
    if j_ok:
        ops_ok, ops_err = _try_import("data_juicer.ops")
    p_ok, p_err = _try_import("pageindex")

    return {
        "graphiti": {
            "package": "graphiti-core",
            "import": "graphiti_core",
            "repo": "https://github.com/getzep/graphiti",
            "installed": _has_spec("graphiti_core"),
            "importable": g_ok,
            "error": g_err,
            "version": _pkg_version("graphiti_core") if g_ok else None,
            "role": "Continuous Context & Temporal Relation Modeler",
            "synapse_backend": "graphiti_core + Neo4j (live)" if g_ok else "local_stub",
        },
        "graphrag": {
            "package": "graphrag",
            "import": "graphrag",
            "repo": "https://github.com/microsoft/graphrag",
            "installed": _has_spec("graphrag"),
            "importable": r_ok,
            "api_importable": api_ok,
            "error": r_err if not r_ok else (api_err if not api_ok else None),
            "version": _pkg_version("graphrag") if r_ok else None,
            "role": "Hierarchical Abstractor & Global Query Synthesizer",
            "synapse_backend": (
                "graphrag_package+store_communities"
                if r_ok
                else "graphrag_lite"
            ),
            "note": (
                "Full MS pipeline (build_index/global_search) needs graphrag.api deps; "
                "Synapse always builds community abstracts over the semantic store."
                if r_ok and not api_ok
                else None
            ),
        },
        "data_juicer": {
            "package": "py-data-juicer",
            "import": "data_juicer",
            "repo": "https://github.com/datajuicer/data-juicer",
            "installed": _has_spec("data_juicer"),
            "importable": j_ok,
            "ops_importable": ops_ok,
            "error": j_err if not j_ok else (ops_err if not ops_ok else None),
            "version": _pkg_version("data_juicer") if j_ok else None,
            "role": "Multi-Format Ingestion Pipeline & Raw Data Streamliner",
            "synapse_backend": (
                "data_juicer_ops+lite_chain" if ops_ok else "data_juicer_lite"
            ),
        },
        "pageindex": {
            "package": "pageindex",
            "import": "pageindex",
            "repo": "https://github.com/VectifyAI/PageIndex",
            "installed": _has_spec("pageindex"),
            "importable": p_ok,
            "error": p_err,
            "version": _pkg_version("pageindex") if p_ok else None,
            "role": "Reasoning-Based Document & Structural Tree Navigator",
            "synapse_backend": (
                "pageindex_client+local_tree" if p_ok else "pageindex_lite"
            ),
            "note": "Cloud PageIndexClient needs PAGEINDEX_API_KEY; local tree always on.",
        },
        "all_installed": all(
            [
                _has_spec("graphiti_core"),
                _has_spec("graphrag"),
                _has_spec("data_juicer"),
                _has_spec("pageindex"),
            ]
        ),
        "all_importable": all([g_ok, r_ok, j_ok, p_ok]),
    }
