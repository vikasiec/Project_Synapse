"""JSON snapshot export/import for the semantic store (portable backup)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from synapse.models import (
    Claim,
    Conflict,
    ConflictResolution,
    ConflictStatus,
    Entity,
    EntityStatus,
    Episode,
    Fact,
    RawObject,
    utc_now_iso,
)
from synapse.store import SemanticStore

PathLike = Union[str, Path]
SNAPSHOT_VERSION = 1


def export_store(store: SemanticStore) -> dict[str, Any]:
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "exported_at": utc_now_iso(),
        "raw_objects": [o.to_dict() for o in store.raw_objects.values()],
        "episodes": [e.to_dict() for e in store.episodes.values()],
        "entities": [e.to_dict() for e in store.entities.values()],
        "facts": [f.to_dict() for f in store.facts.values()],
        "conflicts": [c.to_dict() for c in store.conflicts.values()],
        "claims": [c.to_dict() for c in store.claims.values()],
        "audit": store.audit.to_list(),
    }


def export_store_to_file(store: SemanticStore, path: PathLike) -> Path:
    p = Path(path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)
    data = export_store(store)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def import_store(data: dict[str, Any], store: SemanticStore | None = None) -> SemanticStore:
    """Load snapshot into store (default: fresh memory store). Does not clear existing if provided."""
    target = store if store is not None else SemanticStore()
    version = data.get("snapshot_version", 0)
    if version > SNAPSHOT_VERSION:
        raise ValueError(f"Unsupported snapshot_version={version}")

    for d in data.get("raw_objects", []):
        target.put_raw(_raw(d))
    for d in data.get("episodes", []):
        target.put_episode(_episode(d))
    for d in data.get("entities", []):
        target.put_entity(_entity(d))
    for d in data.get("facts", []):
        target.put_fact(_fact(d))
    for d in data.get("conflicts", []):
        target.put_conflict(_conflict(d))
    for d in data.get("claims", []):
        target.put_claim(_claim(d))

    # Audit is append-only replay (optional)
    from synapse.audit import AuditEvent

    for d in data.get("audit", []):
        target.audit.events.append(
            AuditEvent(
                event_id=d["event_id"],
                event_type=d["event_type"],
                timestamp=d["timestamp"],
                actor=d["actor"],
                detail=dict(d.get("detail") or {}),
            )
        )

    target.audit.record(
        "store.import",
        actor="system:import",
        detail={
            "raw": len(data.get("raw_objects", [])),
            "entities": len(data.get("entities", [])),
            "facts": len(data.get("facts", [])),
        },
    )
    return target


def import_store_from_file(path: PathLike, store: SemanticStore | None = None) -> SemanticStore:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return import_store(data, store=store)


def _raw(d: dict[str, Any]) -> RawObject:
    return RawObject(
        object_id=d["object_id"],
        source_system=d["source_system"],
        content_hash=d["content_hash"],
        ingested_at=d["ingested_at"],
        bytes_ref=d["bytes_ref"],
        acl_tags=list(d.get("acl_tags", [])),
        raw_payload=d["raw_payload"],
        source_uri=d.get("source_uri"),
        media_type=d.get("media_type", "text/plain"),
        sensitivity=d.get("sensitivity", "internal"),
        retention_class=d.get("retention_class", "standard"),
    )


def _episode(d: dict[str, Any]) -> Episode:
    return Episode(
        episode_id=d["episode_id"],
        raw_object_ids=list(d["raw_object_ids"]),
        domain=d["domain"],
        prep_pipeline_version=d["prep_pipeline_version"],
        acl_tags=list(d.get("acl_tags", [])),
        payload_text=d["payload_text"],
        time_span_start=d.get("time_span_start"),
        time_span_end=d.get("time_span_end"),
        quality_signals=dict(d.get("quality_signals") or {}),
        pipeline_version_history=list(
            d.get("pipeline_version_history") or [d["prep_pipeline_version"]]
        ),
    )


def _entity(d: dict[str, Any]) -> Entity:
    return Entity(
        entity_id=d["entity_id"],
        entity_type=d["entity_type"],
        status=EntityStatus(d.get("status", "active")),
        canonical_name=d.get("canonical_name"),
        aliases=list(d.get("aliases") or []),
        external_ids=list(d.get("external_ids") or []),
        trust_score=float(d.get("trust_score", 0.5)),
        acl_tags=list(d.get("acl_tags") or []),
        merged_into=d.get("merged_into"),
    )


def _fact(d: dict[str, Any]) -> Fact:
    return Fact(
        fact_id=d["fact_id"],
        subject_entity_id=d["subject_entity_id"],
        predicate=d["predicate"],
        object=d["object"],
        confidence=float(d["confidence"]),
        evidence_refs=list(d["evidence_refs"]),
        source_system=d["source_system"],
        acl_tags=list(d.get("acl_tags") or []),
        valid_from=d["valid_from"],
        valid_to=d.get("valid_to"),
        extractor_version=d.get("extractor_version", "rule-extractor/0.1"),
    )


def _conflict(d: dict[str, Any]) -> Conflict:
    res = None
    if d.get("resolution"):
        r = d["resolution"]
        res = ConflictResolution(
            method=r.get("method", "human_pin"),
            chosen_fact_id=r.get("chosen_fact_id"),
            adjudicator=r.get("adjudicator"),
            reason=r.get("reason"),
        )
    return Conflict(
        conflict_id=d["conflict_id"],
        subject_entity_id=d["subject_entity_id"],
        predicate=d["predicate"],
        competing_fact_ids=list(d["competing_fact_ids"]),
        status=ConflictStatus(d.get("status", "open")),
        resolution=res,
    )


def _claim(d: dict[str, Any]) -> Claim:
    return Claim(
        claim_id=d["claim_id"],
        statement=d["statement"],
        supporting_fact_ids=list(d.get("supporting_fact_ids") or []),
        raw_citations=list(d.get("raw_citations") or []),
        confidence=float(d["confidence"]),
        uncertainty_notes=list(d.get("uncertainty_notes") or []),
        policy_filtered=bool(d.get("policy_filtered", False)),
        conflict_ids=list(d.get("conflict_ids") or []),
        route_used=d.get("route_used"),
        idf=d.get("idf"),
    )
