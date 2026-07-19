"""
Schema drift detection (H5).

Watches episode/payload shapes per source_system and emits drift events
when new keys or patterns appear — triggers reprocess recommendation.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from synapse.models import utc_now_iso
from synapse.store import SemanticStore

_KEY_RE = re.compile(r"^([A-Za-z0-9_ -]{2,40})\s*[:=]", re.MULTILINE)


@dataclass
class SourceShape:
    source_system: str
    keys: set[str] = field(default_factory=set)
    sample_count: int = 0
    last_seen: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_system": self.source_system,
            "keys": sorted(self.keys),
            "sample_count": self.sample_count,
            "last_seen": self.last_seen,
        }


@dataclass
class DriftEvent:
    source_system: str
    new_keys: list[str]
    removed_keys: list[str]
    detected_at: str
    recommendation: str = "reprocess"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DriftDetector:
    def __init__(self, store: SemanticStore) -> None:
        self.store = store
        self.baselines: dict[str, SourceShape] = {}
        self.events: list[DriftEvent] = []

    def observe_all(self) -> list[DriftEvent]:
        """Scan store and return new drift events since last baselines."""
        by_source: dict[str, list[str]] = defaultdict(list)
        for raw in self.store.raw_objects.values():
            by_source[raw.source_system].append(raw.raw_payload)

        new_events: list[DriftEvent] = []
        for source, payloads in by_source.items():
            keys: set[str] = set()
            for p in payloads:
                keys |= {m.group(1).strip().lower() for m in _KEY_RE.finditer(p)}
            # Also light pattern tags
            blob = "\n".join(payloads).lower()
            for tag, pat in (
                ("has_version", r"\bv\d+\.\d+\.\d+\b"),
                ("has_crashloop", r"crashloopbackoff"),
                ("has_revenue", r"annual[_ ]?revenue|arr"),
                ("has_person", r"person |employee |account_status"),
            ):
                if re.search(pat, blob):
                    keys.add(tag)

            shape = SourceShape(
                source_system=source,
                keys=keys,
                sample_count=len(payloads),
                last_seen=utc_now_iso(),
            )
            prev = self.baselines.get(source)
            if prev is None:
                self.baselines[source] = shape
                continue
            new_keys = sorted(keys - prev.keys)
            removed = sorted(prev.keys - keys)
            if new_keys or (removed and prev.sample_count >= 2):
                ev = DriftEvent(
                    source_system=source,
                    new_keys=new_keys,
                    removed_keys=removed,
                    detected_at=utc_now_iso(),
                    recommendation="reprocess" if new_keys else "review",
                )
                self.events.append(ev)
                new_events.append(ev)
                self.store.audit.record(
                    "drift.detected",
                    actor="system:drift",
                    detail=ev.to_dict(),
                )
            # Update baseline to latest observed union (expanding soft types)
            prev.keys |= keys
            prev.sample_count = len(payloads)
            prev.last_seen = utc_now_iso()
        return new_events

    def describe(self) -> dict[str, Any]:
        return {
            "baselines": {k: v.to_dict() for k, v in self.baselines.items()},
            "events": [e.to_dict() for e in self.events[-50:]],
            "event_count": len(self.events),
        }
