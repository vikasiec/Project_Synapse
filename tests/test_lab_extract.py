"""Clinical lab / IVD vertical — Path A extraction + CSV e2e (Claude review ask)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from synapse.connectors.csv_drop import CsvDropConnector
from synapse.connectors.registry import ConnectorRegistry
from synapse.connectors.runner import ConnectorRunner
from synapse.dual_path import DualPathExtractor, HeuristicResidualExtractor
from synapse.extraction import RuleExtractor
from synapse.ingestion import IngestionService
from synapse.ontology import OntologyRegistry
from synapse.session import open_session
from synapse.store import SemanticStore

FERRITIN_PAYLOAD = """Date: 2025-08-12
Test_Name: Ferritin
Result: 28.9
Unit: ug/L
Reference_Range: 15-150
Status: Normal
Comment: Iron stores mid-low
"""

KAGGLE = (
    Path(__file__).resolve().parents[1]
    / ".data"
    / "kaggle_raw"
    / "lab_test_results_public.csv"
)


class TestLabExtract(unittest.TestCase):
    def test_ontology_lab_result(self):
        ont = OntologyRegistry.default()
        self.assertIn("LabResult", ont.types)
        g = ont.govern_extract("LabResult", domain="clinical_lab")
        self.assertEqual(g.ontology_type, "LabResult")
        self.assertEqual(g.ontology_layer, "L1")
        self.assertEqual(g.domain, "clinical_lab")

    def test_path_a_ferritin(self):
        store = SemanticStore()
        ex = RuleExtractor(store, ontology=OntologyRegistry.default())
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land(
            "Lab-LIS",
            FERRITIN_PAYLOAD,
            ["domain:clinical", "clearance:l2"],
        )
        out = ex.extract_from_episode(r.episode, r.raw)
        self.assertIsNotNone(out)
        self.assertEqual(out.entity.entity_type, "LabResult")
        self.assertEqual(out.entity.ontology_type, "LabResult")
        self.assertEqual(out.entity.canonical_name, "Ferritin")
        preds = {f.predicate: f.object for f in out.facts}
        self.assertEqual(preds.get("result"), 28.9)
        self.assertEqual(preds.get("unit"), "ug/L")
        self.assertEqual(preds.get("result_status"), "Normal")
        self.assertIn("reference_range", preds)

    def test_dual_path_invokes_when_lab_entity_found(self):
        store = SemanticStore()
        dual = DualPathExtractor(
            store, residual=HeuristicResidualExtractor()
        )
        dual.path_a = RuleExtractor(store)
        ing = IngestionService(store, domain="clinical_lab")
        r = ing.land(
            "Spreadsheet",
            FERRITIN_PAYLOAD,
            ["domain:clinical", "clearance:l2"],
        )
        res = dual.extract(r.episode, r.raw)
        self.assertEqual(res.entity_name, "Ferritin")
        self.assertGreaterEqual(len(res.deterministic_facts), 2)

    def test_csv_connector_lab_rows_produce_facts(self):
        """Synthetic mini-CSV: every row must become at least one fact."""
        csv_text = (
            "Test_Name,Result,Unit,Reference_Range,Status\n"
            "Ferritin,28.9,ug/L,15-150,Normal\n"
            "HbA1c,5.0,%,4.0-6.0,Normal\n"
            "Total IgE,1.73,KU/L,0.1-100,Normal\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "labs.csv"
            path.write_text(csv_text, encoding="utf-8")
            store = SemanticStore()
            reg = ConnectorRegistry()
            conn = CsvDropConnector(
                path=str(path),
                connector_id="lab-csv-test",
                source_system="Lab-LIS",
                default_acl=["domain:clinical", "clearance:l2"],
            )
            reg.register(conn)
            runner = ConnectorRunner(
                store,
                reg,
                ingestion=IngestionService(store, domain="clinical_lab"),
                dual_path=DualPathExtractor(
                    store, residual=HeuristicResidualExtractor()
                ),
                domain="clinical_lab",
                use_dual_path=True,
            )
            result = runner.poll_one("lab-csv-test")
            self.assertEqual(result.events, 3)
            self.assertGreaterEqual(result.extracted, 3)
            self.assertGreaterEqual(len(store.facts), 6)
            self.assertIsNotNone(store.get_entity_by_name("Ferritin"))
            self.assertIsNotNone(store.get_entity_by_name("HbA1c"))

    @unittest.skipUnless(KAGGLE.is_file(), "Kaggle lab CSV not present")
    def test_kaggle_lab_csv_majority_extract(self):
        """Claude's real dataset: landing already worked; extraction must produce facts."""
        store = SemanticStore()
        reg = ConnectorRegistry()
        conn = CsvDropConnector(
            path=str(KAGGLE),
            connector_id="lab-csv",
            source_system="Spreadsheet",
            default_acl=["domain:clinical", "clearance:l2"],
        )
        reg.register(conn)
        runner = ConnectorRunner(
            store,
            reg,
            ingestion=IngestionService(store, domain="clinical_lab"),
            dual_path=DualPathExtractor(
                store, residual=HeuristicResidualExtractor()
            ),
            domain="clinical_lab",
            use_dual_path=True,
        )
        result = runner.poll_one("lab-csv")
        self.assertGreaterEqual(result.events, 20)
        # Before fix: extracted=0. After: most rows produce entities/facts.
        self.assertGreaterEqual(result.extracted, 20)
        self.assertGreaterEqual(len(store.facts), 40)
        self.assertIsNotNone(store.get_entity_by_name("Ferritin"))

    def test_session_lab_seed_style(self):
        session = open_session()
        try:
            session.ingestion.domain = "clinical_lab"
            r = session.ingestion.land(
                "Lab-Analyzer",
                FERRITIN_PAYLOAD,
                ["domain:clinical", "clearance:l2"],
            )
            out = session.dual_path.extract(r.episode, r.raw)
            self.assertEqual(out.entity_name, "Ferritin")
            ent = session.store.get_entity_by_name("Ferritin")
            self.assertEqual(ent.ontology_type, "LabResult")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
