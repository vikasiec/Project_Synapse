"""Lightweight in-process counters for observability (no deps)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsRegistry:
    counters: dict[str, int] = field(default_factory=dict)
    timings_ms: dict[str, list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    started_at: float = field(default_factory=time.time)

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + value

    def observe_ms(self, name: str, duration_ms: float) -> None:
        with self._lock:
            self.timings_ms.setdefault(name, []).append(duration_ms)
            # cap samples
            if len(self.timings_ms[name]) > 500:
                self.timings_ms[name] = self.timings_ms[name][-500:]

    def timer(self, name: str):
        registry = self

        class _Timer:
            def __enter__(self_inner):
                self_inner._t0 = time.perf_counter()
                return self_inner

            def __exit__(self_inner, *exc):
                dt = (time.perf_counter() - self_inner._t0) * 1000.0
                registry.observe_ms(name, dt)
                registry.inc(f"{name}.count")

        return _Timer()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            timing_summary = {}
            for k, samples in self.timings_ms.items():
                if not samples:
                    continue
                ordered = sorted(samples)
                mid = ordered[len(ordered) // 2]
                timing_summary[k] = {
                    "count": len(samples),
                    "p50_ms": round(mid, 3),
                    "max_ms": round(ordered[-1], 3),
                    "avg_ms": round(sum(samples) / len(samples), 3),
                }
            return {
                "uptime_s": round(time.time() - self.started_at, 2),
                "counters": dict(self.counters),
                "timings": timing_summary,
            }


# Process-global registry
METRICS = MetricsRegistry()
