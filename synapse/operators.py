"""
Data-Juicer-class composable prep operators (POC subset).

Not the full Alibaba Data-Juicer suite — same *idea*: sandboxed, chainable
transforms that clean/normalize streams without forcing a warehouse schema.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol


@dataclass
class OpContext:
    """Mutable bag passed through an operator chain."""

    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    dropped: bool = False
    drop_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "meta": dict(self.meta),
            "dropped": self.dropped,
            "drop_reason": self.drop_reason,
            "token_estimate": self.meta.get("token_estimate"),
        }


class Operator(Protocol):
    name: str

    def __call__(self, ctx: OpContext) -> OpContext: ...


class StripWhitespace:
    name = "strip_whitespace"

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        ctx.text = ctx.text.strip()
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


class NormalizeNewlines:
    name = "normalize_newlines"

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        ctx.text = ctx.text.replace("\r\n", "\n").replace("\r", "\n")
        ctx.text = re.sub(r"\n{3,}", "\n\n", ctx.text)
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


class UnicodeNFKC:
    name = "unicode_nfkc"

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        ctx.text = unicodedata.normalize("NFKC", ctx.text)
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


class DropEmpty:
    name = "drop_empty"

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        if not ctx.text.strip():
            ctx.dropped = True
            ctx.drop_reason = "empty"
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


class DropTooShort:
    name = "drop_too_short"

    def __init__(self, min_chars: int = 8) -> None:
        self.min_chars = min_chars

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        if len(ctx.text.strip()) < self.min_chars:
            ctx.dropped = True
            ctx.drop_reason = f"too_short<{self.min_chars}"
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


class RedactEmails:
    name = "redact_emails"
    _RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        ctx.text, n = self._RE.subn("[REDACTED_EMAIL]", ctx.text)
        ctx.meta["redacted_emails"] = n
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


class RedactSecretsLite:
    """Light secret scrubber for POC dumps (not a full DLP product)."""

    name = "redact_secrets_lite"
    _PATTERNS = [
        (re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
        (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "[REDACTED_KEY]"),
        (re.compile(r"\bsk-[0-9A-Za-z]{20,}\b"), "[REDACTED_KEY]"),
    ]

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        n = 0
        for pat, repl in self._PATTERNS:
            ctx.text, c = pat.subn(repl, ctx.text)
            n += c
        ctx.meta["redacted_secrets"] = n
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


class TokenEstimate:
    name = "token_estimate"

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        ctx.meta["token_estimate"] = max(1, len(ctx.text.split()))
        ctx.meta["char_len"] = len(ctx.text)
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


class CollapseSpaces:
    name = "collapse_spaces"

    def __call__(self, ctx: OpContext) -> OpContext:
        if ctx.dropped:
            return ctx
        ctx.text = re.sub(r"[ \t]+", " ", ctx.text)
        ctx.meta["ops"] = ctx.meta.get("ops", []) + [self.name]
        return ctx


DEFAULT_PIPELINE: list[Operator] = [
    StripWhitespace(),
    NormalizeNewlines(),
    UnicodeNFKC(),
    CollapseSpaces(),
    RedactEmails(),
    RedactSecretsLite(),
    DropEmpty(),
    DropTooShort(min_chars=8),
    TokenEstimate(),
]


class OperatorPipeline:
    """Composable prep chain — Data-Juicer role in the blueprint."""

    name = "data_juicer_lite"

    def __init__(self, ops: Optional[list[Operator]] = None) -> None:
        self.ops = list(ops or DEFAULT_PIPELINE)

    def run(self, text: str, **meta: Any) -> OpContext:
        ctx = OpContext(text=text, meta=dict(meta))
        for op in self.ops:
            ctx = op(ctx)
            if ctx.dropped:
                break
        return ctx

    def describe(self) -> list[str]:
        return [getattr(op, "name", type(op).__name__) for op in self.ops]
