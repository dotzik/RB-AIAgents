"""Nahraje `flows/langflow/vykazy-agent-mcp.json` do běžícího LangFlow.

    python scripts/import_langflow_flow.py
    python scripts/import_langflow_flow.py --ask "Kolik hodin jsem odpracoval v srpnu 2026?"

Aktualizuje na místě; `POST /api/v1/flows/` pokaždé vytvoří kopii
a přejmenuje ji na „… (1)".

Obsluha API (gzip i při `Accept-Encoding: identity`, `x-api-key` místo Beareru
u `/api/v1/run`) se importuje z HW2. Navíc proti HW2 je registrace MCP serveru.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "HW2" / "scripts"))

from import_langflow_flow import (
    LANGFLOW,
    OLLAMA_PLACEHOLDER,
    _request,
    api_key,
    token,
)

HW3 = ROOT / "HW3"
FLOW_FILE = HW3 / "flows" / "langflow" / "vykazy-agent-mcp.json"
ENV_FILE = HW3 / ".env"
MCP_SERVER_NAME = "timeagent"
MCP_IN_NETWORK = "http://mcp:8000/mcp"


def env_value(key: str) -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    sys.exit(f"V {ENV_FILE} chybí {key}.")


def ensure_mcp_server(tok: str) -> None:
    existing = {s["name"] for s in _request("GET", "/api/v2/mcp/servers", tok)}
    if MCP_SERVER_NAME in existing:
        return
    _request("POST", f"/api/v2/mcp/servers/{MCP_SERVER_NAME}", tok, {"url": MCP_IN_NETWORK})
    print(f"Zaregistrován MCP server {MCP_SERVER_NAME} → {MCP_IN_NETWORK}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, default=FLOW_FILE)
    ap.add_argument("--ask", help="po nahrání položit flow tuhle otázku")
    args = ap.parse_args()

    if not args.file.exists():
        sys.exit(
            f"Chybí {args.file}. Vygeneruj ho z kořene repozitáře:\n"
            "  docker compose -p rb-aiagents exec -T langflow python - "
            "< HW3/scripts/build_langflow_flow.py > HW3/flows/langflow/vykazy-agent-mcp.json"
        )

    raw = args.file.read_text(encoding="utf-8")
    if OLLAMA_PLACEHOLDER in raw:
        raw = raw.replace(OLLAMA_PLACEHOLDER, env_value("OLLAMA_BASE_URL"))
        print(f"Adresa Ollamy dosazena z {ENV_FILE}")
    flow = json.loads(raw)
    name = flow["name"]

    try:
        tok = token()
    except urllib.error.URLError as exc:
        sys.exit(
            f"LangFlow na {LANGFLOW} neodpovídá ({exc}). "
            "Spusť HW2 stack: docker compose -p rb-aiagents up -d"
        )

    ensure_mcp_server(tok)

    existing = [
        f for f in _request("GET", "/api/v1/flows/?get_all=true", tok) if f.get("name") == name
    ]
    if existing:
        flow_id = existing[0]["id"]
        _request("PATCH", f"/api/v1/flows/{flow_id}", tok, flow)
        print(f"Aktualizován flow {flow_id} ({name})")
        for extra in existing[1:]:
            _request("DELETE", f"/api/v1/flows/{extra['id']}", tok)
            print(f"  smazán duplikát {extra['id']}")
    else:
        flow_id = _request("POST", "/api/v1/flows/", tok, flow)["id"]
        print(f"Založen flow {flow_id} ({name})")

    print(f"  UI: {LANGFLOW}/flow/{flow_id}")

    if args.ask:
        answer = _request(
            "POST",
            f"/api/v1/run/{flow_id}",
            api_key(tok),
            {
                "input_value": args.ask,
                "input_type": "chat",
                "output_type": "chat",
                "session_id": "hw3-import-smoke",
            },
            as_api_key=True,
        )
        text = answer["outputs"][0]["outputs"][0]["results"]["message"]["text"]
        print(f"\n> {args.ask}\n{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
