"""
Clinical reference-range flag evaluation (docs/Instrument_Data_Format.md
section 4, "Clinical Normalization Engine"): given a numeric result and its
reference range, compute NORMAL/HIGH/LOW/CRITICAL/PANIC.

This is a derived value computed at read time (profiling/materialization),
never written back onto the immutable landed RawObject -- same "raw stays
raw" discipline as everything else in this codebase that computes something
from landed data (SchemaFieldProfile, star_schema's classification, etc.).

Honesty about what this is, stated up front: real critical/panic limits are
lab- and analyte-specific policy (defined by the lab's own escalation
rules), not something derivable purely from a reference range. What's
implemented here is a reasonable, clearly-documented *heuristic* --
severity scaled by how many multiples of the reference range's own width a
result falls outside it -- not a clinically-validated threshold table. It's
useful for a schema-on-read demo (turning a raw HL7/ASTM/vendor-JSON result
+ range into a human-readable severity band) but should not be mistaken for
real lab-defined critical-value policy.
"""

from __future__ import annotations

import re
from typing import Optional

# How many multiples of the reference range's own width a result must fall
# outside the nearer bound before escalating past plain HIGH/LOW. Kept as
# named constants (not inlined) so the heuristic is visible and adjustable
# in one place, not buried in a comparison.
_CRITICAL_MULTIPLE = 1.5
_PANIC_MULTIPLE = 3.0

_RANGE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[-^]\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_reference_range(range_str: Optional[str]) -> Optional[tuple[float, float]]:
    """Parses the two reference-range shapes this project's formats
    actually emit: HL7/vendor-JSON's "low-high" (e.g. "13.5-17.5",
    "70.0-105.0") and ASTM's "low^high" component-separated form (e.g.
    "0.6^1.3", already seen split into two fields by astm_semantics.py's
    RANGE_SPLIT, but the raw combined form is supported here too for
    formats that don't pre-split it). Returns None for anything else --
    never guesses at an ambiguous or malformed range."""
    if not range_str:
        return None
    m = _RANGE_RE.match(range_str)
    if not m:
        return None
    low, high = float(m.group(1)), float(m.group(2))
    if low > high:
        return None
    return low, high


def compute_flag(
    value: Optional[float] = None,
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    *,
    range_str: Optional[str] = None,
) -> Optional[str]:
    """Returns "NORMAL"/"HIGH"/"LOW"/"CRITICAL"/"PANIC", or None when the
    value or range can't be evaluated (missing/malformed). Callers may pass
    a pre-split ref_low/ref_high (ASTM's shape) or a combined range_str
    (HL7/vendor-JSON's shape, parsed via parse_reference_range) -- not
    both; range_str takes precedence if given."""
    if value is None:
        return None
    if range_str is not None:
        parsed = parse_reference_range(range_str)
        if parsed is None:
            return None
        ref_low, ref_high = parsed
    if ref_low is None or ref_high is None or ref_low > ref_high:
        return None

    if ref_low <= value <= ref_high:
        return "NORMAL"

    width = ref_high - ref_low
    if width <= 0:
        # Degenerate range (low == high): anything outside it is at least
        # HIGH/LOW, but the multiple-of-width escalation below has no
        # meaningful denominator -- fall back to the plain direction only.
        return "HIGH" if value > ref_high else "LOW"

    distance = (value - ref_high) if value > ref_high else (ref_low - value)
    multiple = distance / width
    direction = "HIGH" if value > ref_high else "LOW"
    if multiple >= _PANIC_MULTIPLE:
        return "PANIC"
    if multiple >= _CRITICAL_MULTIPLE:
        return "CRITICAL"
    return direction


def _to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_flag_for_row(row: dict[str, str], value_field: str, range_field: str) -> Optional[str]:
    """Convenience wrapper for row-shaped data (star_schema.py's row
    extraction output): looks up value_field/range_field by name, coerces,
    and delegates to compute_flag. Returns None if either field is
    missing/unparseable -- silent skip, not a fabricated flag."""
    value = _to_float(row.get(value_field))
    return compute_flag(value, range_str=row.get(range_field))


def compute_flag_for_row_split_range(
    row: dict[str, str], value_field: str, low_field: str, high_field: str
) -> Optional[str]:
    """Same as compute_flag_for_row, for formats (ASTM) that already split
    the reference range into separate low/high fields instead of one
    combined string."""
    value = _to_float(row.get(value_field))
    ref_low = _to_float(row.get(low_field))
    ref_high = _to_float(row.get(high_field))
    return compute_flag(value, ref_low, ref_high)
