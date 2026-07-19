"""
Blueprint engine facade — maps master PDF pieces to live implementations.

| Blueprint        | Implementation                                      |
|------------------|-----------------------------------------------------|
| Data-Juicer      | integrations.DataJuicerAdapter (pkg + lite chain)   |
| Graphiti         | graphiti_core + Neo4j (graphiti_ops)                |
| GraphRAG         | integrations.GraphRAGAdapter (pkg + store communities) |
| PageIndex        | integrations.PageIndexAdapter (pkg + local tree)    |

Always honest about package vs lite via describe() / engine_availability().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from synapse.integrations.availability import engine_availability
from synapse.integrations.data_juicer_adapter import (
    DataJuicerAdapter,
    create_prep_adapter,
)
from synapse.integrations.graphiti_adapter import graphiti_status
from synapse.integrations.graphrag_adapter import (
    GraphRAGAdapter,
    create_graphrag_adapter,
)
from synapse.integrations.pageindex_adapter import (
    PageIndexAdapter,
    create_pageindex_adapter,
)
from synapse.graphrag_lite import CommunityIndex
from synapse.operators import OperatorPipeline
from synapse.pageindex import DocTree
from synapse.store import SemanticStore


@dataclass
class EngineRegistry:
    """Lazy-built engine views over the semantic store."""

    store: SemanticStore
    prep: DataJuicerAdapter = field(default_factory=create_prep_adapter)
    pageindex: PageIndexAdapter = field(default_factory=create_pageindex_adapter)
    graphrag: GraphRAGAdapter = field(default_factory=create_graphrag_adapter)
    _community_index: Optional[CommunityIndex] = None
    _doc_trees: dict[str, DocTree] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        packages = engine_availability()
        return {
            "blueprint_engines": packages,
            "data_juicer": {
                **self.prep.describe(),
                "operators": self.prep.pipeline.describe()
                if hasattr(self.prep, "pipeline")
                else self.prep.describe().get("lite_operators"),
            },
            "graphiti": graphiti_status(),
            "graphrag": {
                **self.graphrag.describe(),
                "communities": len(self._community_index.communities)
                if self._community_index
                else 0,
            },
            "pageindex": {
                **self.pageindex.describe(),
                "doc_trees": len(self._doc_trees),
            },
        }

    def rebuild_communities(self) -> CommunityIndex:
        self._community_index = self.graphrag.build(self.store)
        return self._community_index

    def communities(self) -> CommunityIndex:
        if self._community_index is None:
            return self.rebuild_communities()
        return self._community_index

    def index_document(
        self,
        text: str,
        *,
        title: str = "document",
        doc_id: Optional[str] = None,
    ) -> DocTree:
        tree = self.pageindex.build(text, title=title, doc_id=doc_id)
        self._doc_trees[tree.doc_id] = tree
        return tree

    def index_episode_docs(self) -> list[DocTree]:
        """Build PageIndex trees for long episodes (doc-like payloads)."""
        trees: list[DocTree] = []
        for ep in self.store.episodes.values():
            text = ep.payload_text or ""
            if len(text) < 80:
                continue
            if text.count("\n") < 2 and "#" not in text:
                continue
            tree = self.pageindex.build(
                text,
                title=f"episode:{ep.episode_id[:8]}",
                doc_id=f"doc:{ep.episode_id}",
            )
            self._doc_trees[tree.doc_id] = tree
            trees.append(tree)
        return trees

    def route_query(
        self,
        question: str,
        *,
        intent: str = "entity_lookup",
    ) -> dict[str, Any]:
        """
        Multi-engine answer assist:
          themes/* → GraphRAG communities
          doc/* or low-structure → PageIndex leaves
          else → entity path handled by QueryService
        """
        intent_l = (intent or "").lower()
        q_l = question.lower()
        thematic = any(
            w in q_l
            for w in (
                "theme",
                "themes",
                "across",
                "global",
                "top failure",
                "failure mode",
                "overall",
                "summary of all",
            )
        )
        if intent_l in {"themes", "global_summary", "failure_modes"} or thematic:
            idx = self.communities()
            hits = self.graphrag.query(idx, question, top_k=3)
            return {
                "engine": self.graphrag.name,
                "intent": "global_themes",
                "hits": hits,
            }

        if intent_l in {"document", "doc", "pageindex"} or any(
            w in q_l for w in ("section", "document", "heading", "page ")
        ):
            if not self._doc_trees:
                self.index_episode_docs()
            routed = []
            for tree in self._doc_trees.values():
                for hit in self.pageindex.route(tree, question, top_k=2):
                    hit["doc_id"] = tree.doc_id
                    hit["doc_title"] = tree.title
                    routed.append(hit)
            routed.sort(key=lambda h: h.get("score", 0), reverse=True)
            return {
                "engine": self.pageindex.name,
                "intent": "document_navigate",
                "hits": routed[:5],
            }

        return {
            "engine": "semantic_query",
            "intent": intent_l or "entity_lookup",
            "hits": [],
            "hint": "Use query service for entity/conflict claims",
        }


def build_engine_registry(
    store: SemanticStore,
    *,
    pipeline: Optional[OperatorPipeline] = None,
) -> EngineRegistry:
    prep = create_prep_adapter(pipeline)
    return EngineRegistry(
        store=store,
        prep=prep,
        pageindex=create_pageindex_adapter(),
        graphrag=create_graphrag_adapter(),
    )
