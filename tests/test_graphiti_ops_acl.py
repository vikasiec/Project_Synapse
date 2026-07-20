"""
Active_File.md row 31 (RC-03): `/v1/graphiti/search` had no principal-scoped
filtering at all -- any caller could search the full remote graph regardless
of ACL. Fixed with Graphiti's own native `group_id`/`group_ids` tenant
partition, applied both query-side (passed to `client.search`) and
result-side (dropping any hit whose own `group_id` isn't allowed) -- a
remote graph is a derivative and must not become a policy escape hatch even
if the query-side filter were ever bypassed or unsupported by a given
client.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Optional

from synapse.graph_memory import derive_group_id
from synapse.graphiti_ops import GraphitiOps


@dataclass
class _FakeEdge:
    uuid: str
    name: str
    fact: str
    group_id: Optional[str] = None
    source_node_uuid: Optional[str] = None
    target_node_uuid: Optional[str] = None


class _FakeSearchClient:
    """Records the group_ids it was called with; returns edges spanning
    multiple group_ids regardless, so the result-side filter is what
    actually has to do the work in these tests."""

    def __init__(self, edges: list[_FakeEdge]):
        self._edges = edges
        self.last_group_ids: Optional[list[str]] = "not_called"

    async def search(self, query: str, *, num_results: int = 8, group_ids=None):
        self.last_group_ids = group_ids
        return list(self._edges)


class TestGraphitiOpsAcl(unittest.TestCase):
    def _edges(self) -> list[_FakeEdge]:
        gid_sre = derive_group_id(["domain:sre", "clearance:l2"])
        gid_banking = derive_group_id(["domain:banking", "clearance:l1"])
        return [
            _FakeEdge(uuid="e1", name="n1", fact="sre fact", group_id=gid_sre),
            _FakeEdge(uuid="e2", name="n2", fact="banking fact", group_id=gid_banking),
            _FakeEdge(uuid="e3", name="n3", fact="untagged fact", group_id=None),
        ]

    def test_group_ids_passed_through_to_client_search(self):
        client = _FakeSearchClient(self._edges())
        ops = GraphitiOps(client=client)
        allowed = [derive_group_id(["domain:sre", "clearance:l2"])]
        ops.search("anything", group_ids=allowed)
        self.assertEqual(client.last_group_ids, allowed)

    def test_result_side_filter_drops_hits_outside_allowed_group_ids(self):
        """Even if a client ignored the query-side group_ids filter (this
        fake returns all 3 edges regardless), the result-side check must
        still only surface the allowed one."""
        client = _FakeSearchClient(self._edges())
        ops = GraphitiOps(client=client)
        allowed = [derive_group_id(["domain:sre", "clearance:l2"])]
        hits = ops.search("anything", group_ids=allowed)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].uuid, "e1")

    def test_untagged_edges_are_denied_by_default_when_scoped(self):
        """An edge with no group_id at all must be dropped when a
        restriction is active -- deny-by-default, matching every other ACL
        check in this codebase (empty/missing ACL never means "visible")."""
        client = _FakeSearchClient(self._edges())
        ops = GraphitiOps(client=client)
        hits = ops.search("anything", group_ids=[derive_group_id(["domain:sre", "clearance:l2"])])
        self.assertNotIn("e3", [h.uuid for h in hits])

    def test_empty_allowed_group_ids_returns_nothing_not_everything(self):
        """A principal who can see zero episodes must get zero search
        results, not an unfiltered dump -- confirms group_ids=[] is treated
        as a real restriction, not falsy-therefore-ignored."""
        client = _FakeSearchClient(self._edges())
        ops = GraphitiOps(client=client)
        hits = ops.search("anything", group_ids=[])
        self.assertEqual(hits, [])
        self.assertEqual(client.last_group_ids, [])

    def test_none_group_ids_means_unrestricted_legacy_behavior(self):
        """No principal/group_ids argument at all (the pre-row-31 call
        shape) must keep working exactly as before -- no regression for
        any other caller of GraphitiOps.search."""
        client = _FakeSearchClient(self._edges())
        ops = GraphitiOps(client=client)
        hits = ops.search("anything")
        self.assertEqual(len(hits), 3)
        self.assertIsNone(client.last_group_ids)


if __name__ == "__main__":
    unittest.main()
