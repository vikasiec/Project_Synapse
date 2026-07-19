"""One dual-path residual smoke with Gemini — secrets redacted."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from synapse.env_load import load_dotenv
    from synapse.dual_path import DualPathExtractor
    from synapse.ingestion import IngestionService
    from synapse.llm_gemini import gemini_configured, create_residual_extractor
    from synapse.store import SemanticStore

    load_dotenv()
    print("configured", gemini_configured())
    print("backend", create_residual_extractor().name)

    store = SemanticStore()
    dual = DualPathExtractor(store)
    ing = IngestionService(store)
    landed = ing.land(
        "GitHub-CI",
        "BUILD SUCCESSFUL: checkout-service deployed image tag v9.9.3 automatically.\n"
        "note: on-call suspects partial EU traffic still on canary; watch error budgets overnight.\n",
        ["domain:sre", "clearance:l2"],
    )
    out = dual.extract(landed.episode, landed.raw)
    print(
        json.dumps(
            {
                "entity": out.entity_name,
                "path_b_backend": out.path_b_backend,
                "path_b_used": out.path_b_used,
                "det_facts": len(out.deterministic_facts),
                "residual_facts": [
                    {"predicate": f.predicate, "object": str(f.object)[:120]}
                    for f in out.residual_facts
                ],
            },
            indent=2,
        )
    )
    return 0 if out.entity_name else 1


if __name__ == "__main__":
    raise SystemExit(main())
