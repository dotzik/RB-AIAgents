"""Generátor LangFlow flow s nástroji z MCP serveru.

Spouští se uvnitř kontejneru s LangFlow, protože používá jeho builder
(`lfx.graph.flow_builder`); ruční skládání JSONu by znamenalo hádat tvar hran
a handle identifikátorů.

    docker compose exec -T langflow python - < HW3/scripts/build_langflow_flow.py \
        > HW3/flows/langflow/vykazy-agent-mcp.json

Jedna komponenta MCPTools místo pěti generovaných Python komponent z HW2.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import urllib.request
from datetime import date

sys.path.insert(0, "/app")

from lfx.graph.flow_builder.component import add_component, configure_component
from lfx.graph.flow_builder.connect import add_connection
from lfx.mcp.flow_builder_tools._state import _load_registry_user_aware

MCP_IN_NETWORK = os.environ.get("MCP_IN_NETWORK", "http://mcp:8000/mcp")
MCP_SERVER_NAME = os.environ.get("MCP_SERVER_NAME", "timeagent")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:32b")
LANGFLOW_LOCAL = "http://localhost:7860"

# Interní adresa do repozitáře nepatří; skutečnou hodnotu dosadí
# `scripts/import_langflow_flow.py` z `.env` až při nahrávání. Stejně jako v HW2.
OLLAMA_PLACEHOLDER = "http://OLLAMA-HOST:11434"

GZIP_MAGIC = bytes([0x1F, 0x8B])

_WEEKDAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]

# Kopie promptu z HW1 — uvnitř kontejneru na balíček nedosáhneme.
# Rozejití hlídá `scripts/export_system_prompt.py --check`.
# Poslední řádek je navíc: LangFlow renderuje markdown a model jinak dělá tabulky.
SYSTEM_PROMPT = """\
Jsi asistent pro analýzu výkazů odpracovaného času. Odpovídáš česky, stručně a věcně.

Pravidla:
- Čísla nikdy neodhaduj ani nepočítej zpaměti — vždy je zjisti nástrojem.
- Když neznáš přesný název projektu, nejdřív si vypiš projekty nástrojem list_projects.
- Data zadávej v ISO formátu (YYYY-MM-DD), měsíce jako YYYY-MM.
- Složitější dotaz rozlož na víc volání nástrojů za sebou (např. porovnání dvou období
  = dvě volání) a teprve pak odpověz.
- Nepovinný parametr prostě vynech — neposílej "null" ani prázdný řetězec.
- Nevolej dvakrát tentýž nástroj se stejnými argumenty; výsledek už máš výš.
- Když nástroj vrátí pole "error", oprav argumenty a zkus to znovu.
- Chybovou hlášku z nástroje nikdy nepiš do odpovědi jako výsledek.
- Uveď jen čísla, která ti v této odpovědi vrátil nástroj. Nikdy nepokračuj
  v trendu, neodhaduj podle jiných měsíců a nepřebírej čísla z dřívější
  konverzace — ta mohou být chybná.
- Když nástroj vrátí nulu, prázdný seznam nebo pole "note", řekni rovnou, že
  za dané období nejsou záznamy, a uveď rozsah dostupných dat z "note".
- V odpovědi uveď konkrétní čísla, u peněz i měnu.

Dnešní datum je {today} ({weekday}). Aktuální měsíc je {month}.

Odpovídej prostým textem bez markdownu.\
"""


def system_prompt() -> str:
    d = date.today()
    return SYSTEM_PROMPT.format(
        today=d.isoformat(), weekday=_WEEKDAYS[d.weekday()], month=d.strftime("%Y-%m")
    )


def _get_json(url: str, token: str | None = None, timeout: int = 60) -> dict:
    headers = {"Accept-Encoding": "identity"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        raw = r.read()
        # LangFlow vrací katalog gzipovaný i při `Accept-Encoding: identity`.
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == GZIP_MAGIC:
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _post_json(url: str, token: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if raw[:2] == GZIP_MAGIC:
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8")) if raw else {}


def langflow_token() -> str:
    return _get_json(f"{LANGFLOW_LOCAL}/api/v1/auto_login")["access_token"]


def full_registry(token: str) -> dict:
    """Registry builderu doplněná o komponenty z bundlů (Ollama je bundle)."""
    registry = dict(_load_registry_user_aware())
    catalogue = _get_json(f"{LANGFLOW_LOCAL}/api/v1/all", token)
    for category, components in catalogue.items():
        if category == "component_display_names":
            continue
        for name, spec in components.items():
            registry.setdefault(name, spec)
    return registry


def ensure_mcp_server(token: str) -> None:
    """LangFlow drží MCP servery mimo flow, komponenta se na ně odkazuje jménem.
    Bez registrace se flow po importu otevře s prázdným rozbalovátkem."""
    existing = {s["name"] for s in _get_json(f"{LANGFLOW_LOCAL}/api/v2/mcp/servers", token)}
    if MCP_SERVER_NAME not in existing:
        _post_json(
            f"{LANGFLOW_LOCAL}/api/v2/mcp/servers/{MCP_SERVER_NAME}",
            token,
            {"url": MCP_IN_NETWORK},
        )


def build() -> dict:
    token = langflow_token()
    ensure_mcp_server(token)
    registry = full_registry(token)
    flow: dict = {"data": {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}}

    chat_in = add_component(flow, "ChatInput", registry)["id"]
    agent = add_component(flow, "Agent", registry)["id"]
    chat_out = add_component(flow, "ChatOutput", registry)["id"]
    ollama = add_component(flow, "ext:ollama:ChatOllamaComponent@official", registry)["id"]
    mcp = add_component(flow, "MCPTools", registry)["id"]

    configure_component(flow, agent, {
        "system_prompt": system_prompt(),
        # Datum má model v promptu; kalkulačka ho svádí počítat zpaměti.
        "add_current_date_tool": False,
        "add_calculator_tool": False,
        "max_iterations": 8,
    })
    configure_component(flow, ollama, {
        "base_url": OLLAMA_PLACEHOLDER,
        "model_name": MODEL,
        "temperature": 0,
        # S výchozím oknem se konverzace tiše ořízne a agent zapomene výsledky.
        "num_ctx": 32768,
        "tool_model_enabled": True,
    })
    configure_component(flow, mcp, {
        # `config` si LangFlow doplní z registrace — adresa je na jednom místě.
        "mcp_server": {"name": MCP_SERVER_NAME},
    })

    # `tool_mode` není parametr komponenty, ale příznak uzlu; plátno ho nastaví
    # při zapojení do `tools`, builder ne. Bez něj komponenta vrátí jeden
    # výsledek místo sady nástrojů.
    mcp_node = next(n for n in flow["data"]["nodes"] if n["id"] == mcp)
    mcp_node["data"]["node"]["tool_mode"] = True

    add_connection(flow, chat_in, "message", agent, "input_value")
    add_connection(flow, ollama, "model_output", agent, "model")
    add_connection(flow, agent, "response", chat_out, "input_value")
    add_connection(flow, mcp, "component_as_tool", agent, "tools")

    # Dokud uzel není v „connection mode", hrana s modelem sice v datech je,
    # ale UI i běh ji ignorují. Plátno to nastaví samo, builder ne.
    agent_node = next(n for n in flow["data"]["nodes"] if n["id"] == agent)
    agent_node["data"]["_connectionMode"] = True

    flow["name"] = "Výkazy — agent přes MCP (HW3)"
    flow["description"] = "Agent nad výkazy; nástroje z HW1 přes MCP server."
    return flow


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
