"""
Row-oriented (not column-oriented) extraction across a source's raw
objects -- the single entry point synapse/star_schema.py uses to build
real fact/dimension table rows.

synapse/profiling.py's _extract_field_values (and everything built on
it: SchemaFieldProfile, Explore, Schema View) is deliberately
column-oriented -- "field_name -> every observed value" -- the right
shape for schema/type inference, but it discards which values belonged
to the same source record. Materializing a real fact table needs the
opposite: a record's fields kept together as one row, so foreign keys
and measures stay correctly correlated. This module dispatches to the
row-oriented extractors (hl7_semantics.extract_hl7_rows,
profiling.extract_fhir_rows_by_type) for the two formats that actually
need them, mirroring _extract_field_values's own dispatch structure for
everything else (CSV already lands one RawObject per row -- see
POST /v1/explore/ingest's CSV branch -- so one row-per-object is already
correct there without any new parsing).
"""

from __future__ import annotations

import json
from typing import Optional

from synapse.hl7_semantics import extract_hl7_rows
from synapse.profiling import _KV_RE, _flatten_json, extract_fhir_rows_by_type


def extract_rows(raws: list, type_filter: Optional[str] = None) -> list[dict[str, str]]:
    """Row-level extraction across a source's raw objects.

    - HL7 payload: extract_hl7_rows scoped to type_filter (a segment name).
    - FHIR Bundle: extract_fhir_rows_by_type scoped to type_filter (a
      resourceType).
    - everything else (CSV-per-row RawObject, plain JSON): one row per
      RawObject -- type_filter must be absent (nothing to scope to,
      same "no filter on non-decomposable content" rule
      _extract_field_values already enforces).
    """
    rows: list[dict[str, str]] = []
    for raw in raws:
        payload = raw.raw_payload
        stripped = payload.strip()

        if stripped[:1] in ("{", "["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and parsed.get("resourceType") == "Bundle" and isinstance(
                parsed.get("entry"), list
            ):
                if type_filter:
                    rows.extend(extract_fhir_rows_by_type(payload).get(type_filter, []))
                continue
            if parsed is not None:
                if type_filter:
                    continue
                row = {k: v[0] for k, v in _flatten_json(parsed).items() if v}
                if row:
                    rows.append(row)
                continue

        if stripped.startswith("MSH"):
            by_segment = extract_hl7_rows(payload)
            if by_segment:
                if type_filter:
                    rows.extend(by_segment.get(type_filter, []))
                continue

        if type_filter:
            continue
        row = {}
        for m in _KV_RE.finditer(payload):
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            if val:
                row[key] = val
        if row:
            rows.append(row)
    return rows
