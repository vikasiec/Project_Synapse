import unittest

from synapse.models import RawObject
from synapse.security import (
    Principal,
    derived_acl_from_raw,
    filter_raw_objects,
    intersect_acl,
    principal_may_access,
)


class TestSecurity(unittest.TestCase):
    def test_intersect_acl(self):
        self.assertEqual(intersect_acl([["a", "b"], ["b", "c"]]), {"b"})
        self.assertEqual(intersect_acl([]), set())

    def test_principal_must_cover_required(self):
        p = Principal.from_tags("u", ["domain:sre", "clearance:l2"])
        self.assertTrue(principal_may_access(p, {"domain:sre", "clearance:l2"}))
        self.assertFalse(principal_may_access(p, {"domain:sre", "clearance:l2", "channel:x"}))
        self.assertFalse(principal_may_access(p, set()))

    def test_filter_raw_by_acl(self):
        r1 = RawObject.create("a", "p1", ["domain:sre", "clearance:l2"])
        r2 = RawObject.create("b", "p2", ["domain:sre", "clearance:l1"])
        l2 = Principal.from_tags("u2", ["domain:sre", "clearance:l2"])
        l1 = Principal.from_tags("u1", ["domain:sre", "clearance:l1"])
        self.assertEqual(len(filter_raw_objects(l2, [r1, r2])), 1)
        self.assertEqual(len(filter_raw_objects(l1, [r1, r2])), 1)
        self.assertEqual(filter_raw_objects(l1, [r1, r2])[0].source_system, "b")

    def test_derived_acl_intersection(self):
        objs = [
            RawObject.create("a", "p1", ["domain:sre", "clearance:l2"]),
            RawObject.create("b", "p2", ["domain:sre", "clearance:l2", "channel:incidents"]),
        ]
        self.assertEqual(derived_acl_from_raw(objs), {"domain:sre", "clearance:l2"})


if __name__ == "__main__":
    unittest.main()
