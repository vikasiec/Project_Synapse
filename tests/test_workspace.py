"""Workspaces: the top-level project boundary sources are imported into.
One workspace's confirmed relationships are its schema; multiple
workspaces give multiple schemas."""

from __future__ import annotations

import unittest

from synapse.models import RawObject
from synapse.session import open_session
from synapse.store import SemanticStore
from synapse.workspace import DEFAULT_WORKSPACE_ID, Workspace


class TestWorkspace(unittest.TestCase):
    def test_put_and_lookup(self) -> None:
        store = SemanticStore()
        ws = Workspace.create("Lab Ops", "Lab data")
        store.put_workspace(ws)
        self.assertIn(ws.workspace_id, store.workspaces)
        self.assertEqual(store.workspaces[ws.workspace_id].name, "Lab Ops")

    def test_raw_object_defaults_to_default_workspace(self) -> None:
        raw = RawObject.create(source_system="X", payload="a: 1", acl_tags=[])
        self.assertEqual(raw.workspace_id, "default")

    def test_workspace_for_source_resolves_real_and_virtual_names(self) -> None:
        store = SemanticStore()
        ws = Workspace.create("Clinical")
        store.put_workspace(ws)
        store.put_raw(
            RawObject.create(source_system="LabFile", payload="a: 1", acl_tags=[], workspace_id=ws.workspace_id)
        )
        self.assertEqual(store.workspace_for_source("LabFile"), ws.workspace_id)
        # A virtual sub-source ("base::SEGMENT") resolves back to the same
        # workspace as its base source.
        self.assertEqual(store.workspace_for_source("LabFile::PID"), ws.workspace_id)

    def test_workspace_for_unknown_source_is_none(self) -> None:
        store = SemanticStore()
        self.assertIsNone(store.workspace_for_source("Nope"))

    def test_ensure_default_workspace_idempotent(self) -> None:
        store = SemanticStore()
        first = store.ensure_default_workspace()
        second = store.ensure_default_workspace()
        self.assertEqual(first.workspace_id, DEFAULT_WORKSPACE_ID)
        self.assertEqual(first.workspace_id, second.workspace_id)
        self.assertEqual(len(store.workspaces), 1)

    def test_open_session_auto_creates_default_workspace(self) -> None:
        session = open_session()
        self.assertIn(DEFAULT_WORKSPACE_ID, session.store.workspaces)
        session.close()


if __name__ == "__main__":
    unittest.main()
