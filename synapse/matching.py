"""
Hybrid candidate matching & scoring (Major Goal 2).

Exact spec contract, zero deviation:

    S_total = 0.45*VectorSim(A,B) + 0.40*ValueOverlap(A,B) + 0.15*GraphProximity(A,B)

Thresholds: high-confidence >=0.85, candidate 0.50-0.85, strict-drop <0.50.
Output: the CandidateEdge schema (candidate_id, source_a, source_b,
similarity_score, match_reasons, status).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from synapse.models import utc_now_iso
from synapse.ontology import OntologyRegistry
from synapse.profiling import SchemaFieldProfile, cosine_similarity, jaccard_from_minhash
from synapse.store import SemanticStore

VECTOR_WEIGHT = 0.45
VALUE_OVERLAP_WEIGHT = 0.40
GRAPH_PROXIMITY_WEIGHT = 0.15

HIGH_CONFIDENCE_THRESHOLD = 0.85
CANDIDATE_THRESHOLD = 0.50


def vector_sim(a: SchemaFieldProfile, b: SchemaFieldProfile) -> float:
    return cosine_similarity(a.semantic_vector, b.semantic_vector)


def value_overlap(a: SchemaFieldProfile, b: SchemaFieldProfile) -> float:
    return jaccard_from_minhash(a.min_hash_sketch, b.min_hash_sketch)


def _dominant_ontology_type(store: SemanticStore, source_system: str) -> Optional[str]:
    """Best-effort: the most common ontology_type among entities that have at
    least one fact landed from this source_system. Returns None (unknown)
    when nothing has been extracted from the source yet -- GraphProximity
    then contributes 0.0 rather than guessing."""
    entity_ids = {f.subject_entity_id for f in store.facts.values() if f.source_system == source_system}
    if not entity_ids:
        return None
    types = [
        store.entities[eid].ontology_type
        for eid in entity_ids
        if eid in store.entities and store.entities[eid].ontology_type
    ]
    if not types:
        return None
    return Counter(types).most_common(1)[0][0]


def graph_proximity(store: SemanticStore, ontology: OntologyRegistry, source_a: str, source_b: str) -> float:
    """Heuristic graph-proximity signal (weight 0.15, so approximate is
    acceptable): 1.0 if the two sources' already-extracted entities share/are
    compatible ontology type families (reuses the existing generic
    compatible_types()/types_match() mechanism -- see docs/DOMAIN_PACK_CONTRACT.md),
    else 0.0 when there isn't yet any extracted-entity evidence to compare."""
    type_a = _dominant_ontology_type(store, source_a)
    type_b = _dominant_ontology_type(store, source_b)
    if not type_a or not type_b:
        return 0.0
    return 1.0 if ontology.types_match(type_a, type_b) else 0.0


def _match_reasons(
    vsim: float, voverlap: float, gprox: float, profile_a: SchemaFieldProfile, profile_b: SchemaFieldProfile
) -> list[str]:
    reasons: list[str] = []
    if vsim > 0.0:
        reasons.append(f"Semantic Name Similarity ({vsim:.2f})")
    if voverlap > 0.0:
        reasons.append(f"Value Distribution Overlap ({voverlap:.2f})")
    if profile_a.data_type == profile_b.data_type:
        reasons.append(f"Matching data_type ({profile_a.data_type})")
    if gprox > 0.0:
        reasons.append(f"Graph Proximity ({gprox:.2f})")
    if not reasons:
        reasons.append("No strong signal")
    return reasons


@dataclass
class CandidateEdge:
    candidate_id: str
    source_a: dict[str, str]
    source_b: dict[str, str]
    similarity_score: float
    match_reasons: list[str]
    status: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_a": self.source_a,
            "source_b": self.source_b,
            "similarity_score": self.similarity_score,
            "match_reasons": self.match_reasons,
            "status": self.status,
        }


def score_pair(
    store: SemanticStore,
    ontology: OntologyRegistry,
    profile_a: SchemaFieldProfile,
    profile_b: SchemaFieldProfile,
    *,
    force: bool = False,
) -> Optional[CandidateEdge]:
    """Returns None (strict drop) when S_total < 0.50, per spec Task 3 --
    unless force=True (Schema View's manual "user drew this connection"
    path): the user isn't relying on the score to decide, they already
    decided by drawing the line, so a low score is informational, not a
    reason to silently refuse to show them a drawer at all. Forced
    below-threshold results get status="manual" (distinct from the
    machine-recommended "candidate"/"high_confidence") and an explicit
    reason noting the score didn't clear the normal bar."""
    vsim = vector_sim(profile_a, profile_b)
    voverlap = value_overlap(profile_a, profile_b)
    gprox = graph_proximity(store, ontology, profile_a.source_system, profile_b.source_system)

    s_total = round(
        VECTOR_WEIGHT * vsim + VALUE_OVERLAP_WEIGHT * voverlap + GRAPH_PROXIMITY_WEIGHT * gprox, 4
    )
    if s_total < CANDIDATE_THRESHOLD and not force:
        return None

    reasons = _match_reasons(vsim, voverlap, gprox, profile_a, profile_b)
    if s_total < CANDIDATE_THRESHOLD:
        status = "manual"
        reasons = reasons + ["Manually connected by user (score below the usual candidate threshold)"]
    elif s_total >= HIGH_CONFIDENCE_THRESHOLD:
        status = "high_confidence"
    else:
        status = "candidate"

    return CandidateEdge(
        candidate_id=str(uuid4()),
        source_a={"source_system": profile_a.source_system, "field_name": profile_a.field_name},
        source_b={"source_system": profile_b.source_system, "field_name": profile_b.field_name},
        similarity_score=s_total,
        match_reasons=reasons,
        status=status,
    )


