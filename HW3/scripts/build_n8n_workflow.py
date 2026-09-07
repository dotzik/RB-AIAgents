"""Generátor n8n workflow s nástroji z MCP serveru.

Jeden uzel mcpClientTool místo pěti toolHttpRequest z HW2 — MCP posílá
`inputSchema`, takže se parametry nemusí dopisovat do textu popisu.

    python scripts/build_n8n_workflow.py --credential-id <id_ollama_credential>

Id credentialu je v n8n vidět v URL po jeho otevření; v JSONu žádné tajemství není.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "HW1" / "src"))

from timeagent.agent import build_system_prompt

OUT = ROOT / "HW3" / "flows" / "n8n" / "vykazy-agent-mcp.json"

# Uvnitř sítě projektu se služby vidí pod jmény z compose.
MCP_IN_NETWORK = os.environ.get("MCP_IN_NETWORK", "http://mcp:8000/mcp")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:32b")

# Datum se dosazuje při generování — bez něj model nepřeloží „minulý měsíc".
SYSTEM_MESSAGE = build_system_prompt(date.today()) + (
    "\nOdpovídej vždy česky."
)


def workflow(credential_id: str, credential_name: str) -> dict:
    nodes = [
        {
            "id": "chat-trigger",
            "name": "Chat",
            "type": "@n8n/n8n-nodes-langchain.chatTrigger",
            "typeVersion": 1.4,
            "position": [-400, 0],
            "webhookId": "vykazy-agent-mcp-chat",
            "parameters": {
                "public": True,
                "mode": "hostedChat",
                "authentication": "none",
                "initialMessages": (
                    "Ptej se na výkazy — hodiny, projekty, fakturační podklady. "
                    "Nástroje jdou přes MCP."
                ),
                "options": {},
            },
        },
        {
            "id": "agent",
            "name": "Agent nad výkazy (MCP)",
            "type": "@n8n/n8n-nodes-langchain.agent",
            "typeVersion": 2.2,
            "position": [-40, 0],
            "parameters": {
                "promptType": "define",
                "text": "={{ $json.chatInput }}",
                "options": {"systemMessage": SYSTEM_MESSAGE},
            },
        },
        {
            "id": "ollama",
            "name": "Ollama — Spark",
            "type": "@n8n/n8n-nodes-langchain.lmChatOllama",
            "typeVersion": 1,
            "position": [-160, 240],
            "parameters": {
                "model": MODEL,
                "options": {"numCtx": 32768, "temperature": 0},
            },
            "credentials": {
                "ollamaApi": {"id": credential_id, "name": credential_name}
            },
        },
        {
            "id": "memory",
            "name": "Paměť konverzace",
            "type": "@n8n/n8n-nodes-langchain.memoryBufferWindow",
            "typeVersion": 1.4,
            "position": [20, 240],
            "parameters": {},
        },
        {
            "id": "mcp",
            "name": "Nástroje z MCP",
            "type": "@n8n/n8n-nodes-langchain.mcpClientTool",
            "typeVersion": 1.3,
            "position": [200, 240],
            "parameters": {
                "endpointUrl": MCP_IN_NETWORK,
                # Natvrdo v JSONu: rozbalovátko v UI umí `serverTransport`
                # neuložit a uzel pak jede po SSE, které server nenabízí.
                "serverTransport": "httpStreamable",
                "authentication": "none",
                # `all` — nový nástroj v HW1 se objeví bez editace flow.
                "include": "all",
                "options": {},
            },
        },
    ]

    connections = {
        "Chat": {"main": [[{"node": "Agent nad výkazy (MCP)", "type": "main", "index": 0}]]},
        "Ollama — Spark": {
            "ai_languageModel": [
                [{"node": "Agent nad výkazy (MCP)", "type": "ai_languageModel", "index": 0}]
            ]
        },
        "Paměť konverzace": {
            "ai_memory": [
                [{"node": "Agent nad výkazy (MCP)", "type": "ai_memory", "index": 0}]
            ]
        },
        "Nástroje z MCP": {
            "ai_tool": [[{"node": "Agent nad výkazy (MCP)", "type": "ai_tool", "index": 0}]]
        },
    }

    return {
        "name": "Výkazy — agent přes MCP (HW3)",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--credential-id",
        required=True,
        help="ID credentialu na Ollamu v n8n (z URL po jeho otevření)",
    )
    ap.add_argument("--credential-name", default="Ollama — DGX Spark")
    args = ap.parse_args()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(workflow(args.credential_id, args.credential_name),
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Zapsáno: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
