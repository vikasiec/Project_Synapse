"""
Gemini Path B residual extractor (POC / free-tier friendly).

Env:
  GEMINI_API_KEY       required for live calls
  GEMINI_MODEL         default: gemini-2.5-flash-lite (override for 3.1 Flash-Lite when available)
  GEMINI_MAX_RPM       default: 12  (stay under free-tier ~15 RPM)
  GEMINI_MAX_RPD       default: 900 (stay under free-tier ~1000 RPD)
  GEMINI_MAX_OUTPUT_TOKENS  default: 512
  SYNAPSE_LLM_BACKEND  gemini | heuristic | noop  (default: auto)

POC policy: rules (Path A) first; Gemini only for residual free text.
Real/paid APIs later — same ResidualExtractor interface.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from synapse.dual_path import ResidualExtractor
from synapse.metrics import METRICS
from synapse.models import Episode, Fact, RawObject

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_SECRET_RE = re.compile(
    r"(key=)[^&\s]+|(AIza[0-9A-Za-z_-]{10,})|(AQ\.[0-9A-Za-z_-]{10,})",
    re.I,
)


def _redact_secrets(text: str) -> str:
    """Strip API keys from logs/errors (never print secrets)."""
    if not text:
        return text
    return _SECRET_RE.sub(lambda m: (m.group(1) or "") + "***REDACTED***", text)


@dataclass
class RateLimitState:
    """In-process free-tier guard (not shared across processes)."""

    max_rpm: int = 12
    max_rpd: int = 900
    min_interval_s: float = 5.0  # ~12 RPM
    day_key: str = ""
    day_count: int = 0
    last_call_ts: float = 0.0
    blocked_reason: Optional[str] = None

    def __post_init__(self) -> None:
        self.min_interval_s = max(60.0 / max(self.max_rpm, 1), 1.0)

    def allow(self) -> tuple[bool, Optional[str]]:
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        if day != self.day_key:
            self.day_key = day
            self.day_count = 0
        if self.day_count >= self.max_rpd:
            return False, f"daily cap reached ({self.max_rpd} RPD)"
        wait = self.min_interval_s - (now - self.last_call_ts)
        if wait > 0:
            time.sleep(min(wait, 30.0))
        return True, None

    def record(self) -> None:
        self.last_call_ts = time.time()
        self.day_count += 1


# Process-global limiter for free-tier POC
_RATE = RateLimitState(
    max_rpm=int(os.environ.get("GEMINI_MAX_RPM", "12")),
    max_rpd=int(os.environ.get("GEMINI_MAX_RPD", "900")),
)


def gemini_configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _api_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def call_gemini_generate(
    prompt: str,
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    http_post: Optional[Callable[..., Any]] = None,
) -> str:
    """
    Low-level generateContent call (stdlib urllib).
    http_post: injectable for tests — (url, data_bytes, headers) -> response body str
    """
    key = api_key or _api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set")

    model_id = model or DEFAULT_MODEL
    max_tok = max_output_tokens or int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "512"))
    qs = urlencode({"key": key})
    url = f"{API_BASE}/{model_id}:generateContent?{qs}"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_tok,
            "responseMimeType": "application/json",
        },
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    if http_post is not None:
        raw = http_post(url, data, headers)
        payload = json.loads(raw)
    else:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            # Never surface API keys (key is in query string)
            err_body = _redact_secrets(err_body)
            raise RuntimeError(f"Gemini HTTP {e.code}: {err_body[:500]}") from e

    # Parse candidates[0].content.parts[].text
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini empty candidates: {str(payload)[:300]}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    texts = [p.get("text", "") for p in parts if p.get("text")]
    if not texts:
        raise RuntimeError("Gemini response had no text parts")
    return "\n".join(texts)


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


def _parse_facts_json(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    data = json.loads(text)
    if isinstance(data, dict):
        if "facts" in data and isinstance(data["facts"], list):
            return data["facts"]
        if "predicate" in data:
            return [data]
        return []
    if isinstance(data, list):
        return data
    return []


class GeminiResidualExtractor(ResidualExtractor):
    """
    Path B: ask Gemini for residual structured notes as JSON facts.

    Falls back silently to empty list if no key / rate limited / API error
    (POC-safe; Path A still holds).
    """

    name = "gemini_residual"

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        rate: Optional[RateLimitState] = None,
        http_post: Optional[Callable[..., Any]] = None,
        strict: bool = False,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.api_key = api_key
        self.rate = rate or _RATE
        self.http_post = http_post
        self.strict = strict  # if True, raise instead of swallow errors

    def extract_residual(
        self,
        residual_text: str,
        *,
        episode: Episode,
        raw: RawObject,
        entity_id: Optional[str],
    ) -> list[Fact]:
        if not entity_id or not residual_text.strip():
            return []
        if not (self.api_key or _api_key()):
            if self.strict:
                raise RuntimeError("GEMINI_API_KEY not set")
            return []

        ok, reason = self.rate.allow()
        if not ok:
            METRICS.inc("gemini.rate_limited")
            self.rate.blocked_reason = reason
            if self.strict:
                raise RuntimeError(reason)
            return []

        prompt = self._build_prompt(residual_text, raw.source_system)
        try:
            with METRICS.timer("gemini.generate"):
                text = call_gemini_generate(
                    prompt,
                    model=self.model,
                    api_key=self.api_key,
                    http_post=self.http_post,
                )
            self.rate.record()
            METRICS.inc("gemini.success")
        except Exception:
            METRICS.inc("gemini.error")
            if self.strict:
                raise
            # POC: do not break ingest — fall back to heuristic notes
            return self._heuristic_fallback(
                residual_text, episode=episode, raw=raw, entity_id=entity_id
            )

        try:
            items = _parse_facts_json(text)
        except json.JSONDecodeError:
            METRICS.inc("gemini.parse_error")
            if self.strict:
                raise
            return self._heuristic_fallback(
                residual_text, episode=episode, raw=raw, entity_id=entity_id
            )

        facts: list[Fact] = []
        for item in items[:10]:
            if not isinstance(item, dict):
                continue
            pred = str(item.get("predicate") or "free_text_note").strip()[:64]
            obj = item.get("object")
            if obj is None or pred == "":
                continue
            conf = float(item.get("confidence", 0.6))
            conf = min(max(conf, 0.0), 0.85)  # residual never overconfident
            facts.append(
                Fact.create(
                    entity_id,
                    pred,
                    obj if not isinstance(obj, str) else obj[:500],
                    confidence=conf,
                    evidence_refs=[raw.object_id, episode.episode_id],
                    source_system=raw.source_system,
                    acl_tags=list(raw.acl_tags),
                    valid_from=raw.ingested_at,
                    extractor_version=f"gemini-residual/{self.model}",
                )
            )
        if not facts:
            return self._heuristic_fallback(
                residual_text, episode=episode, raw=raw, entity_id=entity_id
            )
        return facts

    @staticmethod
    def _heuristic_fallback(
        residual_text: str,
        *,
        episode: Episode,
        raw: RawObject,
        entity_id: str,
    ) -> list[Fact]:
        from synapse.dual_path import HeuristicResidualExtractor

        return HeuristicResidualExtractor().extract_residual(
            residual_text, episode=episode, raw=raw, entity_id=entity_id
        )

    @staticmethod
    def _build_prompt(residual_text: str, source_system: str) -> str:
        return f"""You extract residual semantic facts from operational text for a schema-on-read system.
