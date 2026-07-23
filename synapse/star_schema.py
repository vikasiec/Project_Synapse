"""
Star-schema materialization: turns a workspace's (or a combined super
schema's) confirmed relationships into real fact/dimension tables with
real data loaded, rather than leaving them as a discovery/documentation
layer only.

Two-step by design, not a silent auto-execute: fact/dimension
classification is a judgment call (unlike the HL7/FHIR structural links,
which are deterministic facts about a file's own format), so
preview_star_schema() proposes a plan the caller reviews, and
execute_star_schema() actually builds it -- same curate-before-commit
shape as everything else in this app.

Classification heuristic:
  - A source is a FACT candidate if it has at least one measure-shaped
    field (data_type Float or Integer -- deliberately excluding
    Integer8, which this project's pattern table reserves for ID-shaped
    8-digit codes, not measurements).
  - Everything else is a DIMENSION candidate.
  - Sources tied together by SAME_ENTITY_AS merge into one *conformed*
    dimension keyed by their shared field (e.g. LIS `patientid` and HL7
    `PID.patient_id` become one Patient dimension) -- direct reuse of
    relationship data already captured, not a new concept.
  - Join paths from a fact to a dimension are read off *any* confirmed
    relationship (SAME_ENTITY_AS or FOREIGN_KEY_TO) touching one of the
    fact's non-measure fields -- predicate encodes curation semantics
    ("same identity" vs "a reference"), but both equally guarantee "these
    values line up," which is all a join needs. FOREIGN_KEY_TO edges
    additionally confirm directionality when present.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from synapse.clinical_flags import compute_flag_for_row, compute_flag_for_row_split_range
from synapse.row_extraction import extract_rows
from synapse.super_schema import compute_super_schema

_MEASURE_TYPES = {"Float", "Integer"}

# Known (value_field, combined_range_field) or (value_field, low_field,
# high_field) shapes this project's formats actually emit a reference
# range in -- docs/Instrument_Data_Format.md section 4's clinical
# normalization engine. Finite and explicit (not a generic "guess which
# columns pair up" heuristic) since a wrong guess would silently fabricate
# a clinical severity flag from unrelated columns; a fact table whose
# shape isn't listed here simply gets no clinical_flag column, same "don't
# guess" discipline as everywhere else in this module.
_CLINICAL_FLAG_SHAPES: list[tuple[str, str, str]] = [
    ("observation_value", "reference_range", ""),  # HL7 OBX
    ("resultValue", "referenceRange", ""),  # Abbott Alinity results
    ("result_value", "reference_range_low", "reference_range_high"),  # ASTM R
]

_CLINICAL_FLAG_COLUMN = "clinical_flag"


def _clinical_flag_shape_for(columns: set[str]) -> Optional[tuple[str, str, str]]:
    for value_field, range_a, range_b in _CLINICAL_FLAG_SHAPES:
        if value_field not in columns:
            continue
        if range_b:
            if range_a in columns and range_b in columns:
                return value_field, range_a, range_b
        elif range_a in columns:
            return value_field, range_a, ""
    return None


def _compute_clinical_flag(row: dict[str, str], shape: tuple[str, str, str]) -> Optional[str]:
    value_field, range_a, range_b = shape
    if range_b:
        return compute_flag_for_row_split_range(row, value_field, range_a, range_b)
    return compute_flag_for_row(row, value_field, range_a)


def _is_measure_field(name: str, data_type: str) -> bool:
    """Numeric alone isn't enough -- HL7's `set_id` (a per-segment
    sequence counter, "1", "2", ...) and mis-typed timestamp fields
    (profiling's pattern table doesn't recognize HL7's `YYYYMMDDHHMMSS`
    shape as a real Timestamp, so it falls through to Integer) both
    match Float/Integer without being real measurements. Caught by
    testing this classification against the real live dataset, not
    assumed correct -- `set_id` was wrongly pulling PID into the FACT
    side before this exclusion existed. `_index` catches the same class
    of bug for vendor_json_semantics.py's synthetic positional join keys
    (e.g. "alinityBatchExport_index") -- a small integer that identifies
    a record, not a measurement of one."""
    if data_type not in _MEASURE_TYPES:
        return False
    lname = name.lower()
    if lname == "set_id" or lname.endswith("id") or lname.endswith("index"):
        return False
    if any(tok in lname for tok in ("date", "time")):
        return False
    return True


def _measure_fields(profile_by_field: dict) -> list[str]:
    return [name for name, p in profile_by_field.items() if _is_measure_field(name, p.data_type)]


def _best_natural_key(
    source: str, profile_by_field: dict, referenced_fields: set[str], referencing_fields: set[str]
) -> Optional[str]:
    """Prefers a field this source is *referenced by* (other sources
    point at it -- real curated evidence this field IS the source's own
    identity), over a field this source merely *references outward*
    (e.g. PID's own hl7_message_id points at MSH -- that's PID's foreign
    key to the message, not PID's identity) or the generic
    highest-entropy id/code-shaped guess when no relationship grounds it
    at all."""
    referenced = [f for f in referenced_fields if f in profile_by_field]
    if referenced:
        return sorted(referenced, key=lambda f: -profile_by_field[f].entropy_score)[0]
    referencing = [f for f in referencing_fields if f in profile_by_field]
    if referencing:
        return sorted(referencing, key=lambda f: -profile_by_field[f].entropy_score)[0]
    id_like = [
        name
        for name, p in profile_by_field.items()
        if p.data_type not in _MEASURE_TYPES and ("id" in name.lower() or "code" in name.lower() or "key" in name.lower())
    ]
    pool = id_like or [n for n, p in profile_by_field.items() if p.data_type not in _MEASURE_TYPES]
    if not pool:
        return None
    return sorted(pool, key=lambda f: -profile_by_field[f].entropy_score)[0]


def _plan(store, ontology, profiler, workspace_ids: list[str], *, principal=None) -> dict[str, Any]:
    combined = compute_super_schema(store, ontology, profiler, workspace_ids, principal=principal)
    sources = [s["source_system"] for s in combined["sources"]]
    relationships = combined["relationships"]

    profiles_by_source = {s: profiler.profile_source(s, principal=principal) for s in sources}
    measures_by_source = {s: _measure_fields(profiles_by_source[s]) for s in sources}
    fact_sources = {s for s in sources if measures_by_source[s]}
    dimension_sources = [s for s in sources if s not in fact_sources]

    # Per-source field evidence for natural-key selection, split by
    # direction: "referenced" (other sources point at this field --
    # real evidence it IS this source's identity) vs "referencing" (this
    # source points outward with it, e.g. PID's own hl7_message_id
    # pointing at MSH -- that's PID's foreign key, not PID's identity).
    # FOREIGN_KEY_TO edges are directional (source_a references
    # source_b); SAME_ENTITY_AS is symmetric, so both sides count as
    # "referenced" (there's no reference direction to read from it).
    referenced_fields: dict[str, set[str]] = {s: set() for s in sources}
    referencing_fields: dict[str, set[str]] = {s: set() for s in sources}
    touched_fields: dict[str, set[str]] = {s: set() for s in sources}
    for r in relationships:
        a_src, a_field = r["source_a"]["source_system"], r["source_a"]["field_name"]
        b_src, b_field = r["source_b"]["source_system"], r["source_b"]["field_name"]
        touched_fields.setdefault(a_src, set()).add(a_field)
        touched_fields.setdefault(b_src, set()).add(b_field)
        if r["predicate"] == "FOREIGN_KEY_TO":
            referencing_fields.setdefault(a_src, set()).add(a_field)
            referenced_fields.setdefault(b_src, set()).add(b_field)
        else:
            referenced_fields.setdefault(a_src, set()).add(a_field)
            referenced_fields.setdefault(b_src, set()).add(b_field)

    # One dimension table per source (no cross-source conformed-dimension
    # merging in this version): tested against the real live dataset,
    # transitively unioning every SAME_ENTITY_AS-connected dimension
    # produced one incorrect mega-table (Order + Barcode + Patient +
    # Worklist all merged, because they're pairwise linked through a
    # chain of *different* shared business keys, not because they're the
    # same real-world entity). Distinguishing "shares a join key" from
    # "is the same grain" reliably needs more than this heuristic can
    # honestly claim yet -- deferred rather than shipped wrong. Join
    # paths between fact and dimension tables (below) already capture
    # the real, useful relationships without that risk.
    dim_table_for_source: dict[str, str] = {}
    dimension_plans = []
    for s in sorted(dimension_sources):
        natural_key = _best_natural_key(
            s, profiles_by_source[s], referenced_fields.get(s, set()), referencing_fields.get(s, set())
        )
        table_name = f"dim_{s.split('::')[-1].lower()}"
        dim_table_for_source[s] = table_name
        dimension_plans.append(
            {
                "table": table_name,
                "sources": [s],
                "natural_key": natural_key,
                "natural_key_is_guess": natural_key not in touched_fields.get(s, set()),
                "columns": sorted(profiles_by_source[s].keys()),
            }
        )

    fact_plans = []
    for s in sorted(fact_sources):
        fk_columns = []
        for r in relationships:
            a_src, a_field = r["source_a"]["source_system"], r["source_a"]["field_name"]
            b_src, b_field = r["source_b"]["source_system"], r["source_b"]["field_name"]
            # The join field on the dimension side is THIS edge's own
            # field, not necessarily the dimension's chosen natural_key
            # (a dimension can be joined to by more than one edge, on
            # different fields -- e.g. OBR is joined by ORC via
            # placer_order_number but by OBX via test_code; resolving
            # every fact FK through OBR's single natural_key would look
            # up the wrong column entirely for the test_code edge).
            if a_src == s and a_field not in measures_by_source[s] and b_src in dim_table_for_source:
                fk_columns.append(
                    {
                        "fact_field": a_field,
                        "dimension_table": dim_table_for_source[b_src],
                        "dimension_source": b_src,
                        "dimension_key_field": b_field,
                    }
                )
            elif b_src == s and b_field not in measures_by_source[s] and a_src in dim_table_for_source:
                fk_columns.append(
                    {
                        "fact_field": b_field,
                        "dimension_table": dim_table_for_source[a_src],
                        "dimension_source": a_src,
                        "dimension_key_field": a_field,
                    }
                )
        # A near-constant field (e.g. a FHIR resourceType column that's
        # the same literal string on every row) can't usefully identify a
        # SPECIFIC dimension row and isn't a real join key even if it
        # happens to be relationship-tagged -- exclude it up front.
        fk_columns = [fk for fk in fk_columns if profiles_by_source[s][fk["fact_field"]].entropy_score >= 0.05]

        # At most one FK per target dimension table (the generated output
        # column is named after the dimension table -- two different
        # fact_fields both pointing at the same dimension would collide
        # on that name). Prefer the higher-entropy field: more likely a
        # genuine identifying key than a coincidental low-cardinality match.
        best_by_table: dict[str, dict] = {}
        for fk in fk_columns:
            table = fk["dimension_table"]
            existing = best_by_table.get(table)
            if existing is None or profiles_by_source[s][fk["fact_field"]].entropy_score > profiles_by_source[s][
                existing["fact_field"]
            ].entropy_score:
                best_by_table[table] = fk
        unique_fks = list(best_by_table.values())

        source_columns = sorted(profiles_by_source[s].keys())
        clinical_flag_shape = _clinical_flag_shape_for(set(source_columns))
        display_columns = source_columns + ([_CLINICAL_FLAG_COLUMN] if clinical_flag_shape else [])
        fact_plans.append(
            {
                "table": f"fact_{s.split('::')[-1].lower()}",
                "source": s,
                "measures": measures_by_source[s],
                "foreign_keys": unique_fks,
                "columns": display_columns,
                "clinical_flag_shape": clinical_flag_shape,
            }
        )

    return {
        "workspace_ids": workspace_ids,
        "facts": fact_plans,
        "dimensions": dimension_plans,
        "profiles_by_source": profiles_by_source,
    }


def preview_star_schema(store, ontology, profiler, workspace_ids: list[str], *, principal=None) -> dict[str, Any]:
    plan = _plan(store, ontology, profiler, workspace_ids, principal=principal)
    return {
        "workspace_ids": plan["workspace_ids"],
        "facts": [{k: v for k, v in f.items() if k != "profiles_by_source"} for f in plan["facts"]],
        "dimensions": plan["dimensions"],
    }


def _rows_for_source(profiler, source: str, principal) -> list[dict[str, str]]:
    base, sub = profiler._split_virtual(source)
    raws = profiler._visible_raw_for_source(base, principal, None)
    return extract_rows(raws, type_filter=sub)


def execute_star_schema(
    store, ontology, profiler, workspace_ids: list[str], target_db_path: str, *, principal=None
) -> dict[str, Any]:
    """Builds the plan preview_star_schema proposes and actually loads it:
    creates a new SQLite file at target_db_path (does not touch the
    source SemanticStore at all -- purely additive output), one
    dim_<name> table per dimension (surrogate dim_key + natural key +
    every profiled column, deduped by natural key), one fact_<name>
    table per fact (measure columns + FK columns resolved to their
    target dimension's dim_key, or NULL if a fact row's key value never
    appeared in that dimension)."""
    plan = _plan(store, ontology, profiler, workspace_ids, principal=principal)

    Path(target_db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target_db_path)
    try:
        tables_summary: list[dict[str, Any]] = []
        # table -> field -> value -> dim_key. Indexed by every column, not
        # just the dimension's own chosen natural key -- a dimension can
        # be joined to by more than one edge, on different fields (e.g.
        # OBR is joined by ORC via placer_order_number but by OBX via
        # test_code); first-seen wins if a field's values aren't
        # actually unique enough to be a real join key on their own.
        dim_field_lookup: dict[str, dict[str, dict[str, int]]] = {}

        for dim in plan["dimensions"]:
            source = dim["sources"][0]
            rows = _rows_for_source(profiler, source, principal)
            natural_key = dim["natural_key"]
            columns = dim["columns"]

            seen_keys: dict[str, int] = {}
            table_rows: list[tuple[int, dict[str, str]]] = []
            next_key = 1
            for row in rows:
                key_val = row.get(natural_key) if natural_key else None
                if natural_key and key_val is None:
                    continue
                dedup_on = key_val if natural_key else str(next_key)
                if dedup_on in seen_keys:
                    continue
                dim_key = next_key
                next_key += 1
                seen_keys[dedup_on] = dim_key
                table_rows.append((dim_key, row))

            table_name = dim["table"]
            col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
            conn.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" (dim_key INTEGER PRIMARY KEY{"," if columns else ""} {col_defs})')
            col_list = ", ".join(['dim_key'] + [f'"{c}"' for c in columns])
            placeholders = ", ".join(["?"] * (len(columns) + 1))
            conn.executemany(
                f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})',
                [[dim_key] + [row.get(c) for c in columns] for dim_key, row in table_rows],
            )

            field_index: dict[str, dict[str, int]] = {}
            for dim_key, row in table_rows:
                for col in columns:
                    val = row.get(col)
                    if val is None:
                        continue
                    field_index.setdefault(col, {}).setdefault(val, dim_key)
            dim_field_lookup[table_name] = field_index
            tables_summary.append({"name": table_name, "kind": "dimension", "row_count": len(table_rows)})

        for fact in plan["facts"]:
            source = fact["source"]
            rows = _rows_for_source(profiler, source, principal)
            fk_specs = fact["foreign_keys"]
            measure_cols = fact["measures"]
            clinical_flag_shape = fact["clinical_flag_shape"]
            fk_fact_fields = {fk["fact_field"] for fk in fk_specs}
            other_cols = [
                c
                for c in fact["columns"]
                if c not in measure_cols and c not in fk_fact_fields and c != _CLINICAL_FLAG_COLUMN
            ]
            fk_out_cols = [f'{fk["dimension_table"]}_key' for fk in fk_specs]

            table_name = fact["table"]
            flag_cols = [_CLINICAL_FLAG_COLUMN] if clinical_flag_shape else []
            all_cols = fk_out_cols + measure_cols + other_cols + flag_cols
            col_defs = ", ".join(
                f'"{c}" {"INTEGER" if c in fk_out_cols else "TEXT"}' for c in all_cols
            )
            conn.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" (fact_key INTEGER PRIMARY KEY{"," if all_cols else ""} {col_defs})')

            insert_rows = []
            for row in rows:
                values: list[Any] = []
                for fk in fk_specs:
                    raw_val = row.get(fk["fact_field"])
                    lookup = dim_field_lookup.get(fk["dimension_table"], {}).get(fk["dimension_key_field"], {})
                    values.append(lookup.get(raw_val) if raw_val is not None else None)
                for c in measure_cols:
                    values.append(row.get(c))
                for c in other_cols:
                    values.append(row.get(c))
                if clinical_flag_shape:
                    values.append(_compute_clinical_flag(row, clinical_flag_shape))
                insert_rows.append(values)

            col_list = ", ".join([f'"{c}"' for c in all_cols])
            placeholders = ", ".join(["?"] * len(all_cols))
            if all_cols:
                conn.executemany(f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})', insert_rows)
            tables_summary.append({"name": table_name, "kind": "fact", "row_count": len(insert_rows)})

        conn.commit()
    finally:
        conn.close()

    return {"db_path": str(target_db_path), "tables": tables_summary}
