"""
Load local `.env` into process env (stdlib only).

- Never logs values
- Does not override already-set environment variables
- Ignores missing `.env` silently
"""

from __future__ import annotations

from pathlib import Path
import os


def load_dotenv(path: str | None = None) -> bool:
    """
    Parse KEY=VALUE lines from .env into os.environ.
    Returns True if a file was found and read.
    """
    root = Path(__file__).resolve().parent.parent
    env_path = Path(path) if path else root / ".env"
    if not env_path.is_file():
        return False

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if not key:
            continue
        # Do not override explicit shell exports
        if key in os.environ and os.environ.get(key):
            continue
        os.environ[key] = val
    return True
