"""
Super schema: an explicit combine-step over 2+ workspaces. Unions their
sources and already-confirmed relationships, discovers NEW candidate
relationships between sources that live in *different* member workspaces
(the actual value of combining them -- not just union what each already
found on its own), and flags conflicts where two workspaces define the
same canonical field name with a different data_type.

Cross-workspace candidates are genuinely uncertain guesses across
independently-curated projects -- they're returned as normal
CandidateEdges, not auto-confirmed, so they go through the exact same
score -> review -> Accept flow (ExplanationDrawer / POST
/v1/ontology/relationships) everything else in this app already uses.
"""

from __future__ import annotations

from typing import Any, Optional

from synapse.matching import analyze_sources
from synapse.profiling import SchemaProfiler, _canonicalize_field_name
from synapse.security import Principal


def compute_super_schema(
    store, ontology, profiler: SchemaProfiler, workspace_ids: list[str], *, principal: Optional[Principal] = None
) -> dict[str, Any]:
    workspace_id_set = set(workspace_ids)

    # (a) union of member sources, tagged with which workspace each came from.
    sources_by_workspace: dict[str, list[str]] = {}
    for ws_id in workspace_ids:
        sources_by_workspace[ws_id] = profiler.known_sources(principal=principal, workspace_id=ws_id)
    all_sources = sorted({s for srcs in sources_by_workspace.values() for s in srcs})

    # (b) existing relationships where both sides resolve into the given set.
    existing_relationships = []
    for edge in ontology.relationships.values():
        ws_a = store.workspace_for_source(edge.source_a.get("source_system", ""))
        ws_b = store.workspace_for_source(edge.source_b.get("source_system", ""))
        if ws_a in workspace_id_set and ws_b in workspace_id_set:
            existing_relationships.append(edge.to_dict())

    # (c) newly-scored candidates between sources from DIFFERENT member
    # workspaces -- the actual value of combining them. Same-workspace
    # pairs are skipped (that's Explore/Schema View's job within one
    # workspace, already covered by (b) once confirmed).
    profiles_by_source = {s: profiler.profile_source(s, principal=principal) for s in all_sources}
    cross_workspace_candidates = []
    seen_pairs: set[frozenset] = set()
    for i, source_a in enumerate(all_sources):
        for source_b in all_sources[i + 1 :]:
            ws_a = store.workspace_for_source(source_a)
            ws_b = store.workspace_for_source(source_b)
            if ws_a == ws_b:
                continue
            pair_key = frozenset({source_a, source_b})
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            edges = analyze_sources(store, ontology, profiles_by_source[source_a], profiles_by_source[source_b])
            cross_workspace_candidates.extend(e.to_dict() for e in edges)
    cross_workspace_candidates.sort(key=lambda e: e["similarity_score"], reverse=True)

    # (d) conflicts: same canonical field name appearing in >=2 member
    # workspaces with a different dominant data_type.
    by_canonical: dict[str, dict[str, set[str]]] = {}
    for ws_id, srcs in sources_by_workspace.items():
        for source in srcs:
            for field_name, profile in profiles_by_source[source].items():
                canonical = _canonicalize_field_name(field_name)
                if not canonical:
                    continue
                by_canonical.setdefault(canonical, {}).setdefault(ws_id, set()).add(profile.data_type)

    conflicts = []
    for canonical, by_ws in by_canonical.items():
        if len(by_ws) < 2:
            continue
        all_types = {t for types in by_ws.values() for t in types}
        if len(all_types) < 2:
            continue
        conflicts.append(
            {
                "canonical_field": canonical,
                "workspaces": {ws_id: sorted(types) for ws_id, types in by_ws.items()},
            }
        )

    return {
        "workspace_ids": workspace_ids,
        "sources": [{"source_system": s, "workspace_id": store.workspace_for_source(s)} for s in all_sources],
        "relationships": existing_relationships,
        "cross_workspace_candidates": cross_workspace_candidates,
        "conflicts": conflicts,
    }
