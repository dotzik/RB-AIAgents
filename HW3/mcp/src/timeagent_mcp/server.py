"""MCP server nad nástroji z HW1. Obal bez doménové logiky."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from typing import Any

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from timeagent import db, tools

SERVER_NAME = "timeagent"

# Low-level Server, ne MCPServer/dekorátory: schéma se přebírá z TOOL_SCHEMAS
# doslova. Odvození ze signatur by zahodilo enum u `dimension` a popisy.
TOOLS: list[types.Tool] = [
    types.Tool(
        name=fn["name"],
        description=fn["description"],
        input_schema=fn["parameters"],
    )
    for fn in (schema["function"] for schema in tools.TOOL_SCHEMAS)
]


async def on_list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def on_call_tool(
    ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
) -> types.CallToolResult:
    """Výsledek `tools.call_tool` beze změny.

    `is_error` se nenastavuje ani pro `{"error": ...}` — model má hlášku dostat
    jako obsah a opravit argumenty. S `is_error=True` klient běh utne.
    Pole `note` projde tím, že se serializuje celý dict. Neopravovat.
    """
    result = tools.call_tool(params.name, params.arguments or {})
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False, indent=2)
            )
        ],
        structured_content=result,
    )


def create_server() -> Server[Any]:
    return Server(
        SERVER_NAME,
        version="0.1.0",
        title="Výkazy odpracovaného času",
        instructions=(
            "Nástroje nad databází výkazů odpracovaného času a fakturačních "
            "podkladů. Čísla ber vždy z nástrojů, nikdy je nedopočítávej."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def health(request: Request) -> JSONResponse:
    """Stejný tvar jako `/health` v HW2 — obojí hlídá jeden skript."""
    try:
        with closing(db.connect_ro()) as conn:
            projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            entries = conn.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0]
    except (FileNotFoundError, sqlite3.Error) as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "nedostupné",
                "database": str(db.default_db_path()),
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "Databázi vygeneruje `uv run timeagent seed` v HW1.",
            },
        )
    return JSONResponse(
        {
            "status": "ok",
            "database": str(db.default_db_path()),
            "projects": projects,
            "time_entries": entries,
            "tools": len(TOOLS),
        }
    )


# Ochrana proti DNS rebindingu je v SDK zapnutá; bez výčtu odmítne i legitimní
# požadavek. Z n8n a LangFlow chodí `Host: mcp:8000`, ne localhost.
DEFAULT_ALLOWED_HOSTS = [
    "mcp:8000",
    "hw3-mcp:8000",
    "localhost:8010",
    "127.0.0.1:8010",
    "[::1]:8010",
]


def _allowed_hosts() -> list[str]:
    raw = os.environ.get("MCP_ALLOWED_HOSTS", "")
    extra = [h.strip() for h in raw.split(",") if h.strip()]
    return [*DEFAULT_ALLOWED_HOSTS, *extra]


def build_app() -> Any:
    """ASGI aplikace: MCP na `/mcp`, health check na `/health`."""
    hosts = _allowed_hosts()
    return create_server().streamable_http_app(
        custom_starlette_routes=[Route("/health", health, methods=["GET"])],
        transport_security=TransportSecuritySettings(
            allowed_hosts=hosts,
            allowed_origins=[f"http://{h}" for h in hosts],
        ),
    )


app = build_app()
