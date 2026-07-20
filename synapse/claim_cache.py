"""
Claim / answer cache with TTL (H2 latency, H3 token economics).

Cache keys are ACL-bound: different principals never share entries.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class CacheEntry:
    key: str
    payload: dict[str, Any]
    principal_fingerprint: str
    created_at: float
    ttl_seconds: float
    hits: int = 0

    def expired(self, now: Optional[float] = None) -> bool:
        t = now if now is not None else time.time()
        return (t - self.created_at) > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "principal_fingerprint": self.principal_fingerprint,
            "age_s": round(time.time() - self.created_at, 2),
            "ttl_seconds": self.ttl_seconds,
            "hits": self.hits,
            "expired": self.expired(),
        }


@dataclass
class ClaimCache:
    """In-process TTL cache (swap for Redis later)."""

    default_ttl: float = 120.0
    max_entries: int = 256
    _entries: dict[str, CacheEntry] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    @staticmethod
    def make_key(
        question: str,
        *,
        principal_attrs: list[str] | set[str],
        intent: Optional[str] = None,
        entity: Optional[str] = None,
        budget_class: Optional[str] = None,
        data_revision: Optional[int] = None,
    ) -> str:
        attrs = ",".join(sorted(principal_attrs))
        blob = f"{question}|{intent}|{entity}|{budget_class}|{attrs}|revision={data_revision}"
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def principal_fingerprint(principal_attrs: list[str] | set[str]) -> str:
        return hashlib.sha256(
            ",".join(sorted(principal_attrs)).encode("utf-8")
        ).hexdigest()[:16]

    def get(self, key: str) -> Optional[dict[str, Any]]:
        ent = self._entries.get(key)
        if ent is None or ent.expired():
            if ent is not None and ent.expired():
                del self._entries[key]
            self.misses += 1
            return None
        ent.hits += 1
        self.hits += 1
        return dict(ent.payload)

    def put(
        self,
        key: str,
        payload: dict[str, Any],
        *,
        principal_attrs: list[str] | set[str],
        ttl_seconds: Optional[float] = None,
    ) -> None:
        if len(self._entries) >= self.max_entries:
            # Evict oldest
            oldest = min(self._entries.values(), key=lambda e: e.created_at)
            self._entries.pop(oldest.key, None)
        self._entries[key] = CacheEntry(
            key=key,
            payload=dict(payload),
            principal_fingerprint=self.principal_fingerprint(principal_attrs),
            created_at=time.time(),
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl,
        )

    def invalidate_all(self) -> int:
        n = len(self._entries)
        self._entries.clear()
        return n

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": round(self.hits / total, 4) if total else 0.0,
            "default_ttl": self.default_ttl,
            "max_entries": self.max_entries,
        }
