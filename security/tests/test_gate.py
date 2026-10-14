"""Test mitigace M1: autorizační gate v MCP serveru (kap. 7, případy V1–V12).

Kontroluje se obsah odpovědi proti databázi a auditní log, ne text hlášky.
Zakázaný „side effect“ read-only nástrojů je předání cizích dat.
"""
from __future__ import annotations

import json
import sqlite3

import httpx2
from timeagent import tools

from conftest import CLIENT_A, CLIENT_B, DEFAULT_CLIENTS, audit_records, call, write_policy

# Cokoli z toho v odpovědi klientovi A = únik cizích dat.
FOREIGN = ["NWND", "GLBX", "INIT", "INTR", "Northwind", "Globex", "Initech", "1350"]


def _leaks(payload: dict) -> list[str]:
    text = json.dumps(payload, ensure_ascii=False)
    return [marker for marker in FOREIGN if marker in text]


def _billable_hours(db_path, project: str, month: str) -> float:
    """Nezávislý dotaz do DB, ne přes nástroje."""
    with sqlite3.connect(db_path) as conn:
        (hours,) = conn.execute(
            "SELECT COALESCE(SUM(hours), 0) FROM time_entries "
            "WHERE project_id = ? AND billable = 1 AND substr(date, 1, 7) = ?",
            (project, month),
        ).fetchone()
    return round(hours, 2)


def _last(env) -> dict:
    return audit_records(env["audit"])[-1]


async def test_v0_bez_gate_cizi_data_uniknou(env):
    """Výchozí stav: původní server z HW3 vydá data Northwindu komukoli.

    Bez tohoto testu by zelené V2–V7 mohly znamenat jen to, že data chybí.
    """
    from mcp import Client
    from timeagent_mcp.server import create_server as create_unprotected

    async with Client(create_unprotected()) as client:
        result = await client.call_tool("compute_invoice", {"project": "Northwind", "month": "2026-08"})
    payload = json.loads(result.content[0].text)

    assert payload["client"] == "Northwind Trading"
    assert payload["billable_hours"] == _billable_hours(env["db"], "NWND", "2026-08") > 0


async def test_v1_klient_dostane_fakturu_za_vlastni_projekt(env, server_url):
    payload = await call(server_url, "compute_invoice", {"project": "ACME", "month": "2026-08"},
                         service="n8n-telegram", chat_id=CLIENT_A)

    assert "error" not in payload
    assert payload["client"] == "Acme Corp"
    assert payload["billable_hours"] == _billable_hours(env["db"], "ACME", "2026-08")
    assert payload["billable_hours"] > 0
    assert _last(env)["decision"] == "allow"


async def test_v2_cizi_projekt_je_zamitnut_bez_cizich_dat(env, server_url):
    for needle in ("NWND", "Northwind"):
        payload = await call(server_url, "compute_invoice", {"project": needle, "month": "2026-08"},
                             service="n8n-telegram", chat_id=CLIENT_A)

        assert payload.get("denied") == "project_not_allowed"
        assert "billable_hours" not in payload
        assert _leaks(payload) == []
        assert _last(env)["decision"] == "deny"
        assert _last(env)["arguments"]["project"] == needle


async def test_v3_dotaz_bez_projektu_nesecte_vsechny_klienty(env, server_url):
    payload = await call(server_url, "query_time_entries",
                         {"date_from": "2026-05-01", "date_to": "2026-08-31"},
                         service="n8n-telegram", chat_id=CLIENT_A)

    assert payload.get("denied") == "project_required"
    assert "total_hours" not in payload
    assert _leaks(payload) == []


async def test_v4_souhrn_pres_klienty_a_kapacita_jsou_zamitnuty(env, server_url):
    by_client = await call(server_url, "summarize_by",
                           {"dimension": "client", "date_from": "2026-05-01", "date_to": "2026-08-31",
                            "project": "ACME"},
                           service="n8n-telegram", chat_id=CLIENT_A)
    capacity = await call(server_url, "capacity_check", {"month": "2026-08"},
                          service="n8n-telegram", chat_id=CLIENT_A)

    assert by_client.get("denied") == "dimension_not_allowed"
    assert capacity.get("denied") == "tool_not_allowed"
    assert _leaks(by_client) == [] and _leaks(capacity) == []


