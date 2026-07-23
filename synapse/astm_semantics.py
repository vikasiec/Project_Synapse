"""
ASTM E1394/E1381 pipe-delimited record semantics (Roche Cobas 8000 and
similar clinical chemistry analyzers) -- a real, standardized lab-interface
protocol distinct from HL7v2, despite superficial similarity (also
pipe-delimited, also positional).

Real field positions per record type, not a positional-code passthrough --
same discipline hl7_semantics.py established for HL7v2. Record types in a
stream (confirmed against the real sample file, 631 lines, exactly these
5 types): H (header, 1 per file), P (patient), O (order), R (result),
L (terminator, 1 per file).

Unlike HL7, ASTM records carry no explicit correlation id linking a result
back to its order or a patient (no MSH-10-style message_control_id). The
real correlation is purely stream position: one P record opens a block:
every O and R that follows belongs to that patient until the next P
appears; every R that follows an O belongs to that order until the next O
appears. This module makes that positional correlation explicit and
inspectable by injecting synthetic astm_patient_id/astm_specimen_id keys
into every record they logically belong to (parallel to hl7_semantics.py's
hl7_message_id injection, just keyed by sequence instead of a field value).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

# Real ASTM E1394 field positions -> canonical names, 1-indexed after the
# record-type letter (same convention as hl7_semantics.SEGMENT_FIELDS).
# Confirmed against the real sample file's field counts per record type
# (H=14, P=9, O=23, R=13, L=3 pipe-delimited tokens).
RECORD_FIELDS: dict[str, dict[int, str]] = {
    "H": {
        4: "sender_name", 11: "processing_id", 12: "version_number", 13: "message_datetime",
    },
    "P": {
        1: "set_id", 2: "patient_id", 7: "date_of_birth", 8: "sex",
        # 5 (patient_name) handled by NAME_SPLIT below.
    },
    "O": {
        1: "set_id", 2: "specimen_id", 5: "priority", 6: "requested_datetime",
        15: "specimen_source", 22: "report_type",
        # 4 (universal_test_id, a backslash-separated panel of tests) handled
        # separately below -- multiple tests per order, not a single code.
    },
    "R": {
        1: "set_id", 3: "result_value", 4: "units", 6: "abnormal_flag",
        8: "result_status", 11: "completed_datetime", 12: "instrument_id",
        # 2 (universal_test_id) handled by TEST_ID_SPLIT below; 5
        # (reference_range) handled by RANGE_SPLIT below.
    },
    "L": {
        1: "set_id", 2: "termination_code",
    },
}

# Composite field "^^^CODE" (ASTM's CE-like universal test id) -- component
# 4 is the local test code, same role as HL7's OBR-4/OBX-3 CE_SPLIT.
TEST_ID_SPLIT: dict[tuple[str, int], str] = {
    ("R", 2): "test_code",
}

# P-5 patient name: "Last^First" -> two real sub-columns, same role as
# HL7's XPN_SPLIT.
NAME_SPLIT: dict[tuple[str, int], tuple[str, str]] = {
    ("P", 5): ("patient_last_name", "patient_first_name"),
}

# R-5 reference range: "low^high" -> two real sub-columns.
RANGE_SPLIT: dict[tuple[str, int], tuple[str, str]] = {
    ("R", 5): ("reference_range_low", "reference_range_high"),
}

_PATIENT_ID_FIELD = "astm_patient_id"
_SPECIMEN_ID_FIELD = "astm_specimen_id"

# Explicit, human-reviewable structural facts (positional, not value-based --
# see module docstring) to auto-confirm at ingest time, same role as HL7's
# STRUCTURAL_LINKS.
STRUCTURAL_LINKS: list[tuple[str, str, str, str, str]] = [
    ("O", _PATIENT_ID_FIELD, "P", "patient_id", "FOREIGN_KEY_TO"),
    ("R", _PATIENT_ID_FIELD, "P", "patient_id", "FOREIGN_KEY_TO"),
    ("R", _SPECIMEN_ID_FIELD, "O", "specimen_id", "FOREIGN_KEY_TO"),
]


def looks_like_astm(payload: str) -> bool:
    """Cheap format sniff: does the payload's first non-blank line look
    like an ASTM header record? "H|\\^&|" is the fixed ASTM delimiter-
    definition opener, as distinct from HL7's "MSH|^~\\&|"."""
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        tokens = line.split("|")
        return len(tokens) > 1 and tokens[0] == "H" and "^&" in tokens[1]
    return False


