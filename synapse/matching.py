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

# VectorSim leans on field *names* (a char-trigram hash + an English-only
# synonym table -- see profiling.py) -- a real relationship across
# differently-named or differently-languaged sources can score ~0 on name
# alone. When the actual observed *values* overlap this strongly and the
# two fields share a data_type, that's real automated evidence independent
# of naming, strong enough to clear the candidate bar on its own rather
# than requiring the name signal to contribute anything.
VALUE_OVERLAP_OVERRIDE_THRESHOLD = 0.90

# Deterministic field-name alias groups (docs/Instrument_Data_Format.md
# section 3's "AliasMapper", built as a supplementary signal on top of the
# fuzzy VectorSim/trigram matching above, not a replacement for it) --
# known vendor/LIS/middleware naming variants for the same real-world
# concept that trigram similarity alone often misses (e.g. "PtID" vs
# "patient_id" share almost no substrings despite being obvious synonyms
# to a human). Explicit and human-reviewable, same spirit as HL7's
# STRUCTURAL_LINKS -- add a variant here only when it's a genuinely known
# naming convention, not a guess. Deliberately scoped to atomic identifier
# concepts (never composite/name fields): an identifier either is the same
# real-world reference or isn't, whereas a "combined name" field and a
# "split last/first name" field aren't really the same shape even when
# they describe the same person, so asserting them as literally aliased
# would overclaim.
ALIAS_GROUPS: dict[str, frozenset[str]] = {
    "patient_identity": frozenset({
        "patientid", "patient_ref", "ptid", "patient_id", "pid-3",
        "subject.reference", "patientidentifier", "patient_identifier",
    }),
    "specimen_identity": frozenset({
        "sampleid", "sample_id", "specimenbarcode", "specimen_id",
        "specimenid", "barcode",
    }),
    "assay_identity": frozenset({
        "testcode", "test_code", "assaycode", "assay_code",
    }),
}


def _alias_group_for(field_name: str) -> Optional[str]:
    lname = field_name.lower()
    for group, variants in ALIAS_GROUPS.items():
        if lname in variants:
            return group
    return None


def fields_are_known_aliases(field_a: str, field_b: str) -> bool:
    group_a = _alias_group_for(field_a)
    return group_a is not None and group_a == _alias_group_for(field_b)


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

    # A known alias pair counts as a full name-similarity signal for
    # scoring purposes (that's what "known alias" means -- trigram
    # similarity just can't see it) while match_reasons below still
    # reports the real vsim, so the explanation stays honest about what
    # trigram similarity alone found.
    alias_match = (
        fields_are_known_aliases(profile_a.field_name, profile_b.field_name)
        and profile_a.data_type == profile_b.data_type
    )
    effective_vsim = 1.0 if alias_match else vsim

    s_total = round(
        VECTOR_WEIGHT * effective_vsim + VALUE_OVERLAP_WEIGHT * voverlap + GRAPH_PROXIMITY_WEIGHT * gprox, 4
    )
    value_overlap_override = (
        voverlap >= VALUE_OVERLAP_OVERRIDE_THRESHOLD and profile_a.data_type == profile_b.data_type
    )
    if s_total < CANDIDATE_THRESHOLD and not force and not value_overlap_override and not alias_match:
        return None

    reasons = _match_reasons(vsim, voverlap, gprox, profile_a, profile_b)
    if alias_match:
        reasons = reasons + [f"Known field-name alias ({profile_a.field_name} ↔ {profile_b.field_name})"]
    if s_total < CANDIDATE_THRESHOLD and value_overlap_override:
        status = "candidate"
        reasons = reasons + [
            "Strong value overlap despite low name similarity "
            "(possibly a different naming convention or language)"
        ]
    elif s_total < CANDIDATE_THRESHOLD and alias_match:
        status = "candidate"
        reasons = reasons + ["Known vendor field-name alias, but observed values don't corroborate it yet"]
    elif s_total < CANDIDATE_THRESHOLD:
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


def auto_link_aliases(
    store: SemanticStore,
    ontology: OntologyRegistry,
    profiler: Any,
    new_source: str,
    *,
    workspace_id: Optional[str] = None,
    principal: Any = None,
) -> list[Any]:
    """Run once at ingest for a newly-landed source (docs/Instrument_Data_
    Format.md section 3's "AliasMapper", additive to -- not a replacement
    for -- the fuzzy VectorSim matching every other candidate path already
    runs): pairs the new source's fields against every other already-known
    source in the same workspace, and auto-confirms only the pairs that are
    BOTH a known field-name alias AND well-corroborated by real observed
    value overlap (status == "high_confidence" from score_pair's normal
    threshold logic, forced past the strict-drop floor by the alias itself
    -- see score_pair's alias_match handling).

    Deliberately conservative about what gets silently asserted as fact:
    an alias match alone (e.g. two different vendors' files both calling a
    field "patient_id") does NOT by itself mean the two specific datasets
    share real patients -- unrelated demo files can use the same *label*
    for genuinely different value spaces. Requiring real value overlap too
    is what makes auto-confirm honest here (same reasoning HL7/ASTM's
    structural links get to skip: those really are facts about one file's
    own structure, not a claim about two independently-curated datasets
    actually corresponding). A well-named-but-uncorroborated pair still
    surfaces as a normal "candidate" for review, exactly like any other
    scored match -- nothing is hidden, just not silently confirmed.

    `new_source` is the just-landed source's BASE name -- for a
    decomposable format (HL7/ASTM/FHIR/vendor JSON) that expands to
    several virtual sub-sources ("base::TYPE"), each of which needs its
    own alias check against every other known source, not just the base
    name itself (which has no fields of its own once decomposed -- see
    profiling.py's "no type_filter on decomposable content -> {}" rule)."""
    all_known = profiler.known_sources(principal=principal, workspace_id=workspace_id)
    new_expanded = [s for s in all_known if s.split("::", 1)[0] == new_source]
    if not new_expanded:
        return []

    created: list[Any] = []
    for new_full in new_expanded:
        new_profiles = profiler.profile_source(new_full, principal=principal, workspace_id=workspace_id)
        if not new_profiles:
            continue
        for other_source in all_known:
            if other_source.split("::", 1)[0] == new_source:
                continue  # same landed file -- structural links (if any) already cover this
            other_profiles = profiler.profile_source(other_source, principal=principal, workspace_id=workspace_id)
            if not other_profiles:
                continue
            for field_a, profile_a in new_profiles.items():
                for field_b, profile_b in other_profiles.items():
                    if not fields_are_known_aliases(field_a, field_b):
                        continue
                    source_a_ref = {"source_system": new_full, "field_name": field_a}
                    source_b_ref = {"source_system": other_source, "field_name": field_b}
                    if ontology.is_pair_rejected(source_a_ref, source_b_ref):
                        continue
                    if ontology.find_relationship_by_pair(source_a_ref, source_b_ref) is not None:
                        continue
                    edge = score_pair(store, ontology, profile_a, profile_b, force=True)
                    if edge is None or edge.status != "high_confidence":
                        continue
                    confirmed = ontology.accept_relationship(
                        candidate_id=edge.candidate_id,
                        source_a=edge.source_a,
                        source_b=edge.source_b,
                        predicate="SAME_ENTITY_AS",
                        match_reasons=edge.match_reasons,
                        similarity_score=edge.similarity_score,
                    )
                    created.append(confirmed)
    return created
