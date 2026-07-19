"""Canonical data contracts for the Synapse semantic data plane."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def content_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EntityStatus(str, Enum):
    ACTIVE = "active"
    MERGED = "merged"
    DEPRECATED = "deprecated"


class ConflictStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ACCEPTED_PLURAL = "accepted_plural"


@dataclass
class RawObject:
    """Immutable landing-zone record (system of record for bytes)."""

    object_id: str
    source_system: str
    content_hash: str
    ingested_at: str
    bytes_ref: str
    acl_tags: list[str]
    raw_payload: str
    source_uri: Optional[str] = None
    media_type: str = "text/plain"
    sensitivity: str = "internal"
    retention_class: str = "standard"

    @classmethod
    def create(
        cls,
        source_system: str,
        payload: str,
        acl_tags: list[str],
        *,
        source_uri: Optional[str] = None,
        media_type: str = "text/plain",
        sensitivity: str = "internal",
        retention_class: str = "standard",
        ingested_at: Optional[str] = None,
    ) -> RawObject:
        h = content_hash(payload)
        return cls(
            object_id=new_id(),
            source_system=source_system,
            content_hash=h,
            ingested_at=ingested_at or utc_now_iso(),
            bytes_ref=f"mem://raw_landing/{h}",
            acl_tags=list(acl_tags),
            raw_payload=payload,
            source_uri=source_uri,
            media_type=media_type,
            sensitivity=sensitivity,
            retention_class=retention_class,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Episode:
    """Prepared unit derived from one or more raw objects (schema-on-read input)."""

    episode_id: str
    raw_object_ids: list[str]
    domain: str
    prep_pipeline_version: str
    acl_tags: list[str]
    payload_text: str
    time_span_start: Optional[str] = None
    time_span_end: Optional[str] = None
    quality_signals: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls,
        raw: RawObject,
        *,
        domain: str,
        prep_pipeline_version: str = "data-juicer-sim/0.1",
        quality_signals: Optional[dict[str, Any]] = None,
    ) -> Episode:
        return cls(
            episode_id=new_id(),
            raw_object_ids=[raw.object_id],
            domain=domain,
            prep_pipeline_version=prep_pipeline_version,
            acl_tags=list(raw.acl_tags),
            payload_text=raw.raw_payload,
            time_span_start=raw.ingested_at,
            time_span_end=raw.ingested_at,
            quality_signals=quality_signals or {"token_estimate": max(1, len(raw.raw_payload.split()))},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Entity:
    entity_id: str
    entity_type: str
    status: EntityStatus = EntityStatus.ACTIVE
    canonical_name: Optional[str] = None
    aliases: list[str] = field(default_factory=list)
    external_ids: list[dict[str, str]] = field(default_factory=list)
    trust_score: float = 0.5
    acl_tags: list[str] = field(default_factory=list)
    # If status=merged, points at surviving entity (stable redirect; never delete history)
    merged_into: Optional[str] = None
    # H8 ontology tags (load-bearing for ranking/scope; entity_type remains ER key)
    ontology_type: Optional[str] = None
    ontology_layer: Optional[str] = None

    @classmethod
    def create(
        cls,
        entity_type: str,
        canonical_name: str,
        *,
        aliases: Optional[list[str]] = None,
        external_ids: Optional[list[dict[str, str]]] = None,
        trust_score: float = 0.5,
        acl_tags: Optional[list[str]] = None,
        entity_id: Optional[str] = None,
        ontology_type: Optional[str] = None,
        ontology_layer: Optional[str] = None,
    ) -> Entity:
        return cls(
            entity_id=entity_id or new_id(),
            entity_type=entity_type,
            canonical_name=canonical_name,
            aliases=list(aliases or []),
            external_ids=list(external_ids or []),
            trust_score=min(max(trust_score, 0.0), 1.0),
            acl_tags=list(acl_tags or []),
            merged_into=None,
            ontology_type=ontology_type,
            ontology_layer=ontology_layer,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class Fact:
    fact_id: str
    subject_entity_id: str
    predicate: str
    object: Any
    confidence: float
    evidence_refs: list[str]
    source_system: str
    acl_tags: list[str]
    valid_from: str
    valid_to: Optional[str] = None
    extractor_version: str = "rule-extractor/0.1"

    @classmethod
    def create(
        cls,
        subject_entity_id: str,
        predicate: str,
        obj: Any,
        *,
        confidence: float,
        evidence_refs: list[str],
        source_system: str,
        acl_tags: list[str],
        valid_from: Optional[str] = None,
        extractor_version: str = "rule-extractor/0.1",
    ) -> Fact:
        return cls(
            fact_id=new_id(),
            subject_entity_id=subject_entity_id,
            predicate=predicate,
            object=obj,
            confidence=min(max(confidence, 0.0), 1.0),
            evidence_refs=list(evidence_refs),
            source_system=source_system,
            acl_tags=list(acl_tags),
            valid_from=valid_from or utc_now_iso(),
            extractor_version=extractor_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConflictResolution:
    method: str
    chosen_fact_id: Optional[str] = None
    adjudicator: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class Conflict:
    conflict_id: str
    subject_entity_id: str
    predicate: str
    competing_fact_ids: list[str]
    status: ConflictStatus = ConflictStatus.OPEN
    resolution: Optional[ConflictResolution] = None

    @classmethod
    def open(
        cls,
        subject_entity_id: str,
        predicate: str,
        competing_fact_ids: list[str],
    ) -> Conflict:
        return cls(
            conflict_id=new_id(),
            subject_entity_id=subject_entity_id,
            predicate=predicate,
            competing_fact_ids=list(competing_fact_ids),
            status=ConflictStatus.OPEN,
        )

    def to_dict(self) -> dict[str, Any]:
        d = {
            "conflict_id": self.conflict_id,
            "subject_entity_id": self.subject_entity_id,
            "predicate": self.predicate,
            "competing_fact_ids": self.competing_fact_ids,
            "status": self.status.value,
            "resolution": asdict(self.resolution) if self.resolution else None,
        }
        return d


@dataclass
class Claim:
    """Query-time answer packet with citations and uncertainty."""

    claim_id: str
    statement: str
    supporting_fact_ids: list[str]
    raw_citations: list[str]
    confidence: float
    uncertainty_notes: list[str] = field(default_factory=list)
    policy_filtered: bool = False
    conflict_ids: list[str] = field(default_factory=list)
    route_used: Optional[str] = None
    idf: Optional[float] = None

    @classmethod
    def create(
        cls,
        statement: str,
        *,
        supporting_fact_ids: list[str],
        raw_citations: list[str],
        confidence: float,
        uncertainty_notes: Optional[list[str]] = None,
        policy_filtered: bool = False,
        conflict_ids: Optional[list[str]] = None,
        route_used: Optional[str] = None,
        idf: Optional[float] = None,
    ) -> Claim:
        return cls(
            claim_id=new_id(),
            statement=statement,
            supporting_fact_ids=list(supporting_fact_ids),
            raw_citations=list(raw_citations),
            confidence=min(max(confidence, 0.0), 1.0),
            uncertainty_notes=list(uncertainty_notes or []),
            policy_filtered=policy_filtered,
            conflict_ids=list(conflict_ids or []),
            route_used=route_used,
            idf=idf,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