async def test_v5_neexistujici_projekt_nevypise_cizi_projekty(env, server_url):
    payload = await call(server_url, "compute_invoice", {"project": "XYZ", "month": "2026-08"},
                         service="n8n-telegram", chat_id=CLIENT_A)

    assert payload.get("denied") == "project_not_allowed"
    assert _leaks(payload) == []
    assert "ACME" in payload["error"]  # vlastní projekty nabídne


async def test_v6_identita_v_argumentu_se_ignoruje(env, server_url):
    own = await call(server_url, "compute_invoice",
                     {"project": "ACME", "month": "2026-08", "chat_id": CLIENT_B},
                     service="n8n-telegram", chat_id=CLIENT_A)
    foreign = await call(server_url, "compute_invoice",
                         {"project": "NWND", "month": "2026-08", "chat_id": CLIENT_B},
                         service="n8n-telegram", chat_id=CLIENT_A)

    assert own["client"] == "Acme Corp"
    assert foreign.get("denied") == "project_not_allowed"
    assert _leaks(foreign) == []


async def test_v7_neznamy_nebo_chybejici_chat_id(env, server_url):
    unknown = await call(server_url, "compute_invoice", {"project": "ACME", "month": "2026-08"},
                         service="n8n-telegram", chat_id="9999")
    missing = await call(server_url, "compute_invoice", {"project": "ACME", "month": "2026-08"},
                         service="n8n-telegram")

    assert unknown.get("denied") == "unknown_chat_id"
    assert missing.get("denied") == "missing_chat_id"
    assert "billable_hours" not in unknown and "billable_hours" not in missing


async def test_v8_bez_tokenu_a_se_spatnym_tokenem_401(env, server_url):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "compute_invoice", "arguments": {"project": "NWND", "month": "2026-08"}}}
    async with httpx2.AsyncClient(timeout=10) as http:
        no_token = await http.post(server_url, json=body)
        bad_token = await http.post(server_url, json=body, headers={"Authorization": "Bearer spatny"})

    assert no_token.status_code == 401
    assert bad_token.status_code == 401
    records = audit_records(env["audit"])
    assert [r["reason"] for r in records] == ["unauthenticated", "unauthenticated"]
    assert all(r["tool"] is None for r in records)  # k nástroji se nedošlo


async def test_v9_bez_politiky_vse_zamitnuto(env, server_url, monkeypatch):
    monkeypatch.setenv("TIMEAGENT_POLICY", str(env["policy"].with_name("neexistuje.toml")))
    async with httpx2.AsyncClient(timeout=10) as http:
        response = await http.post(
            server_url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer cokoli", "X-Timeagent-Chat-Id": CLIENT_A},
        )

    assert response.status_code == 503
    assert "billable_hours" not in response.text


async def test_v10_vlastnik_vidi_vse_jako_bez_gate(env, server_url):
    args = {"project": "NWND", "month": "2026-08"}
    payload = await call(server_url, "compute_invoice", args, service="owner-cli")

    assert payload == tools.call_tool("compute_invoice", args)
    assert payload["client"] == "Northwind Trading"


async def test_v11_seznam_projektu_jen_vlastni(env, server_url):
    payload = await call(server_url, "list_projects", {}, service="n8n-telegram", chat_id=CLIENT_A)

    assert {p["id"] for p in payload["projects"]} == {"ACME", "ACM2"}
    assert payload["count"] == 2
    assert _leaks(payload) == []


async def test_v12_revokace_plati_hned(env, server_url):
    before = await call(server_url, "compute_invoice", {"project": "ACME", "month": "2026-08"},
                        service="n8n-telegram", chat_id=CLIENT_A)
    write_policy(env["policy"], {k: v for k, v in DEFAULT_CLIENTS.items() if k != CLIENT_A})
    after = await call(server_url, "compute_invoice", {"project": "ACME", "month": "2026-08"},
                       service="n8n-telegram", chat_id=CLIENT_A)

    assert before["client"] == "Acme Corp"
    assert after.get("denied") == "unknown_chat_id"
    assert "billable_hours" not in after
