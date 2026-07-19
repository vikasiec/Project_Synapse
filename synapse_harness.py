#!/usr/bin/env python3
"""
Project Synapse entrypoint.

Usage:
  python synapse_harness.py                  # full simulation
  python synapse_harness.py --db .data/x.db
  python -m synapse simulate
  python -m synapse eval
  python -m synapse serve --port 8787
"""

from synapse.cli import main

if __name__ == "__main__":
    main()
