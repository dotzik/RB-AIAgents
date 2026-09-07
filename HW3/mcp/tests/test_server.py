"""Testy MCP obalu. Nástroje samotné testuje HW1."""
from __future__ import annotations

import json

from mcp import Client
from timeagent import tools
from timeagent_mcp.server import create_server


def _payload(result) -> dict:
    return json.loads(result.content[0].text)


async def test_seznam_nastroju_je_shodny_s_hw1(demo_db):
    """Schémata se přebírají z TOOL_SCHEMAS, nepíšou se znovu."""
    async with Client(create_server()) as client:
        result = await client.list_tools()

    ocekavane = {s["function"]["name"]: s["function"] for s in tools.TOOL_SCHEMAS}
    assert {t.name for t in result.tools} == set(ocekavane)
    for tool in result.tools:
        assert tool.description == ocekavane[tool.name]["description"]
        assert tool.input_schema == ocekavane[tool.name]["parameters"]


async def test_enum_u_dimension_projde_do_schematu(demo_db):
    """Enum je to, co by odvození schématu ze signatury zahodilo."""
    async with Client(create_server()) as client:
        result = await client.list_tools()

    summarize = next(t for t in result.tools if t.name == "summarize_by")
    enum = summarize.input_schema["properties"]["dimension"]["enum"]
    assert enum == ["project", "client", "day", "week", "month", "tag"]


async def test_chyba_prijde_jako_data_a_ne_jako_selhani(demo_db):
    async with Client(create_server()) as client:
        result = await client.call_tool(
            "compute_invoice", {"project": "Neexistující", "month": "2026-08"}
        )

    assert not result.is_error
    assert "error" in _payload(result)
    assert "Dostupné" in _payload(result)["error"]


async def test_neznamy_nastroj_take_jako_data(demo_db):
    async with Client(create_server()) as client:
        result = await client.call_tool("neexistujici_nastroj", {})

    assert not result.is_error
    assert "Neznámý nástroj" in _payload(result)["error"]


async def test_note_prezije_cestu_protokolem(demo_db):
    """Období mimo data musí přijít s větou o rozsahu dat."""
    async with Client(create_server()) as client:
        result = await client.call_tool("capacity_check", {"month": "2026-11"})

    payload = _payload(result)
    assert payload["total_hours"] == 0
    assert "note" in payload
    assert "Neodhaduj chybějící hodnoty" in payload["note"]


async def test_coerce_arguments_plati_i_pres_mcp(demo_db):
    """Řetězec "160" musí projít narovnáním v HW1, ne spadnout na typu."""
    async with Client(create_server()) as client:
        result = await client.call_tool(
            "capacity_check", {"month": "2026-08", "target_hours": "160"}
        )

    payload = _payload(result)
    assert payload["target_hours"] == 160.0
    assert "error" not in payload


async def test_structured_content_nese_tyz_slovnik(demo_db):
    async with Client(create_server()) as client:
        result = await client.call_tool("list_projects", {"active_only": True})

    assert result.structured_content == _payload(result)
    assert result.structured_content["count"] > 0