class CandidateCache:
    """In-memory holding area for scored CandidateEdges between the time
    they're returned by /v1/explore/analyze and a curation decision
    (ACCEPT/REJECT/RELABEL) is made against their candidate_id. Process
    lifetime only, same durability boundary as the rest of this POC's
    non-store state (e.g. DriftDetector.baselines)."""

    def __init__(self) -> None:
        self._by_id: dict[str, CandidateEdge] = {}

    def put_all(self, edges: list[CandidateEdge]) -> None:
        for e in edges:
            self._by_id[e.candidate_id] = e

    def get(self, candidate_id: str) -> Optional[CandidateEdge]:
        return self._by_id.get(candidate_id)


def _same_entity_as_edges_touching(ontology: OntologyRegistry, source_system: str) -> list[Any]:
    """Accepted SAME_ENTITY_AS relationship edges with one side on source_system."""
    out = []
    for edge in ontology.relationships.values():
        if edge.predicate != "SAME_ENTITY_AS":
            continue
        if edge.source_a.get("source_system") == source_system or edge.source_b.get("source_system") == source_system:
            out.append(edge)
    return out


def transitive_candidates(
    store: SemanticStore,
    ontology: OntologyRegistry,
    profiler: Any,
    source_c: str,
    profiles_c: dict[str, SchemaFieldProfile],
    principal: Any = None,
) -> list[CandidateEdge]:
    """Major Goal 4, task 3 (Transitive Learning Engine). When newly-profiled
    Source C matches an already-linked Source B, propose a new CandidateEdge
    from C to every Source A that B is already SAME_ENTITY_AS-linked to,
    citing the transitive mapping.

    profiles_c is expected to already be ACL-scoped by the caller (the same
    principal is threaded through here so Source B is profiled under that
    same scope, not unrestricted -- otherwise a principal without access to
    B's raw data could still learn its field names/stats via the C-side
    transitive walk.
    """
    linked_systems: set[str] = set()
    for edge in ontology.relationships.values():
        if edge.predicate != "SAME_ENTITY_AS":
            continue
        linked_systems.add(edge.source_a.get("source_system", ""))
        linked_systems.add(edge.source_b.get("source_system", ""))
    linked_systems.discard(source_c)
    linked_systems.discard("")

    results: list[CandidateEdge] = []
    for source_b in linked_systems:
        profiles_b = profiler.profile_source(source_b, principal=principal)
        if not profiles_b:
            continue
        direct = analyze_sources(store, ontology, profiles_c, profiles_b)
        if not direct:
            continue
        best_c_b = direct[0]  # highest-scoring C<->B field pair
        for edge in _same_entity_as_edges_touching(ontology, source_b):
            other_side = edge.source_a if edge.source_b.get("source_system") == source_b else edge.source_b
            source_a_system = other_side.get("source_system")
            if not source_a_system or source_a_system in (source_b, source_c):
                continue
            results.append(
                CandidateEdge(
                    candidate_id=str(uuid4()),
                    source_a=dict(other_side),
                    source_b=best_c_b.source_a,  # the Source C field that matched B
                    similarity_score=best_c_b.similarity_score,
                    match_reasons=list(best_c_b.match_reasons)
                    + [f"Transitive mapping via {source_b} (already linked to {source_a_system})"],
                    status=best_c_b.status,
                )
            )
    return results


def analyze_sources(
    store: SemanticStore,
    ontology: OntologyRegistry,
    profiles_a: dict[str, SchemaFieldProfile],
    profiles_b: dict[str, SchemaFieldProfile],
) -> list[CandidateEdge]:
    """All-pairs field comparison across two sources' profile sets.

    Pairs already logged as a REJECT negative-feedback signal
    (OntologyRegistry.reject_relationship) are skipped -- otherwise a
    re-analyze would keep re-surfacing exactly what a human already told
    the system was a false positive, defeating the point of REJECT.
    """
    edges: list[CandidateEdge] = []
    for field_a, profile_a in profiles_a.items():
        for field_b, profile_b in profiles_b.items():
            edge = score_pair(store, ontology, profile_a, profile_b)
            if edge is None:
                continue
            if ontology.is_pair_rejected(edge.source_a, edge.source_b):
                continue
            edges.append(edge)
    edges.sort(key=lambda e: e.similarity_score, reverse=True)
    return edges