def _record_row(record_type: str, tokens: list[str]) -> dict[str, str]:
    field_map = RECORD_FIELDS.get(record_type, {})
    row: dict[str, str] = {}
    for idx, value in enumerate(tokens[1:], start=1):
        if not value:
            continue
        split_key = (record_type, idx)
        if split_key in NAME_SPLIT:
            last, first = NAME_SPLIT[split_key]
            parts = value.split("^")
            if parts and parts[0]:
                row[last] = parts[0]
            if len(parts) > 1 and parts[1]:
                row[first] = parts[1]
            continue
        if split_key in RANGE_SPLIT:
            low_name, high_name = RANGE_SPLIT[split_key]
            parts = value.split("^")
            if parts and parts[0]:
                row[low_name] = parts[0]
            if len(parts) > 1 and parts[1]:
                row[high_name] = parts[1]
            continue
        if split_key in TEST_ID_SPLIT:
            components = value.split("^")
            code = components[3] if len(components) > 3 else value
            if code:
                row[TEST_ID_SPLIT[split_key]] = code
            continue
        name = field_map.get(idx)
        if name:
            row[name] = value
    if record_type == "O":
        # Multiple tests can be ordered together ("^^^A\^^^B\^^^C") --
        # captured as one informational field, not split into several rows;
        # each individual test's own result is already the R record's own
        # granularity, which is what row/materialization consumers want.
        raw_test_field = tokens[4] if len(tokens) > 4 else ""
        if raw_test_field:
            codes = []
            for entry in raw_test_field.split("\\"):
                components = entry.split("^")
                code = components[3] if len(components) > 3 else entry
                if code:
                    codes.append(code)
            if codes:
                row["ordered_test_codes"] = ", ".join(codes)
    return row


def _iter_records(payload: str):
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        record_type = line[0]
        if record_type not in RECORD_FIELDS:
            continue
        tokens = line.split("|")
        yield record_type, tokens


def extract_astm_rows(payload: str) -> dict[str, list[dict[str, str]]]:
    """Row-oriented extraction, grouped by record type -- one dict per
    record instance, with astm_patient_id/astm_specimen_id injected into
    O/R records per the positional-correlation rule in the module
    docstring."""
    by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
    current_patient_id: Optional[str] = None
    current_specimen_id: Optional[str] = None

    for record_type, tokens in _iter_records(payload):
        row = _record_row(record_type, tokens)
        if record_type == "P":
            current_patient_id = row.get("patient_id")
            current_specimen_id = None
        elif record_type == "O":
            if current_patient_id:
                row[_PATIENT_ID_FIELD] = current_patient_id
            current_specimen_id = row.get("specimen_id")
        elif record_type == "R":
            if current_patient_id:
                row[_PATIENT_ID_FIELD] = current_patient_id
            if current_specimen_id:
                row[_SPECIMEN_ID_FIELD] = current_specimen_id
        if row:
            by_type[record_type].append(row)

    return dict(by_type)


def extract_astm_by_record(payload: str) -> dict[str, dict[str, list[str]]]:
    """Column-oriented counterpart for schema profiling -- record_type ->
    field_name -> every observed value, same shape hl7_semantics's
    extract_hl7_by_segment returns."""
    by_type = extract_astm_rows(payload)
    out: dict[str, dict[str, list[str]]] = {}
    for record_type, rows in by_type.items():
        field_values: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            for key, val in row.items():
                if val:
                    field_values[key].append(val)
        out[record_type] = dict(field_values)
    return out


def list_astm_record_types(payload: str) -> list[str]:
    if not looks_like_astm(payload):
        return []
    return sorted(extract_astm_by_record(payload).keys())


def auto_link_structure(store, ontology, base_source: str, *, principal=None) -> list:
    """Confirms the STRUCTURAL_LINKS facts as real RelationshipEdges,
    mirroring hl7_semantics.auto_link_structure exactly -- these are
    positional facts about the stream's own structure, not inferred
    candidates, so they're auto-confirmed rather than left for a click."""
    from synapse.matching import score_pair
    from synapse.profiling import SchemaProfiler

    profiler = SchemaProfiler(store)
    created = []
    for rec_a, field_a, rec_b, field_b, predicate in STRUCTURAL_LINKS:
        source_a = f"{base_source}::{rec_a}"
        source_b = f"{base_source}::{rec_b}"
        profiles_a = profiler.profile_source(source_a, principal=principal)
        profiles_b = profiler.profile_source(source_b, principal=principal)
        profile_a = profiles_a.get(field_a)
        profile_b = profiles_b.get(field_b)
        if profile_a is None or profile_b is None:
            continue
        existing = ontology.find_relationship_by_pair(
            {"source_system": source_a, "field_name": field_a},
            {"source_system": source_b, "field_name": field_b},
        )
        if existing is not None:
            created.append(existing)
            continue
        edge = score_pair(store, ontology, profile_a, profile_b, force=True)
        if edge is None:
            continue
        confirmed = ontology.accept_relationship(
            candidate_id=edge.candidate_id,
            source_a=edge.source_a,
            source_b=edge.source_b,
            predicate=predicate,
            match_reasons=list(edge.match_reasons) + ["ASTM structural fact (positional record correlation)"],
            similarity_score=edge.similarity_score,
        )
        created.append(confirmed)
    return created
