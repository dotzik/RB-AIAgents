"""ReAct agent nad MCP serverem, na LangGraph.

Graf staví `create_react_agent`; nástroje si `MultiServerMCPClient` vytáhne
z `tools/list`. Systémový prompt se importuje z HW1, aby ho měli všichni
tři klienti totožný.

    uv run lgagent ask "Kolik hodin jsem odpracoval v srpnu 2026?"
    uv run lgagent ask "…" --json          # strojový výstup pro měření
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from timeagent.agent import build_system_prompt

# `.env` u compose souboru HW3.
load_dotenv(Path(__file__).resolve().parents[4] / ".env")

DEFAULT_MCP_URL = "http://127.0.0.1:8010/mcp"
DEFAULT_MODEL = "qwen2.5:32b"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"

# Výsledky nástrojů se posílají v každém kroku znovu; s výchozím oknem se
# konverzace tiše ořízne a agent zapomene, co mu nástroj vrátil.
NUM_CTX = 32768


def _client(mcp_url: str) -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {"timeagent": {"url": mcp_url, "transport": "streamable_http"}}
    )


def _tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    """Volání nástrojů pro měření a ladění."""
    return [
        {"name": call["name"], "arguments": call["args"]}
        for msg in messages
        if isinstance(msg, AIMessage)
        for call in (msg.tool_calls or [])
    ]


async def _ask(question: str, mcp_url: str, model_name: str, ollama_base: str) -> dict[str, Any]:
    tools = await _client(mcp_url).get_tools()
    model = ChatOllama(
        model=model_name, base_url=ollama_base, temperature=0, num_ctx=NUM_CTX
    )
    agent = create_react_agent(model, tools)

    started = time.perf_counter()
    result = await agent.ainvoke(
        {
            "messages": [
                SystemMessage(build_system_prompt()),
                HumanMessage(question),
            ]
        }
    )
    elapsed = time.perf_counter() - started

    calls = _tool_calls(result["messages"])
    return {
        "client": "python/langgraph",
        "model": model_name,
        "question": question,
        "answer": result["messages"][-1].content,
        "tool_calls": calls,
        "tool_call_count": len(calls),
        "seconds": round(elapsed, 2),
    }


def _hint(exc: Exception, mcp_url: str, ollama_base: str) -> str:
    """Jedna věta s nápovědou místo stack trace. Vzor: HW1/src/timeagent/llm.py."""
    text = f"{type(exc).__name__}: {exc}"
    if "connect" in text.lower() or "refused" in text.lower():
        return (
            f"{text}\nNedosáhl jsem na MCP server ({mcp_url}) nebo na model "
            f"({ollama_base}). MCP zvedne `cd HW3 && docker compose up -d`; "
            "adresu modelu drží OLLAMA_BASE_URL v HW3/.env."
        )
    return text


def _setup_stdout() -> None:
    """Konzole na Windows jede v cp1252 a české odpovědi by na ní spadly."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    parser = argparse.ArgumentParser(
        prog="lgagent", description="ReAct agent nad MCP serverem z HW3 (LangGraph)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="Zeptej se agenta")
    ask.add_argument("question", help="Otázka v češtině")
    ask.add_argument("--json", action="store_true", help="Strojový výstup")
    ask.add_argument("--mcp-url", default=os.environ.get("MCP_URL", DEFAULT_MCP_URL))
    ask.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL))
    ask.add_argument(
        "--ollama-url", default=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA)
    )

    sub.add_parser("tools", help="Vypiš nástroje, které server nabízí")
    args = parser.parse_args(argv)

    if args.command == "tools":
        mcp_url = os.environ.get("MCP_URL", DEFAULT_MCP_URL)

        async def _list() -> None:
            for tool in await _client(mcp_url).get_tools():
                print(f"{tool.name}\n    {tool.description.splitlines()[0]}")

        asyncio.run(_list())
        return 0

    try:
        result = asyncio.run(
            _ask(args.question, args.mcp_url, args.model, args.ollama_url)
        )
    except Exception as exc:  # noqa: BLE001 — CLI má selhat srozumitelně
        message = _hint(exc, args.mcp_url, args.ollama_url)
        if args.json:
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            print(f"Chyba: {message}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for call in result["tool_calls"]:
            print(f"  → {call['name']}({call['arguments']})", file=sys.stderr)
        print(result["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
