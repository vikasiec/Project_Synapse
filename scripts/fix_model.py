"""Fix model id and test one Gemini call — no secrets printed."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from synapse.env_load import load_dotenv
from synapse.llm_gemini import call_gemini_generate


def main() -> int:
    env_path = ROOT / ".env"
    lines = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("GEMINI_MODEL="):
            lines.append("GEMINI_MODEL=gemini-3.1-flash-lite")
        else:
            lines.append(line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # clear cached env then reload
    os.environ["GEMINI_MODEL"] = "gemini-3.1-flash-lite"
    load_dotenv()
    os.environ["GEMINI_MODEL"] = "gemini-3.1-flash-lite"

    prompt = 'Return only this JSON: {"facts":[]}'
    try:
        text = call_gemini_generate(prompt, model="gemini-3.1-flash-lite")
        print("GEMINI_CALL_OK", "chars", len(text))
        print("preview", text[:100].replace("\n", " "))
        return 0
    except Exception as e:
        msg = str(e)
        for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            v = os.environ.get(k)
            if v:
                msg = msg.replace(v, "***")
        print("GEMINI_CALL_FAIL", msg[:250])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
