"""
HL7v2 segment/field semantics for schema profiling (not entity extraction
-- see synapse/extraction.py's _extract_hl7_oru for that side of this same
domain knowledge).

synapse/hl7v2.py deliberately only tokenizes: "Segment *semantics* ... are
the caller's job." This module is that caller's job for the *profiling*
path (Explore/Schema View field discovery), just as extraction.py already
is for the entity-resolution path. Real HL7v2.5.1 field positions, not a
positional-code passthrough -- MSH is the message envelope, PID/ORC/OBR/OBX
are real segments with real field meanings, not "MSH.1, PID.5" blobs.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from typing import Optional

from synapse.hl7v2 import Hl7ParseError, Hl7Segment, looks_like_hl7, parse_hl7_message

# Real HL7v2.5.1 field positions -> canonical names, for the segments this
# project actually parses (MSH/PID/ORC/OBR/OBX/NTE) plus a few common ones
# kept for future-proofing (PV1/EVN/NK1/IN1). A field or segment not listed
# here falls back to "SEG.N" positional naming (see _plain_field_name) --
# nothing is silently dropped, just unlabeled.
SEGMENT_FIELDS: dict[str, dict[int, str]] = {
    "MSH": {
        1: "field_separator", 2: "encoding_characters", 3: "sending_application", 4: "sending_facility",
        5: "receiving_application", 6: "receiving_facility", 7: "message_datetime",
        8: "security", 9: "message_type", 10: "message_control_id",
        11: "processing_id", 12: "version_id",
    },
    "EVN": {
        1: "event_type_code", 2: "recorded_datetime", 4: "event_reason_code",
        5: "operator_id", 6: "event_occurred",
    },
    "PID": {
        1: "set_id", 2: "patient_id_external", 4: "alternate_patient_id",
        6: "mothers_maiden_name", 7: "date_of_birth", 8: "administrative_sex",
        9: "patient_alias", 10: "race", 11: "patient_address", 13: "phone_home",
        14: "phone_business", 15: "primary_language", 16: "marital_status",
        18: "patient_account_number", 19: "ssn_number",
        # 3 (patient_identifier_list) and 5 (patient_name) are handled by
        # CX_SPLIT / XPN_SPLIT below instead -- composite fields split into
        # real sub-columns, not listed here to keep one authoritative place
        # per field index.
    },
    "PV1": {
        1: "set_id", 2: "patient_class", 3: "assigned_patient_location",
        4: "admission_type", 7: "attending_doctor", 8: "referring_doctor",
        10: "hospital_service", 19: "visit_number",
    },
    "ORC": {
        1: "order_control", 2: "placer_order_number", 3: "filler_order_number",
        4: "placer_group_number", 5: "order_status", 6: "response_flag",
        7: "quantity_timing", 9: "transaction_datetime", 10: "entered_by",
        12: "ordering_provider", 21: "ordering_facility_name",
    },
    "OBR": {
        1: "set_id", 2: "placer_order_number", 3: "filler_order_number",
        5: "priority", 6: "requested_datetime", 7: "observation_datetime",
        14: "specimen_received_datetime", 15: "specimen_source",
        16: "ordering_provider", 24: "diagnostic_serv_sect_id", 25: "result_status",
        # 4 (universal_service_id) handled by CE_SPLIT below.
    },
    "OBX": {
        1: "set_id", 2: "value_type", 4: "observation_sub_id",
        5: "observation_value", 6: "units", 7: "reference_range",
        8: "abnormal_flags", 11: "observation_result_status",
        12: "effective_date_of_reference_range", 14: "observation_datetime",
        # 3 (observation_identifier) handled by CE_SPLIT below.
    },
    "NTE": {
        1: "set_id", 2: "source_of_comment", 3: "comment",
    },
    "NK1": {
        1: "set_id", 2: "name", 3: "relationship", 4: "address", 5: "phone_number",
    },
    "IN1": {
        1: "set_id", 2: "insurance_plan_id", 3: "insurance_company_id",
        4: "insurance_company_name",
    },
}

# CE (coded element) composite fields: "code^text^system" split into three
# separately-matchable columns instead of one opaque blob -- this is what
# lets e.g. HL7's OBX-3/OBR-4 test code line up against FHIR's
# code.coding.code during cross-source relationship discovery. Component
# positions per the CE/CWE datatype: 1=code, 2=text, 3=coding system.
# OBR-4 and OBX-3 intentionally emit the SAME output names (both are "what
# test" concepts, at order-level vs result-level) so a structural link
# between them can be asserted by field-name equality (see STRUCTURAL_LINKS).
CE_SPLIT: dict[tuple[str, int], tuple[str, str, str]] = {
    ("OBX", 3): ("test_code", "test_name", "test_coding_system"),
    ("OBR", 4): ("test_code", "test_name", "test_coding_system"),
}

# CX (extended composite ID) fields: id + assigning authority split out --
# the id component (not the full "P000001^^^SYNAPSE" blob) is what should
# actually line up against a plain "patientid"/"pid" column from a CSV or
# FHIR source. Component 1 = id, component 4 = assigning authority.
CX_SPLIT: dict[tuple[str, int], tuple[str, str]] = {
    ("PID", 3): ("patient_id", "patient_id_authority"),
}

# XPN (extended person name) fields: family/given name split out.
# Component 1 = family name, component 2 = given name.
XPN_SPLIT: dict[tuple[str, int], tuple[str, str]] = {
    ("PID", 5): ("patient_last_name", "patient_first_name"),
}

# Synthetic join key injected into every non-MSH segment instance, valued
# from that message's own MSH-10 (message_control_id) -- lets the existing,
# unmodified value-overlap scoring naturally discover "these segments all
# belong to the same message" without any new relationship machinery.
_MESSAGE_ID_FIELD = "hl7_message_id"

# Explicit, human-reviewable list of domain-true HL7 structural facts (not
# inferred candidates) to auto-confirm at ingest time -- see
# auto_link_structure(). Each entry: (seg_a, field_a, seg_b, field_b, predicate).
STRUCTURAL_LINKS: list[tuple[str, str, str, str, str]] = [
    ("PID", _MESSAGE_ID_FIELD, "MSH", "message_control_id", "FOREIGN_KEY_TO"),
    ("ORC", _MESSAGE_ID_FIELD, "MSH", "message_control_id", "FOREIGN_KEY_TO"),
    ("OBR", _MESSAGE_ID_FIELD, "MSH", "message_control_id", "FOREIGN_KEY_TO"),
    ("OBX", _MESSAGE_ID_FIELD, "MSH", "message_control_id", "FOREIGN_KEY_TO"),
    ("ORC", "placer_order_number", "OBR", "placer_order_number", "FOREIGN_KEY_TO"),
    ("OBR", "test_code", "OBX", "test_code", "FOREIGN_KEY_TO"),
]


def _plain_field_name(segment_name: str, index: int) -> str:
    canonical = SEGMENT_FIELDS.get(segment_name, {}).get(index)
    return canonical if canonical else str(index)


def _segment_to_row(segment: Hl7Segment, message_id: Optional[str]) -> dict[str, str]:
    """One segment instance -> one {field_name: value} row, applying the
    same canonical naming + CE/CX/XPN splitting as the column-oriented
    path below. The single place both extract_hl7_by_segment (columns)
    and extract_hl7_rows (rows) get their field semantics from, so the
    two extraction shapes can never silently drift apart."""
    seg_name = segment.name
    row: dict[str, str] = {}
    for idx, f in enumerate(segment.fields, start=1):
        if not f.raw:
            continue
        key = (seg_name, idx)
        if key in CE_SPLIT:
            code_name, text_name, sys_name = CE_SPLIT[key]
            code, text, system = f.component(1), f.component(2), f.component(3)
            if code:
                row[code_name] = code
            if text:
                row[text_name] = text
            if system:
                row[sys_name] = system
            continue
        if key in CX_SPLIT:
            id_name, auth_name = CX_SPLIT[key]
            id_val = f.component(1, repetition=0)
            authority = f.component(4, repetition=0)
            if id_val:
                row[id_name] = id_val
            if authority:
                row[auth_name] = authority
            continue
        if key in XPN_SPLIT:
            last_name, first_name = XPN_SPLIT[key]
            family, given = f.component(1), f.component(2)
            if family:
                row[last_name] = family
            if given:
                row[first_name] = given
            continue
        row[_plain_field_name(seg_name, idx)] = f.raw

    if seg_name != "MSH" and message_id:
        row[_MESSAGE_ID_FIELD] = message_id
    return row


def _emit_segment_field(
    out: dict[str, dict[str, list[str]]], segment: Hl7Segment, message_id: Optional[str]
) -> None:
    bucket = out.setdefault(segment.name, defaultdict(list))
    for k, v in _segment_to_row(segment, message_id).items():
        bucket[k].append(v)


def _parse_hl7_messages(payload: str) -> list:
    """Regroups a payload's lines back into whole HL7 messages and parses
    each -- shared by both the column-oriented and row-oriented
    extractors below.

    Universal newline translation collapses HL7's \\r segment separators
    down to \\n right alongside the \\n message separators -- regroup: a
    new message starts at each line beginning "MSH"; every line after it,
    up to the next MSH, belongs to that same message.
    """
    lines = [ln.strip() for ln in payload.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
    messages: list[list[str]] = []
    for line in lines:
        if looks_like_hl7(line):
            messages.append([line])
        elif messages:
            messages[-1].append(line)

    parsed = []
    for seg_lines in messages:
        try:
            parsed.append(parse_hl7_message("\r".join(seg_lines)))
        except Hl7ParseError:
            continue
    return parsed


def extract_hl7_by_segment(payload: str) -> dict[str, dict[str, list[str]]]:
    """Field-name -> observed-values extraction, grouped by segment type.

    One payload may contain multiple messages; each message's segments
    contribute to their own segment-keyed sub-dict, not one shared flat
    namespace. This is what lets a landed HL7 file present as several
    distinct, correctly-typed virtual sources (MSH/PID/ORC/OBR/OBX)
    instead of one card with positional field codes.
    """
    out: dict[str, dict[str, list[str]]] = {}
    for msg in _parse_hl7_messages(payload):
        msh = msg.first("MSH")
        message_id = msh.value(10) if msh else None
        for seg in msg.segments:
            _emit_segment_field(out, seg, message_id)
    return {seg: dict(fields) for seg, fields in out.items()}


def extract_hl7_rows(payload: str) -> dict[str, list[dict[str, str]]]:
    """Row-oriented counterpart to extract_hl7_by_segment: one dict per
    segment *instance* (not one shared column-list per field), so a
    record's fields stay correlated -- e.g. one OBX's own
    observation_value/units/hl7_message_id stay together as one row,
    rather than fanned out across every OBX in the file. Schema profiling
    intentionally discards this (column-oriented is the right shape for
    field-level stats); star-schema materialization needs it back to
    build real fact/dimension rows."""
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for msg in _parse_hl7_messages(payload):
        msh = msg.first("MSH")
        message_id = msh.value(10) if msh else None
        for seg in msg.segments:
            row = _segment_to_row(seg, message_id)
            if row:
                out[seg.name].append(row)
    return dict(out)


def list_hl7_segments(payload: str) -> list[str]:
    """Segment type names present in a payload, or [] if it isn't HL7 --
    used to decide whether a source should be listed/profiled as several
    virtual sub-sources instead of one flat one."""
    if not looks_like_hl7(payload.lstrip()):
        return []
    return sorted(extract_hl7_by_segment(payload).keys())


# One-time correction table for RelationshipEdges confirmed before this
# segment/resourceType-aware profiling existed: their field identity used
# the old flat naming ("OBX.5", "entry.resource.valueQuantity.value"),
# which no longer resolves to anything now that these sources decompose
# into virtual sub-sources with real semantic field names. Small and
# explicit (reviewable at a glance) rather than an automatic reverse-
# derivation -- each entry: (old_source, old_field) -> (new_source, new_field).
LEGACY_FIELD_RENAME: dict[tuple[str, str], tuple[str, str]] = {
    ("new_data_hl7_v2_oru_r01", "OBX.5"): ("new_data_hl7_v2_oru_r01::OBX", "observation_value"),
    ("new_data_hl7_v2_oru_r01", "OBX.6"): ("new_data_hl7_v2_oru_r01::OBX", "units"),
    ("new_data_hl7_v2_oru_r01", "ORC.2"): ("new_data_hl7_v2_oru_r01::ORC", "placer_order_number"),
    ("new_data_fhir_observations", "entry.resource.valueQuantity.value"): (
        "new_data_fhir_observations::Observation",
        "valueQuantity.value",
    ),
}


def migrate_legacy_field_names(store, ontology) -> int:
    """Rewrites any already-confirmed RelationshipEdge still pointing at a
    pre-decomposition field identity (see LEGACY_FIELD_RENAME) in place --
    same relationship_id/predicate/accepted_at, corrected source_system/
    field_name -- so a prior confirmation isn't silently orphaned into a
    dangling Schema View edge by this change. Idempotent: nothing left in
    the old naming after the first successful run, so later calls (every
    session start) are a fast no-op. Returns the number of edges rewritten."""
    rewritten = 0
    for edge in list(ontology.relationships.values()):
        new_a = LEGACY_FIELD_RENAME.get((edge.source_a.get("source_system"), edge.source_a.get("field_name")))
        new_b = LEGACY_FIELD_RENAME.get((edge.source_b.get("source_system"), edge.source_b.get("field_name")))
        if new_a is None and new_b is None:
            continue
        source_a = (
            {"source_system": new_a[0], "field_name": new_a[1]} if new_a else dict(edge.source_a)
        )
        source_b = (
            {"source_system": new_b[0], "field_name": new_b[1]} if new_b else dict(edge.source_b)
        )
        updated = dataclasses.replace(edge, source_a=source_a, source_b=source_b)
        ontology.relationships[edge.relationship_id] = updated
        if store is not None:
            store.put_relationship_edge(updated)
        rewritten += 1
    return rewritten


def auto_link_structure(store, ontology, base_source: str, *, principal=None) -> list:
    """Auto-confirms the true structural relationships within one landed
    HL7 source (message envelope <-> patient/order/result, order <->
    result-panel, panel <-> result) -- these are facts about the file's
    own structure, not inferred cross-source guesses, so they're created
    already-confirmed rather than left as candidates needing a click.
    Idempotent: skips any pair already present in the ontology, so
    re-landing the same (or a similarly-shaped) file is a safe no-op.
    Returns the list of newly-created RelationshipEdge objects."""
    from synapse.matching import score_pair
    from synapse.profiling import SchemaProfiler

    profiler = SchemaProfiler(store)
    created = []
    for seg_a, field_a, seg_b, field_b, predicate in STRUCTURAL_LINKS:
        source_a_name = f"{base_source}::{seg_a}"
        source_b_name = f"{base_source}::{seg_b}"
        profiles_a = profiler.profile_source(source_a_name, principal=principal)
        profiles_b = profiler.profile_source(source_b_name, principal=principal)
        profile_a = profiles_a.get(field_a)
        profile_b = profiles_b.get(field_b)
        if profile_a is None or profile_b is None:
            continue  # segment not present in this message set

        source_a_ref = {"source_system": source_a_name, "field_name": field_a}
        source_b_ref = {"source_system": source_b_name, "field_name": field_b}
        if ontology.find_relationship_by_pair(source_a_ref, source_b_ref) is not None:
            continue  # already linked -- idempotent re-land

        edge = score_pair(store, ontology, profile_a, profile_b, force=True)
        if edge is None:
            continue
        created.append(
            ontology.accept_relationship(
                candidate_id=edge.candidate_id,
                source_a=edge.source_a,
                source_b=edge.source_b,
                predicate=predicate,
                match_reasons=list(edge.match_reasons) + ["Structural HL7 message linkage (not a matched guess)"],
                similarity_score=edge.similarity_score,
            )
        )
    return created
