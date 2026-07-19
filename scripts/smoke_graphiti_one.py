"""Push a single short episode to Graphiti — free-tier friendly. No secrets printed."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main() -> int:
    from synapse.env_load import load_dotenv

    load_dotenv()
    from synapse.graphiti_factory import build_graphiti_client

    client, label = build_graphiti_client()
    print("CLIENT", label)
    build = getattr(client, "build_indices_and_constraints", None)
    if callable(build):
        await build()
        print("INDICES_OK")

    result = await client.add_episode(
        name="synapse-smoke-1",
        episode_body=(
            "checkout-service: build successful for v9.9.2. "
            "On-call notes partial EU canary traffic."
        ),
        source_description="synapse_poc",
        reference_time=datetime.now(timezone.utc),
    )
    print("EPISODE_OK", type(result).__name__)
    # close driver if present
    close = getattr(client, "close", None)
    if callable(close):
        maybe = close()
        if asyncio.iscoroutine(maybe):
            await maybe
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as e:
        import os

        msg = str(e)
        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "NEO4J_PASSWORD"):
            v = os.environ.get(k)
            if v:
                msg = msg.replace(v, "***")
        print("FAIL", msg[:400])
        raise SystemExit(1)
