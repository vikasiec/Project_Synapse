"""
Graph-First Discovery & Entity Resolution (docs/Graph-First Discovery &
Entity Resolution.pdf) -- a second, entity-level curation layer alongside
the schema-field discovery in synapse/matching.py.

Where matching.py answers "does source A's field mean the same thing as
source B's field", this module answers "is this entity extracted from
source A the same real-world thing as that entity extracted from source
B" -- e.g. "Justin Mason" in the CRM vs "J. Mason" in Billing logs.

Steps 1-2 of the doc's 4-step pipeline (isolated ingestion, temporal fact
extraction) are already what synapse/ingestion.py + synapse/dual_path.py
do on every landed episode -- nothing new needed there. This module is
Step 3 (blocking -> pairwise scoring -> clustering into merge candidates)
+ the data shape Step 4's Curation Canvas reads.

No formula is given in the source doc (unlike Major Goal 2's original
column-matching spec, which specifies exact 0.45/0.40/0.15 weights) --
the weights below are this module's own reasonable design, documented so
they can be revisited, not implied to be a spec requirement.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from synapse.models import Entity, EntityStatus, utc_now_iso
from synapse.profiling import cosine_similarity
from synapse.profiling import _hashing_vector as hashing_vector
from synapse.store import SemanticStore

NAME_SIM_WEIGHT = 0.7
CROSS_SYSTEM_WEIGHT = 0.3

HIGH_CONFIDENCE_THRESHOLD = 0.80
CANDIDATE_THRESHOLD = 0.45

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORD_TOKENS = {"the", "and", "of", "inc", "llc", "ltd"}


def _tokens(name: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(name.lower()) if len(t) >= 3 and t not in _STOPWORD_TOKENS}


@dataclass
class EntityMergeCandidate:
    """The entity-level analog of matching.py's CandidateEdge."""

    candidate_id: str
    entity_a: dict[str, str]
    entity_b: dict[str, str]
    similarity_score: float
    match_reasons: list[str]
    status: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "entity_a": self.entity_a,
            "entity_b": self.entity_b,
            "similarity_score": self.similarity_score,
            "match_reasons": self.match_reasons,
            "status": self.status,
        }


def _entity_ref(store: SemanticStore, ent: Entity) -> dict[str, str]:
    sources = sorted({f.source_system for f in store.facts_for_entity(ent.entity_id)})
    return {
        "entity_id": ent.entity_id,
        "entity_type": ent.entity_type,
        "canonical_name": ent.canonical_name or "",
        "source_systems": ",".join(sources),
    }


def _name_blocks(entities: list[Entity]) -> dict[str, list[Entity]]:
    """Step 3, tier 1 (Blocking): cheap, deterministic token-sharing keys --
    looser than exact-normalized-name equality (EntityResolutionService.
    suggest_merges()'s existing blocking) so "Justin Mason" and "J. Mason"
    land in the same block via the shared "mason" token, not just exact
    full-name matches."""
    blocks: dict[str, list[Entity]] = defaultdict(list)
    for ent in entities:
        names = [ent.canonical_name] + list(ent.aliases)
        seen_tokens: set[str] = set()
        for name in names:
            if not name:
                continue
            seen_tokens |= _tokens(name)
        for token in seen_tokens:
            blocks[f"{ent.entity_type}:{token}"].append(ent)
    return blocks


def _name_similarity(a: Entity, b: Entity) -> float:
    name_a = a.canonical_name or (a.aliases[0] if a.aliases else "")
    name_b = b.canonical_name or (b.aliases[0] if b.aliases else "")
    if not name_a or not name_b:
        return 0.0
    return cosine_similarity(hashing_vector(name_a), hashing_vector(name_b))


def _cross_system_bonus(store: SemanticStore, a: Entity, b: Entity) -> tuple[float, bool]:
    sources_a = {f.source_system for f in store.facts_for_entity(a.entity_id)}
    sources_b = {f.source_system for f in store.facts_for_entity(b.entity_id)}
    is_cross_system = bool(sources_a) and bool(sources_b) and sources_a.isdisjoint(sources_b)
    return (1.0 if is_cross_system else 0.0), is_cross_system


