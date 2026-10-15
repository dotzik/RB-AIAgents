"""MCP server timeagenta s autorizační gate.

Stejné nástroje a schémata jako `timeagent_mcp.server` (HW3), navíc:
- ASGI vrstva před `/mcp`: bez platného tokenu 401, bez politiky 503;
- gate v `on_call_tool`: identita z hlaviček HTTP požadavku, ne z argumentů.

    TIMEAGENT_POLICY=access.toml uv run uvicorn timeagent_gate.server:app --port 8012
"""
from __future__ import annotations

import json
from typing import Any

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route
from timeagent import tools
from timeagent_mcp.server import DEFAULT_ALLOWED_HOSTS, TOOLS, health

from .gate import AuditError, audit, audit_path, authorize, filter_result, visible_tools
from .policy import Identity, PolicyError, load_policy, resolve_identity

SERVER_NAME = "timeagent"


def _result(payload: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))],
        structured_content=payload,
    )


def _identity(ctx: ServerRequestContext[Any]) -> Identity | None:
    """Identita z HTTP požadavku, který nese toto volání. Chyba = None."""
    request = ctx.request
    if request is None:  # mimo HTTP (stdio, in-process) žádná identita
        return None
    try:
        return resolve_identity(load_policy(), request.headers)
    except PolicyError:
        return None


async def on_list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    try:
        allowed = set(visible_tools(_identity(ctx), [t.name for t in TOOLS]))
    except Exception:  # noqa: BLE001 — chyba = žádné nástroje (fail closed)
        allowed = set()
    return types.ListToolsResult(tools=[t for t in TOOLS if t.name in allowed])


async def on_call_tool(
    ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
) -> types.CallToolResult:
    arguments = params.arguments or {}
    try:
        identity = _identity(ctx)
        decision = authorize(identity, params.name, arguments)
    except Exception:  # noqa: BLE001 — chyba v gate = zamítnutí (fail closed)
        try:
            audit(None, params.name, arguments, False, "gate_error")
        except AuditError:
            pass
        return _result({"error": "Přístup zamítnut.", "denied": "gate_error"})

    try:
        audit(identity, params.name, arguments, decision.allowed, decision.reason)
    except AuditError:  # bez záznamu se nic nevydá
        return _result({"error": "Služba není dostupná.", "denied": "audit_unavailable"})
    if not decision.allowed:
        return _result({"error": decision.message, "denied": decision.reason})

    result = tools.call_tool(params.name, decision.arguments)
    return _result(filter_result(identity, params.name, result))


def create_server() -> Server[Any]:
    return Server(
        SERVER_NAME,
        version="0.1.0",
        title="Výkazy odpracovaného času (s autorizací)",
        instructions=(
            "Nástroje nad databází výkazů odpracovaného času a fakturačních "
            "podkladů. Čísla ber vždy z nástrojů, nikdy je nedopočítávej."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


class AuthLayer:
    """Před `/mcp` pustí jen ověřenou službu. Gate pak rozhoduje o nástroji."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        unavailable = JSONResponse({"error": "Služba není dostupná."}, status_code=503)
        try:
            audit_path()
        except AuditError:  # bez auditu se neobsluhuje nikdo (fail closed)
            await unavailable(scope, receive, send)
            return
        try:
            identity = resolve_identity(load_policy(), headers)
        except PolicyError:
            try:
                audit(None, None, None, False, "policy_unavailable")
            except AuditError:
                pass
            await unavailable(scope, receive, send)
            return
        if identity is None:
            try:
                audit(None, None, None, False, "unauthenticated")
            except AuditError:
                pass
            await JSONResponse(
                {"error": "Chybí nebo neplatí token."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_app(extra_hosts: list[str] | None = None) -> Any:
    hosts = [*DEFAULT_ALLOWED_HOSTS, *(extra_hosts or [])]
    inner = create_server().streamable_http_app(
        custom_starlette_routes=[Route("/health", health, methods=["GET"])],
        transport_security=TransportSecuritySettings(
            allowed_hosts=hosts,
            allowed_origins=[f"http://{h}" for h in hosts],
        ),
    )
    return AuthLayer(inner)


app = build_app()
