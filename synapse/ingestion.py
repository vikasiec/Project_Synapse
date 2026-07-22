"""Ingest plane: land raw objects and build episodes (Data-Juicer-class prep)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from synapse.models import Episode, RawObject, content_hash
from synapse.operators import OperatorPipeline
from synapse.store import SemanticStore


@dataclass
class IngestResult:
    raw: RawObject
    episode: Episode
    deduplicated: bool = False
    dropped: bool = False
    drop_reason: Optional[str] = None
    prep_ops: list[str] | None = None


class IngestionService:
    """
    Prep pipeline:
      raw bytes → Data-Juicer-lite operators → content hash → episode

    Idempotent: same content_hash returns existing raw+episode without duplicate rows.
    """

    def __init__(
        self,
        store: SemanticStore,
        *,
        domain: str = "infra_ops",
        pipeline: Optional[OperatorPipeline] = None,
    ) -> None:
        self.store = store
        self.domain = domain
        self.pipeline = pipeline or OperatorPipeline()
        self.pipeline_version = f"data-juicer-lite/{len(self.pipeline.ops)}ops"

    def land(
        self,
        source_system: str,
        payload: str,
        acl_tags: list[str],
        *,
        source_uri: Optional[str] = None,
        sensitivity: str = "internal",
        actor: str = "system:ingest",
        workspace_id: str = "default",
    ) -> IngestResult:
        # Run prep operators first (blueprint: normalize without warehouse schema)
        prep = self.pipeline.run(payload, source_system=source_system)
        if prep.dropped:
            self.store.audit.record(
                "ingest.dropped",
                actor=actor,
                detail={
                    "source_system": source_system,
                    "reason": prep.drop_reason,
                    "ops": prep.meta.get("ops"),
                },
            )
            # Still land empty-safe stub? Skip storage when dropped
            dummy = RawObject.create(
                source_system=source_system,
                payload=payload[:200],
                acl_tags=acl_tags,
                source_uri=source_uri,
                sensitivity=sensitivity,
                workspace_id=workspace_id,
            )
            ep = Episode.from_raw(
                dummy,
                domain=self.domain,
                prep_pipeline_version=self.pipeline_version,
                quality_signals={"dropped": True, "reason": prep.drop_reason},
            )
            return IngestResult(
                raw=dummy,
                episode=ep,
                deduplicated=False,
                dropped=True,
                drop_reason=prep.drop_reason,
                prep_ops=list(prep.meta.get("ops") or []),
            )

        cleaned = prep.text
        h = content_hash(cleaned)
        existing = self.store.get_raw_by_content_hash(
            h, source_system=source_system, source_uri=source_uri
        )
        if existing is not None:
            ep = self.store.episode_for_raw(existing.object_id)
            if ep is None:
                ep = self._build_episode(existing, cleaned, prep.meta)
                self.store.put_episode(ep)
            self.store.audit.record(
                "ingest.dedup",
                actor=actor,
                detail={
                    "content_hash": h[:16],
                    "object_id": existing.object_id,
                    "source_system": existing.source_system,
                },
            )
            return IngestResult(
                raw=existing,
                episode=ep,
                deduplicated=True,
                prep_ops=list(prep.meta.get("ops") or []),
            )

        raw = RawObject.create(
            source_system=source_system,
            payload=cleaned,
            acl_tags=acl_tags,
            source_uri=source_uri,
            sensitivity=sensitivity,
            workspace_id=workspace_id,
        )
        self.store.put_raw(raw)

        episode = self._build_episode(raw, cleaned, prep.meta)
        self.store.put_episode(episode)

        self.store.audit.record(
            "ingest.land",
            actor=actor,
            detail={
                "object_id": raw.object_id,
                "source_system": source_system,
                "content_hash": raw.content_hash[:16],
                "acl_tags": list(acl_tags),
                "ops": prep.meta.get("ops"),
            },
        )
        return IngestResult(
            raw=raw,
            episode=episode,
            deduplicated=False,
            prep_ops=list(prep.meta.get("ops") or []),
        )

    def _build_episode(
        self, raw: RawObject, cleaned: str, prep_meta: dict
    ) -> Episode:
        quality = {
            "token_estimate": prep_meta.get(
                "token_estimate", max(1, len(cleaned.split()))
            ),
            "char_len": prep_meta.get("char_len", len(cleaned)),
            "empty": len(cleaned) == 0,
            "prep_ops": list(prep_meta.get("ops") or []),
            "redacted_emails": prep_meta.get("redacted_emails", 0),
            "redacted_secrets": prep_meta.get("redacted_secrets", 0),
        }
        episode = Episode.from_raw(
            raw,
            domain=self.domain,
            prep_pipeline_version=self.pipeline_version,
            quality_signals=quality,
        )
        episode.payload_text = cleaned
        return episode
