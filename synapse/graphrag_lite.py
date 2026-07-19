"""
GraphRAG-style hierarchical community abstraction (POC).

Not Microsoft GraphRAG — same role: global / thematic answers via community
summaries instead of pure local chunk retrieval.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from synapse.models import Entity, EntityStatus, Fact
from synapse.store import SemanticStore


@dataclass
class Community:
    community_id: str
    label: str
    entity_ids: list[str]
    predicates: list[str]
    summary: str
    size: int
    level: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommunityIndex:
    communities: list[Community]
    backend: str = "graphrag_lite"

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "count": len(self.communities),
            "communities": [c.to_dict() for c in self.communities],
        }


class GraphRAGLite:
    """
    Cluster active entities by type + dominant predicates; emit text summaries
    for global queries ("top themes", "failure modes").
    """

    name = "graphrag_lite"

    def build(self, store: SemanticStore) -> CommunityIndex:
        entities = [
            e
            for e in store.entities.values()
            if e.status == EntityStatus.ACTIVE or e.status.value == "active"
        ]
        by_type: dict[str, list[Entity]] = defaultdict(list)
        for e in entities:
            by_type[e.entity_type].append(e)

        communities: list[Community] = []
        for etype, group in sorted(by_type.items()):
            # Sub-cluster by most common predicate among member facts
            pred_counter: Counter[str] = Counter()
            member_preds: dict[str, Counter[str]] = defaultdict(Counter)
            for e in group:
                for f in store.facts_for_entity(e.entity_id):
                    if f.valid_to is not None:
                        continue
                    pred_counter[f.predicate] += 1
                    member_preds[e.entity_id][f.predicate] += 1

            top_preds = [p for p, _ in pred_counter.most_common(5)]
            # If large group, split by top predicate presence
            if len(group) >= 4 and top_preds:
                primary = top_preds[0]
                with_p = [
                    e
                    for e in group
                    if member_preds[e.entity_id].get(primary, 0) > 0
                ]
                without = [e for e in group if e not in with_p]
                for label_suffix, subset, level in (
                    (f"{primary}", with_p, 1),
                    ("other", without, 1),
                ):
                    if not subset:
                        continue
                    communities.append(
                        self._make_community(
                            store,
                            etype=etype,
                            subset=subset,
                            preds=top_preds,
                            label=f"{etype}/{label_suffix}",
                            level=level,
                        )
                    )
            else:
                communities.append(
                    self._make_community(
                        store,
                        etype=etype,
                        subset=group,
                        preds=top_preds,
                        label=etype,
                        level=0,
                    )
                )

        # Global super-community
        if communities:
            all_ids = [i for c in communities for i in c.entity_ids]
            pred_all: Counter[str] = Counter()
            for e in entities:
                for f in store.facts_for_entity(e.entity_id):
                    if f.valid_to is None:
                        pred_all[f.predicate] += 1
            summary = (
                f"Global knowledge covers {len(entities)} entities across "
                f"{len(by_type)} types. Dominant predicates: "
                + ", ".join(f"{p}({n})" for p, n in pred_all.most_common(6))
                + "."
            )
            communities.insert(
                0,
                Community(
                    community_id="community:global",
                    label="global",
                    entity_ids=all_ids[:50],
                    predicates=[p for p, _ in pred_all.most_common(8)],
                    summary=summary,
                    size=len(entities),
                    level=0,
                ),
            )

        return CommunityIndex(communities=communities)

    def _make_community(
        self,
        store: SemanticStore,
        *,
        etype: str,
        subset: list[Entity],
        preds: list[str],
        label: str,
        level: int,
    ) -> Community:
        names = [e.canonical_name or e.entity_id[:8] for e in subset[:8]]
        # Sample object values for narrative
        samples: list[str] = []
        for e in subset[:5]:
            facts = [f for f in store.facts_for_entity(e.entity_id) if f.valid_to is None]
            for f in facts[:3]:
                samples.append(f"{e.canonical_name}.{f.predicate}={f.object}")
        summary = (
            f"Community '{label}' has {len(subset)} {etype} entities "
            f"(e.g. {', '.join(n for n in names if n)}). "
        )
        if preds:
            summary += f"Key predicates: {', '.join(preds)}. "
        if samples:
            summary += "Examples: " + "; ".join(samples[:6]) + "."
        return Community(
            community_id=f"community:{label}",
            label=label,
            entity_ids=[e.entity_id for e in subset],
            predicates=preds,
            summary=summary,
            size=len(subset),
            level=level,
        )

    def query(
        self,
        index: CommunityIndex,
        question: str,
        *,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Global thematic routing: score communities by keyword overlap with summary."""
        q = {t.lower() for t in re.findall(r"[a-zA-Z0-9_-]+", question) if len(t) > 2}
        # Boost global for thematic words
        thematic = {
            "theme",
            "themes",
            "global",
            "across",
            "top",
            "failure",
            "modes",
            "summary",
            "overall",
            "all",
        }
        scored: list[tuple[float, Community]] = []
        for c in index.communities:
            blob = (c.label + " " + c.summary + " " + " ".join(c.predicates)).lower()
            hits = sum(1 for t in q if t in blob)
            score = hits / max(len(q), 1)
            if q & thematic and c.label == "global":
                score += 0.35
            if c.level == 0 and hits:
                score += 0.05
            if score > 0 or c.label == "global":
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "score": round(s, 4),
                "community": c.to_dict(),
                "answer_excerpt": c.summary,
            }
            for s, c in scored[:top_k]
        ]
