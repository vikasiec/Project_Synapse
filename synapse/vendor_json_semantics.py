"""
Generic vendor JSON with a nested repeating group -- e.g. Abbott Alinity's
batch export (docs/Instrument_Data_Format.md item 5: "Vendor REST JSON
Streams"): one top-level array of specimen records, each carrying its own
nested array of individual assay results.

synapse/profiling.py's _flatten_json deliberately collapses repeated list
items onto the SAME field name (correct for FHIR's flat entry[] and for
simple scalar lists) -- but a *nested* repeating group inside a repeating
top-level array is a different shape: flattening it the same way silently
merges values that mean genuinely different things (an assay's resultValue
for Glucose ends up in the same bucket as the resultValue for Triglycerides
and every other assay type). This module detects that specific shape and
splits it into two virtual sub-sources -- "envelope" (primary record) and
"content" (nested child records) -- the same treatment
_flatten_fhir_bundle_by_type already gives Bundle+Observation, joined by a
synthetic key so the existing value-overlap scoring can discover "this
result belongs to this specimen" without new relationship machinery.

Detection is intentionally narrow (single top-level key wrapping a list of
dicts, at least one of which has its own nested list-of-dicts field) so
this never misfires on ordinary JSON -- same "detect the real shape, don't
guess" discipline as the FHIR Bundle check it sits next to.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

_NestedShape = tuple[str, list[dict], str]


def detect_nested_vendor_json(parsed: Any) -> Optional[_NestedShape]:
    """Returns (primary_field_name, primary_records, child_field_name) if
    `parsed` matches the shape, else None."""
    if not isinstance(parsed, dict) or len(parsed) != 1:
        return None
    ((primary_field_name, value),) = parsed.items()
    if not (isinstance(value, list) and value and all(isinstance(x, dict) for x in value)):
        return None
    child_field_name = None
    for rec in value:
        for key, val in rec.items():
            if isinstance(val, list) and val and all(isinstance(x, dict) for x in val):
                child_field_name = key
                break
        if child_field_name:
            break
    if child_field_name is None:
        return None
    return primary_field_name, value, child_field_name


def looks_like_nested_vendor_json(parsed: Any) -> bool:
    return detect_nested_vendor_json(parsed) is not None


def _find_natural_join_value(record: dict) -> Optional[str]:
    """Best-effort friendlier join key than a bare positional index -- a
    field that looks like a real identifier (barcode/id), not a guess at
    its meaning, just at whether one exists. Falls back to the always-
    correct positional index when none is found (see the *_index field
    every record gets regardless)."""
    for key, val in record.items():
        lower = key.lower()
        if isinstance(val, (str, int, float)) and ("barcode" in lower or lower.endswith("id") or lower == "id"):
            return str(val)
    return None


def _list_or_extend(target: dict[str, list[str]], flat: dict[str, list[str]]) -> None:
    for key, values in flat.items():
        target.setdefault(key, []).extend(values)


def flatten_nested_vendor_json_by_type(parsed: Any) -> dict[str, dict[str, list[str]]]:
    """Column-oriented counterpart to _flatten_fhir_bundle_by_type, for the
    shape this module detects."""
    from synapse.profiling import _flatten_json  # lazy: avoids profiling<->vendor_json_semantics cycle

    detected = detect_nested_vendor_json(parsed)
    if detected is None:
        return {}
    primary_field_name, records, child_field_name = detected
    index_field = f"{primary_field_name}_index"
    id_field = f"{primary_field_name}_id"

    by_type: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for idx, rec in enumerate(records):
        primary_only = {k: v for k, v in rec.items() if k != child_field_name}
        natural_id = _find_natural_join_value(primary_only)
        _list_or_extend(by_type[primary_field_name], _flatten_json(primary_only))
        by_type[primary_field_name].setdefault(index_field, []).append(str(idx))

        for child in rec.get(child_field_name) or []:
            if not isinstance(child, dict):
                continue
            _list_or_extend(by_type[child_field_name], _flatten_json(child))
            by_type[child_field_name].setdefault(index_field, []).append(str(idx))
            if natural_id:
                by_type[child_field_name].setdefault(id_field, []).append(natural_id)

    return dict(by_type)


def extract_nested_vendor_json_rows(parsed: Any) -> dict[str, list[dict[str, str]]]:
    """Row-oriented counterpart, for star_schema.py materialization -- one
    dict per primary/child record instance, not a shared column bucket."""
    from synapse.profiling import _flatten_json  # lazy: avoids profiling<->vendor_json_semantics cycle

    detected = detect_nested_vendor_json(parsed)
    if detected is None:
        return {}
    primary_field_name, records, child_field_name = detected
    index_field = f"{primary_field_name}_index"
    id_field = f"{primary_field_name}_id"

    rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for idx, rec in enumerate(records):
        primary_only = {k: v for k, v in rec.items() if k != child_field_name}
        natural_id = _find_natural_join_value(primary_only)
        primary_row = {k: v[0] for k, v in _flatten_json(primary_only).items() if v}
        primary_row[index_field] = str(idx)
        rows[primary_field_name].append(primary_row)

        for child in rec.get(child_field_name) or []:
            if not isinstance(child, dict):
                continue
            child_row = {k: v[0] for k, v in _flatten_json(child).items() if v}
            child_row[index_field] = str(idx)
            if natural_id:
                child_row[id_field] = natural_id
            rows[child_field_name].append(child_row)

    return dict(rows)
