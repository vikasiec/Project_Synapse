"""
Canonical CSV / HL7 v2.5.1 / FHIR R4 egress converters
(docs/Instrument_Data_Format.md section 5) -- turns an already-materialized
star-schema warehouse (synapse/star_schema.py's real SQLite fact/dimension
tables) back into three standard output shapes, rather than re-deriving
extraction logic a second time.

This is a separate capability from the Warehouse's own SQLite output
(star_schema.py), not a replacement for it: the warehouse is a real
dimensional model meant to be queried directly; egress is a thinner
"give me this data back in a standard interchange shape" step on top of
it, for the cases the spec explicitly asks for (canonical CSV tables,
an HL7 ORU^R01 export, a FHIR Observation Bundle export).

Scope, stated up front: a materialized fact table is a GENERIC shape
(fact_<source> + dim_<source> tables, arbitrary columns) -- there's no
guarantee every fact table looks like a lab result. The HL7/FHIR
serializers below target the common, real shape this project's own fact
tables actually have (a measure column + a foreign key to a patient-like
dimension), and skip a fact table that doesn't have anything joinable to
emit meaningfully rather than emitting a message with fabricated content.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from synapse.models import utc_now_iso


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cur.fetchall()]


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return [row[1] for row in cur.fetchall()]


def _quoted_column_list(columns: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in columns)


def export_csv_tables(db_path: str, output_dir: str) -> dict[str, str]:
    """Writes one CSV per table in the materialized warehouse, named after
    the table itself (fact_<source>.csv / dim_<source>.csv) -- the
    materialized tables are already the "canonical relational tables" the
    spec asks for (real fact/dimension model, not a flat re-derivation);
    this just re-serializes them to files. Returns {table_name: file_path}."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        written: dict[str, str] = {}
        for table in _list_tables(conn):
            columns = _table_columns(conn, table)
            file_path = out_dir / f"{table}.csv"
            cur = conn.execute(f'SELECT {_quoted_column_list(columns)} FROM "{table}"')
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                writer.writerows(cur.fetchall())
            written[table] = str(file_path)
        return written
    finally:
        conn.close()


def _fk_columns(columns: list[str]) -> list[str]:
    return [c for c in columns if c.endswith("_key") and c != "fact_key" and c != "dim_key"]


def _dim_table_for_fk(fk_column: str) -> str:
    return fk_column[: -len("_key")]


def _measure_columns(conn: sqlite3.Connection, table: str, columns: list[str]) -> list[str]:
    """Best-effort: a column is treated as a measure for export purposes if
    at least one non-null value in it parses as a float AND its name
    passes star_schema.py's own _is_measure_field name exclusions (reused
    directly, not re-derived) -- otherwise set_id/*_id/*_index/date/time
    -named numeric-looking columns (sequence counters, join keys) would be
    exported as if they were real measurements, same class of bug
    star_schema.py itself already had to fix once for its own
    classification."""
    from synapse.star_schema import _is_measure_field

    fk_cols = set(_fk_columns(columns))
    candidates = [c for c in columns if c not in fk_cols and c not in ("fact_key",)]
    measures = []
    for c in candidates:
        if not _is_measure_field(c, "Float"):
            continue
        cur = conn.execute(f'SELECT "{c}" FROM "{table}" WHERE "{c}" IS NOT NULL LIMIT 5')
        values = [row[0] for row in cur.fetchall()]
        if values and all(_is_floatish(v) for v in values):
            measures.append(c)
    return measures


