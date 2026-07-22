"""
Entity resolution (Phase 1).

- Blocking keys: normalized name, external_id
- Merge creates redirect (merged_into); facts re-point to survivor
- Never deletes history
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from synapse.models import Entity, EntityStatus
from synapse.ontology import OntologyRegistry
from synapse.store import SemanticStore

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_AUTHORITY_URI_PREFIXES = ("urn:oid:", "urn:uuid:", "urn:", "https://", "http://")


def normalize_name(name: str) -> str:
    """Cheap blocking key: lowercase, strip non-alnum."""
    return _NON_ALNUM.sub("", name.lower().strip())


def normalize_authority(raw: Optional[str]) -> str:
    """
    Normalize an assigning-authority string for comparison, not storage.

    The same real-world authority is represented differently across
    formats -- HL7v2 PID-3.4 gives a bare namespace-id ("HIS"), FHIR
    Identifier.system gives a URI wrapping the same code
    ("urn:oid:HIS"). Comparing raw strings would treat every FHIR/HL7
    pair for the same facility as different authorities and silently
    fracture the already-proven cross-format identity convergence.
    Strip common URI scheme prefixes and take the last path segment so
    both representations collapse to the same key; anything unrecognized
    just gets lowercased, which is a safe no-op for bare HL7-style codes.
    """
    if not raw:
        return ""
    v = raw.strip()
    for prefix in _AUTHORITY_URI_PREFIXES:
        if v.lower().startswith(prefix):
            v = v[len(prefix):]
            break
    v = v.rstrip("/")
    if "/" in v:
        v = v.rsplit("/", 1)[-1]
    return v.lower()


@dataclass
class MergeResult:
    survivor: Entity
    loser: Entity
    facts_rewritten: int


class EntityResolutionService:
    def __init__(
        self,
        store: SemanticStore,
        *,
        ontology: Optional[OntologyRegistry] = None,
    ) -> None:
        self.store = store
        self.ontology = ontology or OntologyRegistry.default()
        # Major Goal 4, task 2: confirmed schema-field relationships
        # (source_system, field_name) pairs from an accepted SAME_ENTITY_AS
        # curation decision -- immediately available as ER blocking metadata
        # for future entities sourced from these two systems. Deliberately
        # does not retroactively merge/re-block existing entities on name
        # alone; that remains suggest_merges()'s existing, separately-vetted
        # blocking strategy. This records *that* two source fields are known
        # to refer to the same real-world concept, for the transitive
        # learning engine (Major Goal 4, task 3) to consume.
        self.linked_schema_fields: set[tuple[str, str, str, str]] = set()

    def link_schema_fields(self, source_a: dict[str, str], source_b: dict[str, str]) -> None:
        key = (
            source_a.get("source_system", ""),
            source_a.get("field_name", ""),
            source_b.get("source_system", ""),
            source_b.get("field_name", ""),
        )
        self.linked_schema_fields.add(key)

    def linked_sources_for(self, source_system: str) -> set[str]:
        """All source systems already confirmed as SAME_ENTITY_AS-linked to
        the given one -- the lookup the transitive learning engine walks."""
        linked: set[str] = set()
        for a_sys, _a_field, b_sys, _b_field in self.linked_schema_fields:
            if a_sys == source_system:
                linked.add(b_sys)
            elif b_sys == source_system:
                linked.add(a_sys)
        return linked

    def resolve_id(self, entity_id: str, *, max_hops: int = 8) -> str:
        """Follow merge redirects to the active survivor."""
        seen: set[str] = set()
        current = entity_id
        for _ in range(max_hops):
            if current in seen:
                break
            seen.add(current)
            ent = self.store.entities.get(current)
            if ent is None:
                return current
            if ent.status == EntityStatus.MERGED and ent.merged_into:
                current = ent.merged_into
                continue
            return current
        return current

    def get_active(self, entity_id: str) -> Optional[Entity]:
        rid = self.resolve_id(entity_id)
        ent = self.store.entities.get(rid)
        if ent and ent.status == EntityStatus.ACTIVE:
            return ent
        return ent

    def find_by_normalized_name(
        self,
        name: str,
        *,
        entity_type: Optional[str] = None,
    ) -> Optional[Entity]:
        key = normalize_name(name)
        for ent in self.store.entities.values():
            if ent.status != EntityStatus.ACTIVE:
                continue
            if entity_type and not self.ontology.types_match(ent.entity_type, entity_type):
                # Also allow match on ontology_type family
                if ent.ontology_type and self.ontology.types_match(
                    ent.ontology_type, entity_type
                ):
                    pass
                else:
                    continue
            candidates = [ent.canonical_name or ""] + list(ent.aliases)
            if any(normalize_name(c) == key for c in candidates if c):
                return ent
        return None

    def find_by_external_id(self, system: str, ext_id: str) -> Optional[Entity]:
        key = f"{system}:{ext_id}"
        eid = self.store.entity_index.get(key)
        if not eid:
            return None
        return self.get_active(eid)

    def find_by_external_id_value(
        self,
        ext_id: str,
        *,
        entity_type: Optional[str] = None,
        authority: Optional[str] = None,
    ) -> Optional[Entity]:
        """
        Cross-source blocking by the ID value alone, ignoring which source
        reported it. Safe for strict-identity types (e.g. patient_id) where
        the ID itself is the authoritative identifier — unlike name, which
        two different real people can share.

        `authority` scopes this further by assigning authority (HL7v2
        PID-3's assigning-authority component / FHIR Identifier.system):
        two different facilities can independently issue the same bare ID
        (e.g. both call a patient "P001") to two different real people.
        When both sides state a known, differing authority, the match is
        rejected even though the bare ID matches. When either side has no
        recorded authority (the common case for CSV-sourced identifiers,
        which have no assigning-authority concept), matching stays
        permissive by bare ID, preserving the existing cross-format
        convergence proof.
        """
        for ent in self.store.entities.values():
            if ent.status != EntityStatus.ACTIVE:
                continue
            if entity_type and ent.entity_type != entity_type:
                continue
            for x in ent.external_ids:
                if x.get("id") != ext_id:
                    continue
                existing_authority = normalize_authority(x.get("authority"))
                incoming_authority = normalize_authority(authority)
                if incoming_authority and existing_authority and existing_authority != incoming_authority:
                    continue
                return ent
        return None

    def get_or_create(
        self,
        entity_type: str,
        canonical_name: str,
        *,
        source_system: str,
        acl_tags: list[str],
        external_id: Optional[str] = None,
        trust_score: float = 0.7,
        domain: Optional[str] = None,
        identifier_authority: Optional[str] = None,
    ) -> Entity:
        """
        Resolve-or-create with name + external_id blocking.
        Ontology governs storage type + L0/L1 tags (H8).

        `identifier_authority` (optional) is the assigning-authority scope
        for `external_id` — HL7v2 PID-3's assigning-authority component or
        FHIR Identifier.system — passed through to the strict-identity
        cross-source blocking check. Omit for sources with no
        assigning-authority concept (e.g. plain CSV columns).
        """
        governed = self.ontology.govern_extract(entity_type, domain=domain)
        storage_type = governed.storage_type

        ot = self.ontology.get(governed.ontology_type) if governed.ontology_type else None
        strict_identity = bool(ot and ot.strict_identity)

        if external_id:
            by_ext = self.find_by_external_id(source_system, external_id)
            if by_ext and strict_identity and identifier_authority:
                # The exact (source_system, external_id) shortcut above
                # assumes the same source_system label never reissues the
                # same bare ID to a different real-world entity. That's not
                # actually guaranteed -- one LIS/connector label can serve
                # multiple facilities with overlapping ID spaces. Only
                # trust the shortcut if this specific (system, id) pairing
                # was never previously recorded under a genuinely different
                # authority; otherwise fall through to the authority-aware
                # cross-source check below.
                recorded_conflict = any(
                    x.get("system") == source_system
                    and x.get("id") == external_id
                    and x.get("authority")
                    and normalize_authority(x.get("authority"))
                    != normalize_authority(identifier_authority)
                    for x in by_ext.external_ids
                )
                if recorded_conflict:
                    by_ext = None
            if by_ext:
                self._widen(
                    by_ext,
                    acl_tags,
                    canonical_name,
                    source_system,
                    external_id,
                    ontology_type=governed.ontology_type,
                    ontology_layer=governed.ontology_layer,
                    identifier_authority=identifier_authority,
                )
                return by_ext
            if strict_identity:
                # A name match alone must never merge two different real
                # people (e.g. two patients both named "Michael Taylor").
                # Block on the ID value itself instead — safe because the ID
                # is authoritative, unlike a name two people can share.
                by_ext_val = self.find_by_external_id_value(
                    external_id, entity_type=storage_type, authority=identifier_authority
                )
                if by_ext_val:
                    self._widen(
                        by_ext_val,
                        acl_tags,
                        canonical_name,
                        source_system,
                        external_id,
                        ontology_type=governed.ontology_type,
                        ontology_layer=governed.ontology_layer,
                        identifier_authority=identifier_authority,
                    )
                    return by_ext_val
                by_name = None
            else:
                by_name = self.find_by_normalized_name(
                    canonical_name, entity_type=storage_type
                )
        else:
            by_name = self.find_by_normalized_name(
                canonical_name, entity_type=storage_type
            )
        if by_name:
            self._widen(
                by_name,
                acl_tags,
                canonical_name,
                source_system,
                external_id or canonical_name,
                ontology_type=governed.ontology_type,
                ontology_layer=governed.ontology_layer,
                identifier_authority=identifier_authority,
            )
            return by_name

        # L2 soft types get slightly lower trust until promoted
        if governed.ontology_layer == "L2":
            trust_score = min(trust_score, 0.55)

        ext_entry: dict[str, str] = {
            "system": source_system,
            "id": external_id or canonical_name,
        }
        if identifier_authority:
            ext_entry["authority"] = identifier_authority

        entity = Entity.create(
            entity_type=storage_type,
            canonical_name=canonical_name,
            aliases=[canonical_name],
            external_ids=[ext_entry],
            trust_score=trust_score,
            acl_tags=list(acl_tags),
            ontology_type=governed.ontology_type,
            ontology_layer=governed.ontology_layer,
        )
        return self.store.put_entity(entity)

    def _widen(
        self,
        entity: Entity,
        acl_tags: list[str],
        alias: str,
        source_system: str,
        external_id: str,
        *,
        ontology_type: Optional[str] = None,
        ontology_layer: Optional[str] = None,
        identifier_authority: Optional[str] = None,
    ) -> None:
        for t in acl_tags:
            if t not in entity.acl_tags:
                entity.acl_tags.append(t)
        if alias and alias not in entity.aliases:
            entity.aliases.append(alias)
        ext: dict[str, str] = {"system": source_system, "id": external_id}
        if identifier_authority:
            ext["authority"] = identifier_authority
        if ext not in entity.external_ids:
            entity.external_ids.append(ext)
        # Upgrade ontology tag when domain L1 is more specific than current
        if ontology_type and ontology_layer:
            if not entity.ontology_type or (
                entity.ontology_layer == "L0" and ontology_layer == "L1"
            ):
                entity.ontology_type = ontology_type
                entity.ontology_layer = ontology_layer
        self.store.put_entity(entity)

    def merge(
        self,
        survivor_id: str,
        loser_id: str,
        *,
        adjudicator: str,
        reason: str,
    ) -> MergeResult:
        """
        Merge loser into survivor.
        - loser.status = merged, loser.merged_into = survivor
        - facts on loser re-point subject to survivor
        - name/alias/external_id indexes update via put_entity
        """
        survivor_id = self.resolve_id(survivor_id)
        loser_id = self.resolve_id(loser_id)
        if survivor_id == loser_id:
            raise ValueError("Cannot merge an entity into itself")

        survivor = self.store.entities.get(survivor_id)
        loser = self.store.entities.get(loser_id)
        if not survivor or not loser:
            raise ValueError("Unknown entity id for merge")
        if survivor.status != EntityStatus.ACTIVE:
            raise ValueError("Survivor must be active")

        # Transfer identity signals
        if loser.canonical_name and loser.canonical_name not in survivor.aliases:
            survivor.aliases.append(loser.canonical_name)
        for a in loser.aliases:
            if a not in survivor.aliases:
                survivor.aliases.append(a)
        for ext in loser.external_ids:
            if ext not in survivor.external_ids:
                survivor.external_ids.append(ext)
        for t in loser.acl_tags:
            if t not in survivor.acl_tags:
                survivor.acl_tags.append(t)
        survivor.trust_score = max(survivor.trust_score, loser.trust_score)

        rewritten = 0
        for fact in list(self.store.facts.values()):
            if fact.subject_entity_id == loser_id:
                fact.subject_entity_id = survivor_id
                self.store.put_fact(fact)
                rewritten += 1

        # Conflicts on loser move subject
        for conflict in list(self.store.conflicts.values()):
            if conflict.subject_entity_id == loser_id:
                conflict.subject_entity_id = survivor_id
                self.store.put_conflict(conflict)

        loser.status = EntityStatus.MERGED
        loser.merged_into = survivor_id
        self.store.put_entity(loser)
        self.store.put_entity(survivor)

        self.store.audit.record(
            "er.merge",
            actor=adjudicator,
            detail={
                "survivor_id": survivor_id,
                "loser_id": loser_id,
                "facts_rewritten": rewritten,
                "reason": reason,
            },
        )
        return MergeResult(survivor=survivor, loser=loser, facts_rewritten=rewritten)

    def suggest_merges(self, *, entity_type: Optional[str] = None) -> list[dict]:
        """Pair active entities that share a normalized name (type-scoped)."""
        buckets: dict[str, list[Entity]] = {}
        for ent in self.store.entities.values():
            if ent.status != EntityStatus.ACTIVE:
                continue
            if entity_type and ent.entity_type != entity_type:
                continue
            names = [ent.canonical_name or ""] + list(ent.aliases)
            keys = {normalize_name(n) for n in names if n}
            for k in keys:
                buckets.setdefault(f"{ent.entity_type}:{k}", []).append(ent)

        suggestions = []
        seen_pairs: set[tuple[str, str]] = set()
        for key, group in buckets.items():
            # unique by id
            uniq: dict[str, Entity] = {e.entity_id: e for e in group}
            ids = list(uniq.keys())
            if len(ids) < 2:
                continue
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = sorted([ids[i], ids[j]])
                    if (a, b) in seen_pairs:
                        continue
                    seen_pairs.add((a, b))
                    suggestions.append(
                        {
                            "blocking_key": key,
                            "entity_a": uniq[a].to_dict(),
                            "entity_b": uniq[b].to_dict(),
                        }
                    )
        return suggestions
