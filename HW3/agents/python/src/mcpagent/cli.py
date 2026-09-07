"""Agent nad MCP serverem, na Pydantic AI.

Nástroje i jejich schémata přijdou ze serveru přes `MCPToolset`.
Systémový prompt se importuje z HW1, aby ho měl .NET klient totožný.

    uv run mcpagent ask "Kolik hodin jsem odpracoval v srpnu 2026?"
    uv run mcpagent ask "…" --json          # strojový výstup pro měření
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
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from timeagent.agent import build_system_prompt

# `.env` u compose souboru HW3.
load_dotenv(Path(__file__).resolve().parents[4] / ".env")

DEFAULT_MCP_URL = "http://127.0.0.1:8010/mcp"
DEFAULT_MODEL = "qwen2.5:32b"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"


def _build_agent(mcp_url: str, model_name: str, ollama_base: str) -> Agent:
    provider = OllamaProvider(base_url=f"{ollama_base.rstrip('/')}/v1")
    return Agent(
        OllamaModel(model_name, provider=provider),
        # `system_prompt`, ne `instructions` — pošle se jednou jako systémová zpráva.
        system_prompt=build_system_prompt(),
        toolsets=[MCPToolset(mcp_url)],
        retries=3,
    )


def _tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    """Volání nástrojů pro měření a ladění."""
    calls = []
    for msg in messages:
        if isinstance(msg, ModelResponse | ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    calls.append({"name": part.tool_name, "arguments": part.args})
    return calls


async def _ask(question: str, mcp_url: str, model_name: str, ollama_base: str) -> dict[str, Any]:
    agent = _build_agent(mcp_url, model_name, ollama_base)
    started = time.perf_counter()
    async with agent:
        result = await agent.run(question)
    elapsed = time.perf_counter() - started
    calls = _tool_calls(result.all_messages())
    return {
        "client": "python/pydantic-ai",
        "model": model_name,
        "question": question,
        "answer": result.output,
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
        prog="mcpagent", description="Agent nad MCP serverem z HW3 (Pydantic AI)"
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
            toolset = MCPToolset(mcp_url)
            async with toolset:
                for tool in await toolset.list_tools():
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
