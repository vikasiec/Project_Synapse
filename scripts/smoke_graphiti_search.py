#!/usr/bin/env python3
"""
Graphiti search smoke under free-tier budget discipline.

- One search only (no mass LLM calls)
- Secrets never printed
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from synapse.env_load import load_dotenv
    from synapse.graphiti_ops import GraphitiOps

    load_dotenv()
    ops = GraphitiOps()
    try:
        status = ops.status()
        if not status.get("neo4j_ready"):
            print(json.dumps({"ok": False, "reason": "neo4j_not_ready", "status": status}, indent=2))
            return 2
        q = " ".join(sys.argv[1:]) or "checkout canary"
        hits = ops.search(q, num_results=5)
        print(
            json.dumps(
                {
                    "ok": True,
                    "query": q,
                    "hit_count": len(hits),
                    "hits": [h.to_dict() for h in hits],
                    "note": "single search — respect free-tier RPM",
                },
                indent=2,
            )
        )
        return 0
    except Exception as e:
        msg = str(e)
        import os

        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "NEO4J_PASSWORD"):
            v = os.environ.get(k)
            if v:
                msg = msg.replace(v, "***")
        print(json.dumps({"ok": False, "error": msg[:400]}, indent=2))
        return 1
    finally:
        ops.close()


if __name__ == "__main__":
    raise SystemExit(main())
