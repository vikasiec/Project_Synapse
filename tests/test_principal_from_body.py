"""
api.py's l1/l2 demo-preset principals hardcoded domain:sre/revenue/identity
-- the banking pack's ASK path returned 403 through the actual UI request
shape because domain:banking was never in that list. Found via Codex's
Sense-board verification (Active_File.md row 12). Fixed generically: the
preset now derives its domain tags from what's actually landed in the store
(store.known_acl_domains()) instead of a hardcoded list.
"""

from __future__ import annotations

import unittest

from synapse.api import _principal_from_body
from synapse.models import RawObject
from synapse.store import SemanticStore


class TestPrincipalFromBody(unittest.TestCase):
    def test_l2_preset_includes_domains_actually_in_the_store(self):
        store = SemanticStore()
        store.put_raw(
            RawObject.create("Bank-CoreBanking", "x", ["domain:banking", "clearance:l2"])
        )
        p = _principal_from_body({"principal": "l2"}, store)
        self.assertIn("domain:banking", p.attributes)

    def test_l2_preset_includes_multiple_domains(self):
        store = SemanticStore()
        store.put_raw(
            RawObject.create("HIS-Patients", "x", ["domain:clinical", "clearance:l2"])
        )
        store.put_raw(
            RawObject.create("Bank-CoreBanking", "y", ["domain:banking", "clearance:l2"])
        )
        p = _principal_from_body({"principal": "l2"}, store)
        self.assertIn("domain:clinical", p.attributes)
        self.assertIn("domain:banking", p.attributes)

    def test_l1_preset_also_derives_domains(self):
        store = SemanticStore()
        store.put_raw(
            RawObject.create("Bank-CoreBanking", "x", ["domain:banking", "clearance:l2"])
        )
        p = _principal_from_body({"principal": "l1"}, store)
        self.assertIn("domain:banking", p.attributes)
        self.assertIn("clearance:l1", p.attributes)

    def test_no_store_falls_back_to_static_list(self):
        p = _principal_from_body({"principal": "l2"}, None)
        self.assertIn("domain:sre", p.attributes)
        self.assertIn("domain:revenue", p.attributes)
        self.assertIn("domain:identity", p.attributes)

    def test_empty_store_falls_back_to_static_list(self):
        p = _principal_from_body({"principal": "l2"}, SemanticStore())
        self.assertIn("domain:sre", p.attributes)

    def test_explicit_dict_principal_unaffected(self):
        store = SemanticStore()
        store.put_raw(
            RawObject.create("Bank-CoreBanking", "x", ["domain:banking", "clearance:l2"])
        )
        p = _principal_from_body(
            {"principal": {"id": "custom", "attributes": ["domain:only-this", "clearance:l1"]}},
            store,
        )
        self.assertEqual(sorted(p.attributes), ["clearance:l1", "domain:only-this"])


if __name__ == "__main__":
    unittest.main()