def score_entity_pair(store: SemanticStore, a: Entity, b: Entity) -> Optional[EntityMergeCandidate]:
    """Step 3, tier 2 (Pairwise Scoring). Returns None (strict drop) below
    CANDIDATE_THRESHOLD, same discipline as matching.py's score_pair()."""
    name_sim = _name_similarity(a, b)
    cross_bonus, is_cross_system = _cross_system_bonus(store, a, b)
    s_total = round(NAME_SIM_WEIGHT * name_sim + CROSS_SYSTEM_WEIGHT * cross_bonus, 4)
    if s_total < CANDIDATE_THRESHOLD:
        return None

    reasons = [f"Name Similarity ({name_sim:.2f})"]
    if is_cross_system:
        reasons.append("Found in different source systems")
    if a.entity_type == b.entity_type:
        reasons.append(f"Matching entity_type ({a.entity_type})")

    status = "high_confidence" if s_total >= HIGH_CONFIDENCE_THRESHOLD else "candidate"
    return EntityMergeCandidate(
        candidate_id=str(uuid4()),
        entity_a=_entity_ref(store, a),
        entity_b=_entity_ref(store, b),
        similarity_score=s_total,
        match_reasons=reasons,
        status=status,
    )


def generate_entity_merge_candidates(
    store: SemanticStore, *, entities: Optional[list[Entity]] = None, ontology: Optional[object] = None
) -> list[EntityMergeCandidate]:
    """Step 3, tier 3 (Clustering, simplified to pairwise CandidateEdges --
    the Curation Canvas resolves transitive clusters one ACCEPT at a time,
    same as Major Goal 4's field-relationship curation).

    `ontology`, when given, excludes entity types the ontology already
    marks `strict_identity` (LabResult, Patient, Doctor, AccountHolder,
    ...) from name-based blocking entirely. That flag exists precisely
    because a shared display name is *not* evidence of sameness for these
    types -- entity_resolution.py's own landing-time get_or_create()
    already refuses to merge two same-named LabResults/Patients on name
    alone, blocking on the authoritative external_id instead (its own
    comment: "A name match alone must never merge two different real
    people"). Real dataset caught this the hard way: 86 separately-landed
    LabResult entities that all display as "Glucose" (one per patient,
    correctly kept distinct on purpose) formed one name-block and flooded
    Resolve with candidates to merge patients' results into each other --
    exactly the outcome strict_identity exists to prevent. Skipping these
    types here isn't a workaround; it's applying the same rule the rest
    of the system already encodes, to the one place that had forgotten
    to check it. Types without strict_identity (generic Person/Org, where
    cross-system name variance like "Justin Mason" vs "J. Mason" really
    is useful curator signal) are unaffected.

    Within a block, pair every member against one stable anchor (star
    topology) rather than every combination (complete graph) -- a block of
    n identically-blocked entities is a real, common case (e.g. many
    LabResult entities that all share a test name like "Glucose" because
    per-record entity resolution never collapsed them into one shared
    analyte identity) and C(n, 2) pairwise candidates for such a block
    buries Resolve under thousands of near-duplicate cards for what is
    really one repeated decision. Anchoring keeps every member reachable
    in exactly one candidate (nothing hidden) while emitting n-1 pairs
    instead of C(n, 2); since the anchor is always entity_a and the UI's
    merge action keeps entity_a as the survivor, accepting each pair
    collapses the block into the anchor one ACCEPT at a time, exactly as
    the star-topology docstring above already promised for the general
    case -- this just keeps that promise sub-quadratic too."""
    pool = entities if entities is not None else [
        e for e in store.entities.values() if e.status == EntityStatus.ACTIVE
    ]
    if ontology is not None:
        def _is_strict_identity(entity: Entity) -> bool:
            ot = ontology.get(entity.entity_type) or ontology.get(entity.ontology_type or "")
            return bool(ot and ot.strict_identity)

        pool = [e for e in pool if not _is_strict_identity(e)]
    blocks = _name_blocks(pool)

    candidates: list[EntityMergeCandidate] = []
    seen_pairs: set[tuple[str, str]] = set()
    for members in blocks.values():
        if len(members) < 2:
            continue
        anchor = min(members, key=lambda e: e.entity_id)
        for other in members:
            if other.entity_id == anchor.entity_id:
                continue
            pair_key = tuple(sorted((anchor.entity_id, other.entity_id)))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            candidate = score_entity_pair(store, anchor, other)
            if candidate is not None:
                candidates.append(candidate)

    candidates.sort(key=lambda c: c.similarity_score, reverse=True)
    return candidates
