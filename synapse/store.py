"""In-memory semantic data plane (Phase 1 local store)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from synapse.audit import AuditLog
from synapse.models import Claim, Conflict, Entity, Episode, Fact, RawObject, new_id, utc_now_iso
from synapse.ontology import RejectedCandidate, RelationshipEdge
from synapse.workspace import DEFAULT_WORKSPACE_ID, DEFAULT_WORKSPACE_NAME, Workspace


@dataclass
class SemanticStore:
    """Simple dict-backed store; replaceable by graph/object backends later."""

    raw_objects: dict[str, RawObject] = field(default_factory=dict)
    episodes: dict[str, Episode] = field(default_factory=dict)
    entities: dict[str, Entity] = field(default_factory=dict)
    facts: dict[str, Fact] = field(default_factory=dict)
    conflicts: dict[str, Conflict] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    # Major Goal 4 / F-027: durable home for OntologyRegistry's curated
    # relationship edges + rejection log, so the Catalog survives a restart
    # under a SQLite-backed store instead of resetting every session.
    relationship_edges: dict[str, RelationshipEdge] = field(default_factory=dict)
    rejected_candidates: dict[str, RejectedCandidate] = field(default_factory=dict)
    # Schema View: durable canvas position per source_system, so a
    # deliberately-arranged schema diagram looks the same every visit
    # instead of resetting to a fresh auto-layout each time.
    schema_layout: dict[str, dict] = field(default_factory=dict)
    # Top-level project boundary: sources are imported into a workspace,
    # and a workspace's confirmed relationships are its schema. See
    # synapse/workspace.py.
    workspaces: dict[str, Workspace] = field(default_factory=dict)
    # external_id key "system:id" -> entity_id
    entity_index: dict[str, str] = field(default_factory=dict)
    # canonical_name lower -> entity_id (same type preference handled by caller)
    name_index: dict[str, str] = field(default_factory=dict)
    # (source_system, source_uri, content_hash) -> object_id for idempotent
    # connector replay. Identical bytes from different sources remain distinct
    # so provenance and ACL tags cannot be silently replaced by the first source.
    content_hash_index: dict[tuple[str, Optional[str], str], str] = field(default_factory=dict)
    # Monotonic in-process revision used to prevent stale query claims after
    # new raw/fact/conflict state is written.
    revision: int = 0
    audit: AuditLog = field(default_factory=AuditLog)

    def put_raw(self, obj: RawObject) -> RawObject:
        self.revision += 1
        self.raw_objects[obj.object_id] = obj
        key = (obj.source_system, obj.source_uri, obj.content_hash)
        self.content_hash_index[key] = obj.object_id
        return obj

    def get_raw_by_content_hash(
        self,
        content_hash: str,
        *,
        source_system: Optional[str] = None,
        source_uri: Optional[str] = None,
    ) -> Optional[RawObject]:
        """Find a replay duplicate within the same source/URI scope."""
        if source_system is None:
            # Preserve a safe read-only compatibility path for callers that
            # only know the hash: return a match only when it is unambiguous.
            matches = [
                oid
                for (src, uri, digest), oid in self.content_hash_index.items()
                if digest == content_hash
            ]
            if len(matches) != 1:
                return None
            oid = matches[0]
        else:
            oid = self.content_hash_index.get((source_system, source_uri, content_hash))
        return self.raw_objects.get(oid) if oid else None

    def episode_for_raw(self, raw_object_id: str) -> Optional[Episode]:
        for ep in self.episodes.values():
            if raw_object_id in ep.raw_object_ids:
                return ep
        return None

    def put_episode(self, episode: Episode) -> Episode:
        self.revision += 1
        self.episodes[episode.episode_id] = episode
        return episode

    def put_entity(self, entity: Entity) -> Entity:
        self.revision += 1
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
        self.revision += 1
        self.facts[fact.fact_id] = fact
        return fact

    def put_conflict(self, conflict: Conflict) -> Conflict:
        self.conflicts[conflict.conflict_id] = conflict
        return conflict

    def put_claim(self, claim: Claim) -> Claim:
        self.claims[claim.claim_id] = claim
        return claim

    def put_relationship_edge(self, edge: RelationshipEdge) -> RelationshipEdge:
        self.relationship_edges[edge.relationship_id] = edge
        return edge

    def delete_relationship_edge(self, relationship_id: str) -> None:
        self.relationship_edges.pop(relationship_id, None)

    def put_rejected_candidate(self, rejected: RejectedCandidate) -> RejectedCandidate:
        self.rejected_candidates[rejected.rejection_id] = rejected
        return rejected

    def put_layout_position(self, source_system: str, x: float, y: float) -> dict:
        entry = {"source_system": source_system, "x": x, "y": y}
        self.schema_layout[source_system] = entry
        return entry

    def put_workspace(self, workspace: Workspace) -> Workspace:
        self.workspaces[workspace.workspace_id] = workspace
        return workspace

    def ensure_default_workspace(self) -> Workspace:
        """Idempotent: already-landed (pre-workspace) data implicitly
        belongs to workspace_id="default" via RawObject's default field --
        this just makes sure that id resolves to a real, named Workspace
        row instead of a bare id with nothing behind it."""
        existing = self.workspaces.get(DEFAULT_WORKSPACE_ID)
        if existing is not None:
            return existing
        return self.put_workspace(Workspace(workspace_id=DEFAULT_WORKSPACE_ID, name=DEFAULT_WORKSPACE_NAME))

    def clone_workspace(
        self, source_workspace_id: str, new_name: str, description: str = "", *, ontology: Optional[object] = None
    ) -> Workspace:
        """"Save As" for a workspace: an independent, editable copy of
        every source it contains plus the confirmed relationships that
        connect them, under a brand-new workspace_id. source_system is
        the identity key everything else (relationships, schema_layout,
        profiling) is keyed on and is assumed globally unique -- so a
        clone must rename each copied source, not reuse the original
        name, or the two workspaces would collide on every downstream
        lookup that assumes one owner per source_system.

        The live app's confirmed-relationship reads (GET /v1/ontology,
        Schema/Catalog views) go through OntologyRegistry.relationships,
        an in-memory dict OntologyRegistry.accept_relationship() keeps in
        sync with this store's relationship_edges on every normal
        ACCEPT -- but that sync is one-directional (ontology -> store).
        Writing straight into self.relationship_edges here would silently
        desync from a live OntologyRegistry, so an optional `ontology`
        handle is accepted and updated the same way accept_relationship
        does, whenever the caller has one (the API route does)."""
        new_ws = Workspace.create(new_name, description)
        self.put_workspace(new_ws)
        suffix = new_ws.workspace_id[:8]

        source_raws = [r for r in self.raw_objects.values() if r.workspace_id == source_workspace_id]
        rename_map: dict[str, str] = {}
        for raw in source_raws:
            rename_map.setdefault(raw.source_system, f"{raw.source_system}_copy_{suffix}")

        for raw in source_raws:
            clone = RawObject.create(
                source_system=rename_map[raw.source_system],
                payload=raw.raw_payload,
                acl_tags=list(raw.acl_tags),
                source_uri=raw.source_uri,
                media_type=raw.media_type,
                sensitivity=raw.sensitivity,
                retention_class=raw.retention_class,
                workspace_id=new_ws.workspace_id,
            )
            self.put_raw(clone)

        def _remap(full_source_system: str) -> Optional[str]:
            base, sep, sub = full_source_system.partition("::")
            if base not in rename_map:
                return None
            return rename_map[base] + (sep + sub if sep else "")

        for edge in list(self.relationship_edges.values()):
            new_a = _remap(edge.source_a.get("source_system", ""))
            new_b = _remap(edge.source_b.get("source_system", ""))
            if new_a is None or new_b is None:
                continue
            new_edge = RelationshipEdge(
                relationship_id=new_id(),
                source_a={**edge.source_a, "source_system": new_a},
                source_b={**edge.source_b, "source_system": new_b},
                predicate=edge.predicate,
                tier=edge.tier,
                candidate_id=None,
                match_reasons=edge.match_reasons,
                similarity_score=edge.similarity_score,
                accepted_at=utc_now_iso(),
            )
            if ontology is not None:
                ontology.relationships[new_edge.relationship_id] = new_edge
            self.put_relationship_edge(new_edge)

        for full_source_system, entry in list(self.schema_layout.items()):
            new_full = _remap(full_source_system)
            if new_full is None:
                continue
            self.put_layout_position(new_full, entry["x"], entry["y"])

        return new_ws

    def workspace_for_source(self, source_system: str) -> Optional[str]:
        """Resolves a (possibly virtual "base::SEGMENT") source_system back
        to the workspace_id of any RawObject landed under its base name --
        used to derive which workspace(s) a relationship touches, and to
        scope /v1/explore listings, without storing workspace redundantly
        on every downstream record."""
        base = source_system.split("::", 1)[0]
        for raw in self.raw_objects.values():
            if raw.source_system == base:
                return raw.workspace_id
        return None

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

    def known_acl_domains(self) -> set[str]:
        """
        Every "domain:X" ACL tag actually present on landed raw objects.
        Generic, data-driven -- lets a demo/default viewer preset grant
        access to whatever domains actually exist in this store without a
        hardcoded domain-name list (Active_File.md row 12, Codex review:
        api.py's l1/l2 principal presets hardcoded domain:sre/revenue/
        identity, so a new pack's data -- e.g. domain:banking -- was
        invisible to the default UI viewer even though nothing else about
        it was domain-specific).
        """
        domains: set[str] = set()
        for raw in self.raw_objects.values():
            for tag in raw.acl_tags:
                if tag.startswith("domain:"):
                    domains.add(tag)
        return domains
