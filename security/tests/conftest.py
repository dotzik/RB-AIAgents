"""Syntetické prostředí pro test gate: seed DB, politika, server na localhostu.

Server běží skutečně (uvicorn ve vlákně) a test na něj volá MCP klientem
přes HTTP. Gate se nemockuje.
"""
from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from datetime import date
from pathlib import Path

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from timeagent import db, seed

from timeagent_gate.policy import hash_token
from timeagent_gate.server import build_app

ANCHOR = date(2026, 8, 31)
TOKENS = {
    "n8n-telegram": secrets.token_urlsafe(32),
    "owner-cli": secrets.token_urlsafe(32),
}
CLIENT_A = "1001"  # Acme Corp
CLIENT_B = "2002"  # Northwind Trading


def write_policy(path: Path, clients: dict[str, str]) -> None:
    lines = [
        "[services.n8n-telegram]",
        f'token_sha256 = "{hash_token(TOKENS["n8n-telegram"])}"',
        'role = "client-proxy"',
        "",
        "[services.owner-cli]",
        f'token_sha256 = "{hash_token(TOKENS["owner-cli"])}"',
        'role = "owner"',
        "",
        "[clients]",
        *(f'"{chat}" = "{client}"' for chat, client in clients.items()),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


DEFAULT_CLIENTS = {CLIENT_A: "Acme Corp", CLIENT_B: "Northwind Trading"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """DB ze seedu + druhý projekt Acme, politika a auditní log v tmp."""
    db_path = tmp_path / "test.sqlite"
    conn = db.connect_rw(db_path)
    seed.seed_database(conn, anchor=ANCHOR, months=4, rng_seed=42)
    conn.execute(
        "INSERT INTO projects (id, name, client, hourly_rate, currency, active) "
        "VALUES ('ACM2', 'Acme — podpora provozu', 'Acme Corp', 1200.0, 'CZK', 1)"
    )
    conn.commit()
    conn.close()

    policy = tmp_path / "access.toml"
    write_policy(policy, DEFAULT_CLIENTS)
    audit_log = tmp_path / "audit.jsonl"

    monkeypatch.setenv("TIMEAGENT_DB", str(db_path))
    monkeypatch.setenv("TIMEAGENT_POLICY", str(policy))
    monkeypatch.setenv("TIMEAGENT_AUDIT_LOG", str(audit_log))
    return {"db": db_path, "policy": policy, "audit": audit_log}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url():
    port = _free_port()
    app = build_app([f"127.0.0.1:{port}"])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server nenastartoval")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def headers(service: str | None, chat_id: str | None = None, token: str | None = None) -> dict[str, str]:
    h: dict[str, str] = {}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    elif service is not None:
        h["Authorization"] = f"Bearer {TOKENS[service]}"
    if chat_id is not None:
        h["X-Timeagent-Chat-Id"] = chat_id
    return h


async def call(url: str, tool: str, arguments: dict, **hdr) -> dict:
    """Jedno volání nástroje skutečným MCP klientem přes HTTP."""
    async with httpx2.AsyncClient(headers=headers(**hdr), timeout=30) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            result = await client.call_tool(tool, arguments)
    return json.loads(result.content[0].text)


def audit_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
