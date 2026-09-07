"""Vygeneruje LangFlow flow — spustí builder uvnitř kontejneru.

    python scripts/gen_langflow_flow.py

Existuje kvůli systémovému promptu. Builder běží uvnitř kontejneru s LangFlow
(potřebuje jeho `lfx`), kde na balíček z HW1 nedosáhne. Dřív tam proto byla
kopie promptu, která se rozešla s originálem. Tenhle wrapper prompt přečte
z HW1 na hostiteli a předá ho dovnitř proměnnou prostředí.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "HW1" / "src"))

from timeagent.agent import build_system_prompt

BUILDER = Path(__file__).resolve().parent / "build_langflow_flow.py"
OUT = Path(__file__).resolve().parents[1] / "flows" / "langflow" / "vykazy-agent.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--service", default="langflow")
    ap.add_argument("--project", default="rb-aiagents", help="compose projekt s LangFlow")
    args = ap.parse_args()

    env = {
        "SYSTEM_PROMPT": build_system_prompt(),
        "TOOLS_BASE_URL": os.environ.get("TOOLS_BASE_URL", "http://api:8000"),
        "OLLAMA_MODEL": os.environ.get("OLLAMA_MODEL", "qwen2.5:32b"),
    }
    cmd = [
        "docker", "compose", "-p", args.project, "exec", "-T",
        *[arg for k, v in env.items() for arg in ("-e", f"{k}={v}")],
        args.service, "python", "-",
    ]

    proc = subprocess.run(
        cmd, stdin=BUILDER.open("rb"), capture_output=True, check=False
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        sys.exit(
            f"Generátor selhal (exit {proc.returncode}). "
            "Běží HW2 stack? `cd HW2 && docker compose up -d`"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(proc.stdout)
    print(f"Zapsáno: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
