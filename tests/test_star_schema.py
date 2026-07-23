"""Star-schema materialization: real fact/dimension tables with real data
loaded, built from confirmed relationships. Classification is a proposed
plan (preview_star_schema), not a silent auto-execute -- execute_star_schema
actually builds it."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from synapse.hl7_semantics import auto_link_structure
from synapse.models import RawObject
from synapse.profiling import SchemaProfiler
from synapse.session import open_session
from synapse.star_schema import execute_star_schema, preview_star_schema
from synapse.store import SemanticStore
from synapse.ontology import OntologyRegistry
from synapse.workspace import Workspace

HL7_PAYLOAD = (
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810083000||ORU^R01|MSG00001|P|2.5.1\n"
    "PID|1||P001^^^HIS^MR||Williams^David||19550604|F\n"
    "ORC|RE|ORD9001|||||^^^20230810083000\n"
    "OBR|1|ORD9001|LAB9001|HGB^Hemoglobin^L|||20230810080000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||14.2|g/dL|13.5-17.5|N\n"
    "MSH|^~\\&|LIS|CityLab|HIS|GeneralHospital|20230810091500||ORU^R01|MSG00002|P|2.5.1\n"
    "PID|1||P002^^^HIS^MR||Chen^Amy||19620311|F\n"
    "ORC|RE|ORD9002|||||^^^20230810091500\n"
    "OBR|1|ORD9002|LAB9002|HGB^Hemoglobin^L|||20230810090000\n"
    "OBX|1|NM|HGB^Hemoglobin^L||13.1|g/dL|13.5-17.5|L\n"
)


def _make_hl7_workspace(store, ontology, name="HL7 Test"):
    ws = Workspace.create(name)
    store.put_workspace(ws)
    store.put_raw(
        RawObject.create(source_system="HL7", payload=HL7_PAYLOAD, acl_tags=["domain:sre", "clearance:l2"], workspace_id=ws.workspace_id)
    )
    auto_link_structure(store, ontology, "HL7")
    return ws


class TestClassification(unittest.TestCase):
    def test_obx_is_fact_pid_orc_obr_msh_are_dimensions(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = _make_hl7_workspace(store, ontology)
        profiler = SchemaProfiler(store)

        plan = preview_star_schema(store, ontology, profiler, [ws.workspace_id])
        fact_tables = {f["table"] for f in plan["facts"]}
        dim_tables = {d["table"] for d in plan["dimensions"]}

        self.assertIn("fact_obx", fact_tables)
        self.assertEqual({"dim_msh", "dim_pid", "dim_orc", "dim_obr"}, dim_tables)

        obx = next(f for f in plan["facts"] if f["table"] == "fact_obx")
        self.assertIn("observation_value", obx["measures"])
        self.assertNotIn("set_id", obx["measures"])  # sequence counter, not a real measure

    def test_obx_foreign_keys_point_at_correct_dimension_fields(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = _make_hl7_workspace(store, ontology)
        profiler = SchemaProfiler(store)

        plan = preview_star_schema(store, ontology, profiler, [ws.workspace_id])
        obx = next(f for f in plan["facts"] if f["table"] == "fact_obx")
        fk_by_table = {fk["dimension_table"]: fk for fk in obx["foreign_keys"]}
        self.assertIn("dim_msh", fk_by_table)
        self.assertEqual(fk_by_table["dim_msh"]["dimension_key_field"], "message_control_id")
        self.assertIn("dim_obr", fk_by_table)
        self.assertEqual(fk_by_table["dim_obr"]["dimension_key_field"], "test_code")

    def test_preview_performs_no_writes(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = _make_hl7_workspace(store, ontology)
        profiler = SchemaProfiler(store)
        rel_count_before = len(ontology.relationships)
        preview_star_schema(store, ontology, profiler, [ws.workspace_id])
        self.assertEqual(len(ontology.relationships), rel_count_before)


class TestDuplicateForeignKeyToSameDimension(unittest.TestCase):
    def test_near_constant_field_excluded_only_one_fk_per_dimension(self):
        # Reproduces a real bug: a fact source with two relationships to
        # the SAME dimension via two different fields (one a genuine
        # varying join key, one a near-constant field that coincidentally
        # matched) must not try to create two "dim_x_key" columns with
        # the same generated name -- and should keep the meaningful one.
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = Workspace.create("Dup FK Test")
        store.put_workspace(ws)

        for i in range(1, 6):
            store.put_raw(
                RawObject.create(
                    source_system="DimSource",
                    payload=f"ref_id: R{i}\nkind: widget\n",
                    acl_tags=["domain:sre", "clearance:l2"],
                    workspace_id=ws.workspace_id,
                )
            )
            store.put_raw(
                RawObject.create(
                    source_system="FactSource",
                    payload=f"ref_id: R{i}\nkind: widget\nmeasure_value: {i * 1.5}\n",
                    acl_tags=["domain:sre", "clearance:l2"],
                    workspace_id=ws.workspace_id,
                )
            )

        profiler = SchemaProfiler(store)
        profiles_a = profiler.profile_source("FactSource")
        profiles_b = profiler.profile_source("DimSource")
        from synapse.matching import score_pair

        for field in ("ref_id", "kind"):
            edge = score_pair(store, ontology, profiles_a[field], profiles_b[field], force=True)
            ontology.accept_relationship(
                candidate_id=edge.candidate_id,
                source_a=edge.source_a,
                source_b=edge.source_b,
                predicate="SAME_ENTITY_AS",
                match_reasons=edge.match_reasons,
                similarity_score=edge.similarity_score,
            )

        plan = preview_star_schema(store, ontology, profiler, [ws.workspace_id])
        fact = next(f for f in plan["facts"] if f["source"] == "FactSource")
        fks_to_dim = [fk for fk in fact["foreign_keys"] if fk["dimension_source"] == "DimSource"]
        self.assertEqual(len(fks_to_dim), 1)
        self.assertEqual(fks_to_dim[0]["fact_field"], "ref_id")  # varying, not the constant "kind"

        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "warehouse.db")
            result = execute_star_schema(store, ontology, profiler, [ws.workspace_id], target)
            row_counts = {t["name"]: t["row_count"] for t in result["tables"]}
            self.assertEqual(row_counts["fact_factsource"], 5)


class TestExecute(unittest.TestCase):
    def test_execute_produces_real_tables_with_correct_row_counts(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = _make_hl7_workspace(store, ontology)
        profiler = SchemaProfiler(store)

        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "warehouse.db")
            result = execute_star_schema(store, ontology, profiler, [ws.workspace_id], target)
            self.assertEqual(result["db_path"], target)
            row_counts = {t["name"]: t["row_count"] for t in result["tables"]}
            self.assertEqual(row_counts["dim_pid"], 2)
            self.assertEqual(row_counts["dim_msh"], 2)
            self.assertEqual(row_counts["fact_obx"], 2)

            conn = sqlite3.connect(target)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cur.fetchall()}
            self.assertIn("fact_obx", tables)
            self.assertIn("dim_pid", tables)
            conn.close()

    def test_fact_rows_resolve_to_correct_dimension_via_join(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = _make_hl7_workspace(store, ontology)
        profiler = SchemaProfiler(store)

        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "warehouse.db")
            execute_star_schema(store, ontology, profiler, [ws.workspace_id], target)

            conn = sqlite3.connect(target)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT f.observation_value, p.patient_id, m.message_control_id
                FROM fact_obx f
                JOIN dim_msh m ON f.dim_msh_key = m.dim_key
                JOIN dim_pid p ON p.hl7_message_id = m.message_control_id
                ORDER BY f.observation_value
                """
            )
            rows = cur.fetchall()
            conn.close()
            self.assertEqual(rows, [("13.1", "P002", "MSG00002"), ("14.2", "P001", "MSG00001")])

    def test_no_foreign_key_resolves_to_the_wrong_dimension_row(self):
        # OBX joins dim_obr on test_code, NOT on OBR's own natural key
        # (placer_order_number) -- this is the exact bug real-data
        # testing caught: resolving via the dimension's chosen key
        # instead of the specific edge's field silently produced
        # nonsense joins.
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = _make_hl7_workspace(store, ontology)
        profiler = SchemaProfiler(store)

        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "warehouse.db")
            execute_star_schema(store, ontology, profiler, [ws.workspace_id], target)
            conn = sqlite3.connect(target)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT f.dim_obr_key FROM fact_obx f WHERE f.dim_obr_key IS NULL
                """
            )
            self.assertEqual(cur.fetchall(), [])  # every OBX row resolved a real OBR
            conn.close()

    def test_workspace_isolation_via_real_session(self):
        session = open_session()
        try:
            ws = Workspace.create("Isolated HL7")
            session.store.put_workspace(ws)
            session.store.put_raw(
                RawObject.create(
                    source_system="HL7Iso",
                    payload=HL7_PAYLOAD,
                    acl_tags=["domain:sre", "clearance:l2"],
                    workspace_id=ws.workspace_id,
                )
            )
            auto_link_structure(session.store, session.ontology, "HL7Iso")
            profiler = SchemaProfiler(session.store)

            with tempfile.TemporaryDirectory() as tmp:
                target = str(Path(tmp) / "warehouse.db")
                result = execute_star_schema(
                    session.store, session.ontology, profiler, [ws.workspace_id], target
                )
                row_counts = {t["name"]: t["row_count"] for t in result["tables"]}
                self.assertEqual(row_counts["fact_obx"], 2)  # only this workspace's 2 messages
        finally:
            session.close()


class TestClinicalFlagColumn(unittest.TestCase):
    """docs/Instrument_Data_Format.md section 4: a derived clinical_flag
    column on fact tables whose shape carries a value + reference range
    (HL7 OBX here; ASTM R and Abbott results use the same mechanism, see
    tests/test_clinical_flags.py for the underlying evaluator)."""

    def test_preview_lists_clinical_flag_column(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = _make_hl7_workspace(store, ontology)
        profiler = SchemaProfiler(store)

        plan = preview_star_schema(store, ontology, profiler, [ws.workspace_id])
        obx = next(f for f in plan["facts"] if f["table"] == "fact_obx")
        self.assertIn("clinical_flag", obx["columns"])

    def test_execute_computes_correct_flags(self):
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = _make_hl7_workspace(store, ontology)
        profiler = SchemaProfiler(store)

        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "warehouse.db")
            execute_star_schema(store, ontology, profiler, [ws.workspace_id], target)
            conn = sqlite3.connect(target)
            cur = conn.cursor()
            cur.execute("SELECT observation_value, clinical_flag FROM fact_obx ORDER BY observation_value")
            rows = cur.fetchall()
            conn.close()
            self.assertEqual(rows, [("13.1", "LOW"), ("14.2", "NORMAL")])

    def test_no_clinical_flag_column_when_shape_not_recognized(self):
        # A fact table with a measure but no reference-range field at all
        # (e.g. Beckman's calculated_value has no range in this dataset)
        # gets no clinical_flag column -- not a guessed/empty one.
        store = SemanticStore()
        ontology = OntologyRegistry.default()
        ontology.store = store
        ws = Workspace.create("No Range")
        store.put_workspace(ws)
        for i in range(1, 4):
            store.put_raw(
                RawObject.create(
                    source_system="Beckman",
                    payload=f"sample_id: S{i}\nrack_no: R1\nassay_abbr: UA\ncalculated_value: {i * 1.5}\nunits: mg/dL\n",
                    acl_tags=["domain:sre", "clearance:l2"],
                    workspace_id=ws.workspace_id,
                )
            )
        profiler = SchemaProfiler(store)
        plan = preview_star_schema(store, ontology, profiler, [ws.workspace_id])
        fact = next((f for f in plan["facts"] if f["source"] == "Beckman"), None)
        self.assertIsNotNone(fact)
        self.assertNotIn("clinical_flag", fact["columns"])


if __name__ == "__main__":
    unittest.main()
