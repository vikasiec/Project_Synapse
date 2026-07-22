"""
SQLite-backed semantic store.

Persists all plane objects as JSON rows. Drop-in replacement for SemanticStore
for durable local Phase 1 runs.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional, Union

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
)
from synapse.ontology import RejectedCandidate, RelationshipEdge
from synapse.store import SemanticStore

PathLike = Union[str, Path]


class SqliteSemanticStore(SemanticStore):
    """
    Extends in-memory store with SQLite durability.

    On put_*: write-through to SQLite + memory.
    On init: load all rows into memory indexes.

    Thread-safe for ThreadingHTTPServer (check_same_thread=False + lock).
    """

    def __init__(self, db_path: PathLike) -> None:
        super().__init__()
        self.db_path = Path(db_path)
        if self.db_path.parent and str(self.db_path.parent) not in ("", "."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # HTTP server uses a thread pool — allow cross-thread use under a lock
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._load_all()
        # Write-through new audit events after load (load does not re-fire sink)
        self.audit.set_sink(
            lambda event: self._upsert("audit_events", event.event_id, event.to_dict())
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_objects (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conflicts (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS relationship_edges (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rejected_candidates (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def _upsert(self, table: str, obj_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                f"INSERT INTO {table} (id, data) VALUES (?, ?) "
                f"ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (obj_id, json.dumps(data)),
            )
            self._conn.commit()

    def _load_all(self) -> None:
        with self._lock:
            rows_raw = list(self._conn.execute("SELECT data FROM raw_objects"))
            rows_ep = list(self._conn.execute("SELECT data FROM episodes"))
            rows_ent = list(self._conn.execute("SELECT data FROM entities"))
            rows_fact = list(self._conn.execute("SELECT data FROM facts"))
            rows_conf = list(self._conn.execute("SELECT data FROM conflicts"))
            rows_claim = list(self._conn.execute("SELECT data FROM claims"))
            rows_audit = list(
                self._conn.execute("SELECT data FROM audit_events ORDER BY rowid")
            )
            rows_rel = list(self._conn.execute("SELECT data FROM relationship_edges"))
            rows_rej = list(self._conn.execute("SELECT data FROM rejected_candidates"))
        for row in rows_raw:
            super().put_raw(_raw_from_dict(json.loads(row["data"])))
        for row in rows_ep:
            super().put_episode(_episode_from_dict(json.loads(row["data"])))
        for row in rows_ent:
            super().put_entity(_entity_from_dict(json.loads(row["data"])))
        for row in rows_fact:
            super().put_fact(_fact_from_dict(json.loads(row["data"])))
        for row in rows_conf:
            super().put_conflict(_conflict_from_dict(json.loads(row["data"])))
        for row in rows_claim:
            super().put_claim(_claim_from_dict(json.loads(row["data"])))
        for row in rows_rel:
            super().put_relationship_edge(_relationship_edge_from_dict(json.loads(row["data"])))
        for row in rows_rej:
            super().put_rejected_candidate(_rejected_candidate_from_dict(json.loads(row["data"])))
        for row in rows_audit:
            from synapse.audit import AuditEvent

            d = json.loads(row["data"])
            self.audit.events.append(
                AuditEvent(
                    event_id=d["event_id"],
                    event_type=d["event_type"],
                    timestamp=d["timestamp"],
                    actor=d["actor"],
                    detail=dict(d.get("detail") or {}),
                )
            )

    def put_raw(self, obj: RawObject) -> RawObject:
        super().put_raw(obj)
        self._upsert("raw_objects", obj.object_id, obj.to_dict())
        return obj

    def put_episode(self, episode: Episode) -> Episode:
        super().put_episode(episode)
        self._upsert("episodes", episode.episode_id, episode.to_dict())
        return episode

    def put_entity(self, entity: Entity) -> Entity:
        super().put_entity(entity)
        self._upsert("entities", entity.entity_id, entity.to_dict())
        return entity

    def put_fact(self, fact: Fact) -> Fact:
        super().put_fact(fact)
        self._upsert("facts", fact.fact_id, fact.to_dict())
        return fact

    def put_conflict(self, conflict: Conflict) -> Conflict:
        super().put_conflict(conflict)
        self._upsert("conflicts", conflict.conflict_id, conflict.to_dict())
        return conflict

    def put_claim(self, claim: Claim) -> Claim:
        super().put_claim(claim)
        self._upsert("claims", claim.claim_id, claim.to_dict())
        return claim

    def put_relationship_edge(self, edge: RelationshipEdge) -> RelationshipEdge:
        super().put_relationship_edge(edge)
        self._upsert("relationship_edges", edge.relationship_id, edge.to_dict())
        return edge

    def delete_relationship_edge(self, relationship_id: str) -> None:
        super().delete_relationship_edge(relationship_id)
        with self._lock:
            self._conn.execute("DELETE FROM relationship_edges WHERE id = ?", (relationship_id,))
            self._conn.commit()

    def put_rejected_candidate(self, rejected: RejectedCandidate) -> RejectedCandidate:
        super().put_rejected_candidate(rejected)
        self._upsert("rejected_candidates", rejected.rejection_id, rejected.to_dict())
        return rejected

    def persist_audit_tail(self) -> None:
        """Flush any in-memory audit events not yet written."""
        with self._lock:
            existing = {
                row["id"]
                for row in self._conn.execute("SELECT id FROM audit_events")
            }
        for event in self.audit.events:
            if event.event_id not in existing:
                self._upsert("audit_events", event.event_id, event.to_dict())



def _raw_from_dict(d: dict[str, Any]) -> RawObject:
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


def _episode_from_dict(d: dict[str, Any]) -> Episode:
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


def _entity_from_dict(d: dict[str, Any]) -> Entity:
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
        ontology_type=d.get("ontology_type"),
        ontology_layer=d.get("ontology_layer"),
    )


def _fact_from_dict(d: dict[str, Any]) -> Fact:
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


def _conflict_from_dict(d: dict[str, Any]) -> Conflict:
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


def _relationship_edge_from_dict(d: dict[str, Any]) -> RelationshipEdge:
    return RelationshipEdge(
        relationship_id=d["relationship_id"],
        source_a=dict(d["source_a"]),
        source_b=dict(d["source_b"]),
        predicate=d["predicate"],
        tier=d.get("tier", "L1"),
        candidate_id=d.get("candidate_id"),
        match_reasons=tuple(d.get("match_reasons") or ()),
        similarity_score=d.get("similarity_score"),
        accepted_at=d.get("accepted_at", ""),
    )


def _rejected_candidate_from_dict(d: dict[str, Any]) -> RejectedCandidate:
    return RejectedCandidate(
        candidate_id=d["candidate_id"],
        source_a=dict(d["source_a"]),
        source_b=dict(d["source_b"]),
        reason=d.get("reason", ""),
        rejected_at=d.get("rejected_at", ""),
        rejection_id=d.get("rejection_id", d["candidate_id"]),
    )


def _claim_from_dict(d: dict[str, Any]) -> Claim:
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
