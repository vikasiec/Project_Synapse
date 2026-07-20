"""ABAC policy engine — security follows the block."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from synapse.models import Conflict, Entity, Episode, Fact, RawObject


@dataclass
class Principal:
    """Authenticated query principal with ABAC attributes."""

    principal_id: str
    attributes: set[str] = field(default_factory=set)

    @classmethod
    def from_tags(cls, principal_id: str, tags: Sequence[str]) -> Principal:
        return cls(principal_id=principal_id, attributes=set(tags))


def intersect_acl(tag_sets: Iterable[Sequence[str]]) -> set[str]:
    """
    Derived Fact Key = ACL_1 ∩ ACL_2 ∩ … ∩ ACL_N

    Empty input → empty set (deny by default).
    """
    iterator = iter(tag_sets)
    try:
        first = set(next(iterator))
    except StopIteration:
        return set()
    for tags in iterator:
        first.intersection_update(tags)
        if not first:
            break
    return first


def principal_may_access(principal: Principal, required_acl: set[str]) -> bool:
    """
    User must cover every required tag (superset).

    Empty required_acl means no derived rights survived intersection → deny.
    """
    if not required_acl:
        return False
    return required_acl.issubset(principal.attributes)


def filter_raw_objects(principal: Principal, objects: Sequence[RawObject]) -> list[RawObject]:
    """Drop raw objects the principal cannot see (per-object ACL)."""
    allowed: list[RawObject] = []
    for obj in objects:
        required = set(obj.acl_tags)
        if required and required.issubset(principal.attributes):
            allowed.append(obj)
    return allowed


def filter_facts(principal: Principal, facts: Sequence[Fact]) -> list[Fact]:
    """Drop facts whose ACL tags are not fully covered by the principal."""
    allowed: list[Fact] = []
    for fact in facts:
        required = set(fact.acl_tags)
        if required and required.issubset(principal.attributes):
            allowed.append(fact)
    return allowed


def filter_episodes(principal: Principal, episodes: Sequence[Episode]) -> list[Episode]:
    """Drop episodes the principal cannot see (per-episode ACL)."""
    allowed: list[Episode] = []
    for ep in episodes:
        required = set(ep.acl_tags)
        if required and required.issubset(principal.attributes):
            allowed.append(ep)
    return allowed


def filter_entities(principal: Principal, entities: Sequence[Entity]) -> list[Entity]:
    """Drop entities the principal cannot see (per-entity ACL)."""
    allowed: list[Entity] = []
    for ent in entities:
        required = set(ent.acl_tags)
        if required and required.issubset(principal.attributes):
            allowed.append(ent)
    return allowed


def filter_conflicts(
    principal: Principal, conflicts: Sequence[Conflict], facts_by_id: dict
) -> list[Conflict]:
    """
    A conflict is only visible if the principal can see every fact it's
    comparing -- a partial view (some competing values hidden) could
    mislead about what's actually in disagreement, so this is stricter
    than "can see at least one side."
    """
    allowed: list[Conflict] = []
    for c in conflicts:
        competing = [facts_by_id[fid] for fid in c.competing_fact_ids if fid in facts_by_id]
        if not competing:
            continue
        required = derived_acl_from_facts(competing)
        if principal_may_access(principal, required):
            allowed.append(c)
    return allowed


def derived_acl_from_raw(objects: Sequence[RawObject]) -> set[str]:
    return intersect_acl(obj.acl_tags for obj in objects)


def derived_acl_from_facts(facts: Sequence[Fact]) -> set[str]:
    return intersect_acl(f.acl_tags for f in facts)
