"""In-memory semantic data plane (Phase 1 local store)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from synapse.audit import AuditLog
from synapse.models import Claim, Conflict, Entity, Episode, Fact, RawObject


@dataclass
class SemanticStore:
    """Simple dict-backed store; replaceable by graph/object backends later."""

    raw_objects: dict[str, RawObject] = field(default_factory=dict)
    episodes: dict[str, Episode] = field(default_factory=dict)
    entities: dict[str, Entity] = field(default_factory=dict)
    facts: dict[str, Fact] = field(default_factory=dict)
    conflicts: dict[str, Conflict] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    # external_id key "system:id" -> entity_id
    entity_index: dict[str, str] = field(default_factory=dict)
    # canonical_name lower -> entity_id (same type preference handled by caller)
    name_index: dict[str, str] = field(default_factory=dict)
    # content_hash -> object_id for idempotent ingest
    content_hash_index: dict[str, str] = field(default_factory=dict)
    audit: AuditLog = field(default_factory=AuditLog)

    def put_raw(self, obj: RawObject) -> RawObject:
        self.raw_objects[obj.object_id] = obj
        self.content_hash_index[obj.content_hash] = obj.object_id
        return obj

    def get_raw_by_content_hash(self, content_hash: str) -> Optional[RawObject]:
        oid = self.content_hash_index.get(content_hash)
        return self.raw_objects.get(oid) if oid else None

    def episode_for_raw(self, raw_object_id: str) -> Optional[Episode]:
        for ep in self.episodes.values():
            if raw_object_id in ep.raw_object_ids:
                return ep
        return None

    def put_episode(self, episode: Episode) -> Episode:
        self.episodes[episode.episode_id] = episode
        return episode

    def put_entity(self, entity: Entity) -> Entity:
        self.entities[entity.entity_id] = entity
        # Index names to survivor when merged
        target_id = entity.merged_into or entity.entity_id
        if entity.status.value != "merged":
            if entity.canonical_name:
                self.name_index[entity.canonical_name.lower()] = entity.entity_id
            for alias in entity.aliases:
                self.name_index[alias.lower()] = entity.entity_id
        else:
            # Redirect old names to survivor
            if entity.canonical_name:
                self.name_index[entity.canonical_name.lower()] = target_id
            for alias in entity.aliases:
                self.name_index[alias.lower()] = target_id
        for ext in entity.external_ids:
            key = f"{ext.get('system', '')}:{ext.get('id', '')}"
            if key != ":":
                self.entity_index[key] = target_id if entity.status.value == "merged" else entity.entity_id
        return entity

    def put_fact(self, fact: Fact) -> Fact:
        self.facts[fact.fact_id] = fact
        return fact

    def put_conflict(self, conflict: Conflict) -> Conflict:
        self.conflicts[conflict.conflict_id] = conflict
        return conflict

    def put_claim(self, claim: Claim) -> Claim:
        self.claims[claim.claim_id] = claim
        return claim

    def get_entity_by_name(self, name: str) -> Optional[Entity]:
        eid = self.name_index.get(name.lower())
        if not eid:
            return None
        ent = self.entities.get(eid)
        if ent is None:
            return None
        # Follow merge redirect
        hops = 0
        while ent and ent.merged_into and hops < 8:
            ent = self.entities.get(ent.merged_into)
            hops += 1
        return ent

    def facts_for_entity(self, entity_id: str, predicate: Optional[str] = None) -> list[Fact]:
        out = [f for f in self.facts.values() if f.subject_entity_id == entity_id]
        if predicate is not None:
            out = [f for f in out if f.predicate == predicate]
        return out

    def open_conflicts_for_entity(self, entity_id: str) -> list[Conflict]:
        return [
            c
            for c in self.conflicts.values()
            if c.subject_entity_id == entity_id and c.status.value == "open"
        ]