def _is_floatish(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _resolve_patient_row(conn: sqlite3.Connection, fact_columns: list[str], fact_row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Finds a patient-identity-carrying dimension row for this fact row,
    up to two hops away. Reuses matching._alias_group_for so this
    recognizes the same vendor-naming variants the AliasMapper does,
    instead of a second, separately-maintained list.

    Real gap this closes: a fact's declared FK doesn't always point
    straight at the patient dimension -- e.g. fact_obx only has a
    dim_msh_key FK (OBX's own confirmed structural link is to MSH, not
    PID), and dim_pid reaches dim_msh only via a shared synthetic value
    (dim_pid.hl7_message_id == dim_msh.message_control_id), the same
    correlation mechanism hl7_semantics.py's own structural links use, not
    a declared foreign key in the materialized schema. Hop 1 checks the
    fact's direct FK dimensions; hop 2, when hop 1 doesn't itself carry a
    patient field, looks for any column value shared between a hop-1
    dimension row and a patient-carrying dimension's own rows."""
    from synapse.matching import _alias_group_for

    dim_tables = [t for t in _list_tables(conn) if t.startswith("dim_")]
    patient_dim_fields: dict[str, str] = {}
    for dt in dim_tables:
        cols = _table_columns(conn, dt)
        field = next((c for c in cols if _alias_group_for(c) == "patient_identity"), None)
        if field:
            patient_dim_fields[dt] = field

    hop1_rows: list[tuple[str, dict[str, Any]]] = []
    for fk in _fk_columns(fact_columns):
        dim_key = fact_row.get(fk)
        if dim_key is None:
            continue
        dim_table = _dim_table_for_fk(fk)
        dim_columns = _table_columns(conn, dim_table)
        cur = conn.execute(
            f'SELECT {_quoted_column_list(dim_columns)} FROM "{dim_table}" WHERE dim_key = ?', (dim_key,)
        )
        row = cur.fetchone()
        if row is None:
            continue
        dim_row = dict(zip(dim_columns, row))
        if dim_table in patient_dim_fields:
            dim_row["_patient_field"] = patient_dim_fields[dim_table]
            return dim_row
        hop1_rows.append((dim_table, dim_row))

    for _dim_table, dim_row in hop1_rows:
        for patient_dim, patient_field in patient_dim_fields.items():
            patient_columns = _table_columns(conn, patient_dim)
            for col, value in dim_row.items():
                if col in ("dim_key", patient_field) or value is None:
                    continue
                if col not in patient_columns:
                    continue
                cur = conn.execute(
                    f'SELECT {_quoted_column_list(patient_columns)} FROM "{patient_dim}" WHERE "{col}" = ?', (value,)
                )
                match = cur.fetchone()
                if match is not None:
                    result = dict(zip(patient_columns, match))
                    result["_patient_field"] = patient_field
                    return result
    return None


def export_hl7(db_path: str) -> str:
    """Builds a real, parseable HL7 v2.5.1 ORU^R01 pipe-delimited text
    blob -- one MSH+PID+OBX message per fact-table row that has both a
    measure and a resolvable patient dimension. Field positions match
    hl7_semantics.py's own SEGMENT_FIELDS exactly, so round-tripping this
    output back through extract_hl7_by_segment recovers the same fields
    (the strongest correctness check available for an export path:
    verified in tests/test_egress.py by doing exactly that)."""
    conn = sqlite3.connect(db_path)
    try:
        messages: list[str] = []
        seq = 0
        for table in _list_tables(conn):
            if not table.startswith("fact_"):
                continue
            columns = _table_columns(conn, table)
            measures = _measure_columns(conn, table, columns)
            if not measures:
                continue
            test_field = next((c for c in columns if "code" in c.lower() and c not in _fk_columns(columns)), None)
            cur = conn.execute(f'SELECT {_quoted_column_list(columns)} FROM "{table}"')
            for raw_row in cur.fetchall():
                fact_row = dict(zip(columns, raw_row))
                patient = _resolve_patient_row(conn, columns, fact_row)
                if patient is None:
                    continue
                seq += 1
                dt = utc_now_iso().replace("-", "").replace(":", "").replace("Z", "").split(".")[0]
                msg_id = f"EGR{seq:06d}"
                patient_id = patient.get(patient["_patient_field"], "")
                msh = f"MSH|^~\\&|SYNAPSE|EGRESS|LIS|EGRESS|{dt}||ORU^R01|{msg_id}|P|2.5.1"
                pid = f"PID|1||{patient_id}^^^SYNAPSE||"
                obx_lines = []
                for i, measure in enumerate(measures, start=1):
                    value = fact_row.get(measure)
                    if value is None:
                        continue
                    test_code = fact_row.get(test_field, measure) if test_field else measure
                    # Field positions match hl7_semantics.SEGMENT_FIELDS["OBX"]
                    # exactly: 1=set_id, 2=value_type, 3=observation_identifier
                    # (CE_SPLIT), 5=observation_value, 11=observation_result_status
                    # -- 6 blank fields (6-10) between value and "F", not 5, so
                    # "F" lands on the real result_status field, not an unlabeled
                    # positional fallback.
                    obx_lines.append(f"OBX|{i}|NM|{test_code}^{measure}^L||{value}||||||F")
                if not obx_lines:
                    seq -= 1
                    continue
                messages.append("\n".join([msh, pid] + obx_lines))
        return "\n".join(messages) + ("\n" if messages else "")
    finally:
        conn.close()


def export_fhir_bundle(db_path: str) -> dict[str, Any]:
    """Builds a FHIR R4 Bundle of Observation resources (+ referenced
    Patient resources) from the materialized warehouse -- same
    fact-row-with-a-measure-and-a-resolvable-patient scope as export_hl7."""
    conn = sqlite3.connect(db_path)
    try:
        entries: list[dict[str, Any]] = []
        seen_patients: set[str] = set()
        seq = 0
        for table in _list_tables(conn):
            if not table.startswith("fact_"):
                continue
            columns = _table_columns(conn, table)
            measures = _measure_columns(conn, table, columns)
            if not measures:
                continue
            cur = conn.execute(f'SELECT {_quoted_column_list(columns)} FROM "{table}"')
            for raw_row in cur.fetchall():
                fact_row = dict(zip(columns, raw_row))
                patient = _resolve_patient_row(conn, columns, fact_row)
                if patient is None:
                    continue
                patient_id = str(patient.get(patient["_patient_field"], ""))
                if not patient_id:
                    continue
                if patient_id not in seen_patients:
                    seen_patients.add(patient_id)
                    entries.append({"resource": {"resourceType": "Patient", "id": patient_id}})
                for measure in measures:
                    value = fact_row.get(measure)
                    if value is None:
                        continue
                    seq += 1
                    entries.append(
                        {
                            "resource": {
                                "resourceType": "Observation",
                                "id": f"egress-obs-{seq}",
                                "status": "final",
                                "code": {"text": measure},
                                "subject": {"reference": f"Patient/{patient_id}"},
                                "valueQuantity": {"value": _coerce_number(value)},
                            }
                        }
                    )
        return {
            "resourceType": "Bundle",
            "type": "collection",
            "id": f"egress-{utc_now_iso().replace(':', '').replace('-', '')}",
            "entry": entries,
        }
    finally:
        conn.close()


def _coerce_number(value: Any) -> Any:
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return value
