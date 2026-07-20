"""
Idempotent reprocessing (H5/H6).

Re-run dual-path extractors over landed raw/episodes when pipeline versions
improve. Facts are versioned via TemporalService supersession; no duplicate spam.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
from synapse.metrics import METRICS
from synapse.models import Episode, RawObject, utc_now_iso
from synapse.store import SemanticStore


@dataclass
class ReprocessReport:
    pipeline_version: str
    episodes_seen: int = 0
    episodes_reprocessed: int = 0
    facts_before: int = 0
    facts_after: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReprocessService:
    """Walk episodes and re-extract under a named pipeline version."""

    def __init__(
        self,
        store: SemanticStore,
        *,
        dual_path: Optional[DualPathExtractor] = None,
        pipeline_version: str = "reprocess/0.1",
        offline_residual: bool = True,
    ) -> None:
        self.store = store
        self.pipeline_version = pipeline_version
        if dual_path is not None:
            self.dual_path = dual_path
        elif offline_residual:
            self.dual_path = DualPathExtractor(
                store, residual=HeuristicResidualExtractor()
            )
        else:
            self.dual_path = DualPathExtractor(store, enable_residual=True)

    def run(
        self,
        *,
        domain: Optional[str] = None,
        limit: Optional[int] = None,
        actor: str = "system:reprocess",
    ) -> ReprocessReport:
        report = ReprocessReport(pipeline_version=self.pipeline_version)
        report.facts_before = len(self.store.facts)
        episodes = list(self.store.episodes.values())
        if domain:
            episodes = [e for e in episodes if e.domain == domain]
        if limit is not None:
            episodes = episodes[: max(0, limit)]

        for ep in episodes:
            report.episodes_seen += 1
            try:
                raw = self._primary_raw(ep)
                if raw is None:
                    report.errors.append(f"{ep.episode_id}: missing_raw")
                    continue
                # Preserve the creation version; append reprocess versions so
                # lineage/rollback can inspect every pass without overwriting
                # the episode's original identity.
                if self.pipeline_version not in ep.pipeline_version_history:
                    ep.pipeline_version_history.append(self.pipeline_version)
                self.store.put_episode(ep)
                self.dual_path.extract(ep, raw)
                report.episodes_reprocessed += 1
            except Exception as e:  # noqa: BLE001
                report.errors.append(f"{ep.episode_id}: {type(e).__name__}: {e}")

        report.facts_after = len(self.store.facts)
        report.finished_at = utc_now_iso()
        self.store.audit.record(
            "reprocess.run",
            actor=actor,
            detail=report.to_dict(),
        )
        METRICS.inc("reprocess.runs")
        METRICS.inc("reprocess.episodes", report.episodes_reprocessed)
        return report

    def _primary_raw(self, ep: Episode) -> Optional[RawObject]:
        for rid in ep.raw_object_ids:
            raw = self.store.raw_objects.get(rid)
            if raw is not None:
                return raw
        return None
