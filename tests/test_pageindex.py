import unittest

from synapse.pageindex import PageIndexLite


class TestPageIndex(unittest.TestCase):
    def test_build_and_route(self):
        text = """# Overview
General intro about checkout.

## Deploy Steps
Use image tag carefully.

## Failure Modes
CrashLoopBackOff after bad canary.
"""
        pi = PageIndexLite()
        tree = pi.build(text, title="runbook")
        self.assertGreaterEqual(len(tree.roots), 1)
        flat = tree.flatten()
        self.assertGreaterEqual(len(flat), 2)
        hits = pi.route(tree, "CrashLoopBackOff failure", top_k=2)
        self.assertTrue(hits)
        self.assertIn("failure", hits[0]["node"]["title"].lower() + hits[0]["node"]["preview"].lower())


if __name__ == "__main__":
    unittest.main()
