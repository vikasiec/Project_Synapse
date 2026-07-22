"""
Schema field profiling & vector extraction (Major Goal 1).

Computes per-(source_system, field) structural profiles and a stdlib-only
semantic vector from already-landed RawObject payloads. Raw values are used
transiently to derive statistics/sketches and are never persisted on the
resulting profile -- only aggregate signals are kept, per the spec's
"without storing raw sensitive values" requirement.

No embedding library is installed in this project (confirmed: the only
existing vector code, synapse/graphiti_factory.py, calls a live remote
Gemini endpoint and is not usable offline). The semantic_vector here is a
deterministic char-trigram hashing-trick vector standing in for the spec's
"lightweight cross-encoder model" -- same shape (a comparable float array),
computed entirely locally.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional

from synapse.models import utc_now_iso
from synapse.security import Principal, filter_raw_objects
from synapse.store import SemanticStore

_KV_RE = re.compile(r"^([A-Za-z0-9_ -]{2,40})\s*[:=]\s*(.*)$", re.MULTILINE)


def _flatten_json(obj: Any, prefix: str = "", out: Optional[dict[str, list[str]]] = None) -> dict[str, list[str]]:
    """Recursively flattens a parsed JSON payload into dotted-path field
    names -> observed scalar values. Repeated list items collapse onto the
    SAME field name (e.g. FHIR's identifier: [...]) rather than exploding
    into identifier.0/identifier.1/... -- consistent with the CSV model
    where multiple rows contribute multiple observed values for one field,
    not one field per row. Domain-blind: no FHIR/HL7/resource-specific keys
    are named anywhere here."""
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_json(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        for item in obj:
            _flatten_json(item, prefix, out)
    elif obj is not None:
        out.setdefault(prefix, []).append(str(obj))
    return out


def _extract_field_values(payload: str) -> dict[str, list[str]]:
    """Field-name -> observed-values extraction, JSON-aware. Tries JSON
    first (covers the FHIR/JSONL connectors, which land raw JSON text
    as-is per synapse/connectors/fhir_file.py and file_jsonl.py); falls
    back to the "key: value"-per-line convention the CSV connector
    actually emits (synapse/connectors/csv_drop.py) and that
    synapse/drift.py's _KEY_RE already relies on elsewhere in this
    codebase. HL7v2 pipe-delimited payloads (synapse/connectors/hl7_file.py)
    are not covered by either path -- segment-position-aware parsing would
    require HL7-specific knowledge a domain-blind profiler shouldn't own;
    left as a known residual rather than silently claimed to work."""
    stripped = payload.strip()
    if stripped[:1] in ("{", "["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            return _flatten_json(parsed)

    field_values: dict[str, list[str]] = defaultdict(list)
    for m in _KV_RE.finditer(payload):
        key = m.group(1).strip().lower()
        val = m.group(2).strip()
        if val:
            field_values[key].append(val)
    return field_values


_VECTOR_DIM = 64
_MINHASH_COUNT = 16

# Ordered most-specific-first: a value is classified as the first pattern it
# matches, so e.g. an 8-digit integer is "Integer8" rather than "Integer".
_PATTERNS: dict[str, re.Pattern] = {
    "UUID": re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
    ),
    "Timestamp": re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"),
    "Date": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "Email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    # Requires at least one separator/+ so plain digit strings (e.g. an
    # 8-digit customer id) are never ambiguous with Integer8/Integer.
    "Phone": re.compile(r"^(?=.*[+\-\(\) ])\+?[\d\-\(\) ]{7,15}$"),
    "Integer8": re.compile(r"^\d{8}$"),
    "Integer": re.compile(r"^-?\d+$"),
    "Float": re.compile(r"^-?\d+\.\d+$"),
}


# Classical schema-matching synonym normalization (the pre-neural technique
# used by tools like COMA/Cupid): canonicalize common field-name tokens
# before vectorizing, so lexically different but semantically equivalent
# names (cust_id / client_num) land close together without a network call.
_SYNONYM_CANON: dict[str, str] = {
    "cust": "customer", "client": "customer", "acct": "customer", "account": "customer",
    "id": "identifier", "num": "identifier", "number": "identifier", "no": "identifier",
    "nm": "name", "fname": "firstname", "lname": "lastname",
    "dob": "birthdate", "birth": "birthdate",
    "tel": "phone", "telephone": "phone", "mobile": "phone",
    "addr": "address", "amt": "amount", "qty": "quantity",
    "dt": "date", "ts": "timestamp",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _canonicalize_field_name(text: str) -> str:
    tokens = _TOKEN_RE.findall(text.strip().lower())
    canon = [_SYNONYM_CANON.get(t, t) for t in tokens]
    return " ".join(canon)


def _hashing_vector(text: str, dim: int = _VECTOR_DIM) -> list[float]:
    """Stdlib-only char-trigram hashing-trick embedding, L2-normalized.
    Input is synonym-canonicalized first (see _SYNONYM_CANON)."""
    vec = [0.0] * dim
    padded = f"  {_canonicalize_field_name(text)}  "
    for i in range(len(padded) - 2):
        trigram = padded[i : i + 3]
        digest = hashlib.blake2b(trigram.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "big")
        sign = 1.0 if (h >> 63) & 1 == 0 else -1.0
        vec[h % dim] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, dot))  # inputs are already L2-normalized


def _minhash_sketch(values: set[str], num_hashes: int = _MINHASH_COUNT) -> list[int]:
    """Approximate MinHash sketch over a distinct value set (Jaccard estimator)."""
    if not values:
        return []
    sketch: list[int] = []
    for seed in range(num_hashes):
        best: Optional[int] = None
        for v in values:
            digest = hashlib.blake2b(f"{seed}:{v}".encode("utf-8"), digest_size=8).digest()
            h = int.from_bytes(digest, "big")
            if best is None or h < best:
                best = h
        sketch.append(best if best is not None else 0)
    return sketch


def jaccard_from_minhash(a: list[int], b: list[int]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    matches = sum(1 for x, y in zip(a, b) if x == y)
    return matches / len(a)


def _dominant_data_type(values: list[str]) -> str:
    if not values:
        return "String"
    counts = {name: 0 for name in _PATTERNS}
    for v in values:
        stripped = v.strip()
        for name, pat in _PATTERNS.items():
            if pat.match(stripped):
                counts[name] += 1
                break
    name, hits = max(counts.items(), key=lambda kv: kv[1])
    return name if hits >= len(values) * 0.6 else "String"


def _regex_pattern_match(values: list[str]) -> dict[str, float]:
    if not values:
        return {}
    out: dict[str, float] = {}
    for name, pat in _PATTERNS.items():
        hits = sum(1 for v in values if pat.match(v.strip()))
        if hits:
            out[name] = round(hits / len(values), 4)
    return out


def _entropy_score(values: list[str]) -> float:
    if not values:
        return 0.0
    return round(len(set(values)) / len(values), 4)


@dataclass
class SchemaFieldProfile:
    source_system: str
    field_name: str
    data_type: str
    entropy_score: float
    regex_pattern_match: dict[str, float]
    min_hash_sketch: list[int]
    semantic_vector: list[float]
    sample_count: int
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_system": self.source_system,
            "field_name": self.field_name,
            "data_type": self.data_type,
            "entropy_score": self.entropy_score,
            "regex_pattern_match": self.regex_pattern_match,
            "min_hash_sketch": self.min_hash_sketch,
            "semantic_vector": self.semantic_vector,
            "sample_count": self.sample_count,
            "generated_at": self.generated_at,
        }


class SchemaProfiler:
    """Computes SchemaFieldProfile objects from landed RawObjects."""

    def __init__(self, store: SemanticStore) -> None:
        self.store = store

    def _visible_raw_for_source(
        self, source_system: str, principal: Optional[Principal]
    ) -> list:
        raws = [r for r in self.store.raw_objects.values() if r.source_system == source_system]
        if principal is not None:
            raws = filter_raw_objects(principal, raws)
        return raws

    def profile_source(
        self, source_system: str, principal: Optional[Principal] = None
    ) -> dict[str, SchemaFieldProfile]:
        field_values: dict[str, list[str]] = defaultdict(list)
        for raw in self._visible_raw_for_source(source_system, principal):
            for key, values in _extract_field_values(raw.raw_payload).items():
                field_values[key].extend(values)

        profiles: dict[str, SchemaFieldProfile] = {}
        for field_name, values in field_values.items():
            profiles[field_name] = SchemaFieldProfile(
                source_system=source_system,
                field_name=field_name,
                data_type=_dominant_data_type(values),
                entropy_score=_entropy_score(values),
                regex_pattern_match=_regex_pattern_match(values),
                min_hash_sketch=_minhash_sketch(set(values)),
                semantic_vector=_hashing_vector(field_name),
                sample_count=len(values),
                generated_at=utc_now_iso(),
            )
        return profiles

    def known_sources(self, principal: Optional[Principal] = None) -> list[str]:
        raws = list(self.store.raw_objects.values())
        if principal is not None:
            raws = filter_raw_objects(principal, raws)
        return sorted({r.source_system for r in raws})

    def profile_all_sources(
        self, principal: Optional[Principal] = None
    ) -> dict[str, dict[str, SchemaFieldProfile]]:
        return {
            source: self.profile_source(source, principal=principal)
            for source in self.known_sources(principal)
        }
