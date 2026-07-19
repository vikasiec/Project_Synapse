"""
GraphRAG adapter — Microsoft graphrag package + store-native communities.

Blueprint role: Hierarchical Abstractor & Global Query Synthesizer.

Microsoft GraphRAG is a full document-corpus index/query stack (LLM + storage).
Project Synapse's semantic store already holds entities/facts; for the POC we:
  1. Prefer detecting the real `graphrag` package (version, api readiness).
  2. Always build hierarchical community abstracts over *our* store (GraphRAG-lite
     algorithm aligned to the blueprint role) so themes work offline without a
     second LLM-heavy pipeline eating free-tier quota.
  3. Expose optional hooks for future MS pipeline runs when graphrag.api imports.
"""

from __future__ import annotations

from typing import Any, Optional

from synapse.graphrag_lite import CommunityIndex, GraphRAGLite
from synapse.store import SemanticStore


class GraphRAGAdapter:
    """Hierarchical community abstractor over the semantic store."""

    def __init__(self) -> None:
        self._lite = GraphRAGLite()
        self._package_ok = False
        self._api_ok = False
        self._version: Optional[str] = None
        self._error: Optional[str] = None
        self._backend = "graphrag_lite"
        self._probe()

    def _probe(self) -> None:
        self._api_exports: list[str] = []
        try:
            import graphrag

            self._package_ok = True
            self._version = getattr(graphrag, "__version__", None)
            self._backend = "graphrag_package+store_communities"
        except Exception as e:  # noqa: BLE001
            self._error = f"{type(e).__name__}: {e}"
            self._backend = "graphrag_lite"
            return

        try:
            import graphrag.api as api

            self._api_ok = True
            self._backend = "graphrag_api+store_communities"
            self._api_exports = sorted(
                x
                for x in dir(api)
                if not x.startswith("_")
                and callable(getattr(api, x, None))
            )
        except Exception as e:  # noqa: BLE001
            self._error = f"api:{type(e).__name__}: {str(e)[:160]}"

    @property
    def name(self) -> str:
        return self._backend

    def build(self, store: SemanticStore) -> CommunityIndex:
        idx = self._lite.build(store)
        # Tag backend so callers/POC evidence show package vs pure-lite
        idx.backend = self._backend
        return idx

    def query(
        self,
        index: CommunityIndex,
        question: str,
        *,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        hits = self._lite.query(index, question, top_k=top_k)
        for h in hits:
            h["engine_backend"] = self._backend
        return hits

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self._backend,
            "package": "graphrag",
            "package_importable": self._package_ok,
            "api_importable": self._api_ok,
            "api_exports": list(getattr(self, "_api_exports", [])),
            "version": self._version,
            "error": self._error,
            "role": "Hierarchical Abstractor & Global Query Synthesizer",
            "note": (
                "Communities are built over Project Synapse SemanticStore "
                "(entity/type + predicate clustering) so themes work offline. "
                "Real graphrag.api (build_index, global_search, local_search, …) "
                "is detected when importable for full-corpus jobs."
            ),
        }


def create_graphrag_adapter() -> GraphRAGAdapter:
    return GraphRAGAdapter()