Structured fields were already extracted by deterministic rules. Only extract EXTRA free-text insights.

Source system: {source_system}

Text:
---
{residual_text[:3000]}
---

Return ONLY valid JSON of the form:
{{"facts":[{{"predicate":"snake_case_name","object":"short value","confidence":0.0}}]}}

Rules:
- Max 5 facts
- Prefer predicates like free_text_note, risk_flag, human_action, incident_theme
- Do not invent version numbers, money amounts, or IDs not in the text
- If nothing useful, return {{"facts":[]}}
"""


def create_residual_extractor(
    backend: Optional[str] = None,
) -> ResidualExtractor:
    """
    Factory for Path B.

    backend / SYNAPSE_LLM_BACKEND:
      - auto (default): gemini if API key set, else heuristic
      - gemini: require key (returns gemini extractor; empty results if no key unless used)
      - heuristic: offline regex residual
      - noop: disable residual
    """
    from synapse.dual_path import (
        HeuristicResidualExtractor,
        NoopResidualExtractor,
    )

    choice = (backend or os.environ.get("SYNAPSE_LLM_BACKEND") or "auto").lower()
    if choice in {"noop", "none", "off"}:
        return NoopResidualExtractor()
    if choice in {"heuristic", "local"}:
        return HeuristicResidualExtractor()
    if choice == "gemini":
        return GeminiResidualExtractor()
    # auto
    if gemini_configured():
        return GeminiResidualExtractor()
    return HeuristicResidualExtractor()
