#!/usr/bin/env python3
"""
Sense board replay script (docs/Grok_Plan19Jul.txt Phase E3).

Seeds a known incident into .data/sense.db, prints raw/meaning/conflict
counts, and prints the URL to open the Sense board — so the visual-sense
proof can be replayed by a second person in under 5 minutes:

    python scripts/sense_demo.py
    python -m synapse serve --port 8787 --db .data/sense.db
    (open the printed URL, click "Open Sense board ->")
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from synapse.scenarios.checkout_incident import CheckoutIncidentScenario
    from synapse.session import open_session

    db_path = str(ROOT / ".data" / "sense.db")
    session = open_session(db_path)
    try:
        CheckoutIncidentScenario(store=session.store).seed(skip_if_populated=True)

        open_conflicts = sum(
            1 for c in session.store.conflicts.values() if c.status.value == "open"
        )
        summary = {
            "db": db_path,
            "raw_objects": len(session.store.raw_objects),
            "episodes": len(session.store.episodes),
            "entities": len(session.store.entities),
            "facts": len(session.store.facts),
            "conflicts_open": open_conflicts,
            "next_steps": [
                f"python -m synapse serve --port 8787 --db {db_path}",
                "open http://127.0.0.1:8787/  ->  click 'Open Sense board ->'",
            ],
        }
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
