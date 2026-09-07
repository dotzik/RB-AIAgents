"""Generátor LangFlow flow pro agenta nad výkazy — stejná doména jako v n8n.

Spouští se **uvnitř kontejneru s LangFlow**, protože používá jeho vlastní builder
(`lfx.graph.flow_builder`). Skládat flow JSON ručně by znamenalo hádat tvar hran
a handle identifikátorů; tady se použije totéž, co dělá plátno.

    docker compose exec -T langflow python - < scripts/build_langflow_flow.py > flows/langflow/vykazy-agent.json

Každý nástroj je **vlastní Python komponenta**, ne komponenta API Request.
Ta totiž v tool mode vystaví modelu jediný nástroj `make_api_request` s volným
parametrem `url_input` — pět takových komponent nedá pět nástrojů, ale pětkrát
totéž, a model si adresu vymyslí. U vlastní komponenty je **jméno nástroje jméno
metody** a typované vstupy s `tool_mode=True` jsou jeho parametry.
Podrobně v docs/srovnani.md.

Popisy i schémata se berou z `GET /tools`, tedy z téhož zdroje jako všude jinde.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import urllib.request
from datetime import date

sys.path.insert(0, "/app")

from lfx.graph.flow_builder.component import (
    add_component,
    configure_component,
)
from lfx.graph.flow_builder.connect import add_connection
from lfx.mcp.flow_builder_tools._state import _load_registry_user_aware

API_IN_NETWORK = os.environ.get("TOOLS_BASE_URL", "http://api:8000")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
# Do odevzdávaného souboru se místo skutečné adresy zapíše zástupný text —
# interní adresa do repozitáře nepatří. Skutečnou hodnotu dosadí
# `scripts/import_langflow_flow.py` z `.env` až při nahrávání do LangFlow.
# (n8n tenhle problém nemá: tam je adresa v credentialu, mimo export.)
OLLAMA_PLACEHOLDER = "http://OLLAMA-HOST:11434"
LANGFLOW_LOCAL = "http://localhost:7860"

GZIP_MAGIC = bytes([0x1F, 0x8B])

_WEEKDAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]

# Týž systémový prompt jako v n8n a v HW1 — každé pravidlo v něm vzniklo
# z pozorovaného selhání, ne z teorie.
SYSTEM_PROMPT = """\
Jsi asistent pro analýzu výkazů odpracovaného času. Odpovídáš česky, stručně a věcně.

Pravidla:
- Čísla nikdy neodhaduj ani nepočítej zpaměti — vždy je zjisti nástrojem.
- Když neznáš přesný název projektu, nejdřív si vypiš projekty nástrojem list_projects.
- Data zadávej v ISO formátu (YYYY-MM-DD), měsíce jako YYYY-MM.
- Složitější dotaz rozlož na víc volání nástrojů za sebou (např. porovnání dvou období
  = dvě volání) a teprve pak odpověz.
- Nevolej dvakrát tentýž nástroj se stejnými argumenty; výsledek už máš výš.
- Když nástroj vrátí pole "error", oprav argumenty a zkus to znovu.
- Chybovou hlášku z nástroje nikdy nepiš do odpovědi jako výsledek.
- Uveď jen čísla, která ti v této odpovědi vrátil nástroj. Nikdy nepokračuj
  v trendu, neodhaduj podle jiných měsíců a nepřebírej čísla z dřívější
  konverzace — ta mohou být chybná.
- Když nástroj vrátí nulu, prázdný seznam nebo pole "note", řekni rovnou, že
  za dané období nejsou záznamy, a uveď rozsah dostupných dat z "note".
- V odpovědi uveď konkrétní čísla, u peněz i měnu.
- Odpovídej prostým textem bez markdownu.

Dnešní datum je {today} ({weekday}). Aktuální měsíc je {month}.\
"""

# Šablona komponenty. Jméno metody = jméno nástroje, jak ho uvidí model.
COMPONENT_TEMPLATE = '''
import json
import urllib.error
import urllib.parse
import urllib.request

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.data import Data

BASE_URL = {base!r}


class {cls}(Component):
    """{doc}"""

    display_name = {name!r}
    description = {description!r}
    name = {name!r}

    inputs = [
{inputs}
    ]
    outputs = [Output(name="result", display_name="Výsledek", method={name!r})]

    def {name}(self) -> Data:
        params = {{}}
{collect}
        url = BASE_URL + ("?" + urllib.parse.urlencode(params) if params else "")
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError) as exc:
            # Chyba se vrací jako data, ne jako výjimka — model si ji má přečíst
            # a opravit se. Stejná zásada jako v HW1 (`tools.call_tool`).
            payload = {{"error": "volani {name} selhalo: " + str(exc)}}
        self.status = payload
        return Data(data=payload)
'''


def system_prompt() -> str:
    d = date.today()
    return SYSTEM_PROMPT.format(
        today=d.isoformat(), weekday=_WEEKDAYS[d.weekday()], month=d.strftime("%Y-%m")
    )


def _get_json(url: str, token: str | None = None) -> dict:
    headers = {"Accept-Encoding": "identity"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        raw = r.read()
        # LangFlow vrací katalog gzipovaný i při `Accept-Encoding: identity`.
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == GZIP_MAGIC:
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def fetch_tools() -> list[dict]:
    return _get_json(f"{API_IN_NETWORK}/tools")["tools"]


def langflow_token() -> str:
    return _get_json(f"{LANGFLOW_LOCAL}/api/v1/auto_login")["access_token"]


def full_registry(token: str) -> dict:
    """Registry builderu doplněná o komponenty z bundlů.

    `_load_registry_user_aware()` vrací jen jádro — Ollama je „bundle" a vypadne
    z něj, takže by z builderu nešla přidat.
    """
    registry = dict(_load_registry_user_aware())
    catalogue = _get_json(f"{LANGFLOW_LOCAL}/api/v1/all", token)
    for category, components in catalogue.items():
        if category == "component_display_names":
            continue
        for name, spec in components.items():
            registry.setdefault(name, spec)
    return registry


def split_params(fn: dict) -> tuple[dict, list[str], list[str]]:
    params = fn.get("parameters", {})
    props = params.get("properties", {})
    req = set(params.get("required", []))
    return props, [k for k in props if k in req], [k for k in props if k not in req]


def component_code(fn: dict) -> str:
    """Zdroják komponenty pro jeden nástroj.

    Vstupy jsou všechny parametry ze schématu, povinné i nepovinné. Na rozdíl od
    n8n je tady model může nechat prázdné a komponenta je do dotazu nezahrne —
    nepovinný parametr se tu tedy vyjádřit dá.
    """
    props, required, _ = split_params(fn)
    cls = "".join(part.capitalize() for part in fn["name"].split("_")) + "Component"

    inputs, collect = [], []
    for key, spec in props.items():
        info = spec.get("description", "")
        if "enum" in spec:
            info += " Jedna z hodnot: " + ", ".join(map(str, spec["enum"])) + "."
        if key not in required:
            info += " (nepovinné — když se nehodí, nech prázdné)"
        inputs.append(
            "        MessageTextInput(\n"
            f"            name={key!r},\n"
            f"            display_name={key!r},\n"
            f"            info={info.strip()!r},\n"
            f"            required={key in required},\n"
            "            tool_mode=True,\n"
            "        ),"
        )
        collect.append(
            f'        if getattr(self, {key!r}, None) not in (None, ""):\n'
            f"            params[{key!r}] = str(self.{key})"
        )

    return COMPONENT_TEMPLATE.format(
        cls=cls,
        name=fn["name"],
        doc=fn["description"].replace('"', "'")[:200],
        description=fn["description"],
        inputs="\n".join(inputs),
        collect="\n".join(collect) or "        pass",
        base=f"{API_IN_NETWORK}/run/{fn['name']}",
    )


def build_custom_node(code: str, token: str) -> dict:
    """Nechá LangFlow zdroják přeložit na uzel.

    Je to jediný spolehlivý způsob, jak dostat správně vyplněnou šablonu včetně
    typů vstupů — ručně skládaný uzel by se rozešel s tím, co čeká runtime.
    """
    body = json.dumps({"code": code}).encode("utf-8")
    req = urllib.request.Request(
        f"{LANGFLOW_LOCAL}/api/v1/custom_component",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == GZIP_MAGIC:
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))["data"]


def build() -> dict:
    token = langflow_token()
    registry = full_registry(token)
    flow: dict = {"data": {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}}

    chat_in = add_component(flow, "ChatInput", registry)["id"]
    agent = add_component(flow, "Agent", registry)["id"]
    chat_out = add_component(flow, "ChatOutput", registry)["id"]
    ollama = add_component(flow, "ext:ollama:ChatOllamaComponent@official", registry)["id"]

    configure_component(flow, agent, {
        "system_prompt": system_prompt(),
        # Obojí jsou vestavěné nástroje agenta. Datum má model v systémovém promptu
        # a kalkulačka ho svádí počítat zpaměti místo dotazu do databáze — v jednom
        # běhu na ni sáhl s výrazem `get_hours_worked('2026-08')`.
        "add_current_date_tool": False,
        "add_calculator_tool": False,
        "max_iterations": 8,
    })
    configure_component(flow, ollama, {
        "base_url": OLLAMA_PLACEHOLDER,
        "model_name": MODEL,
        "temperature": 0,
        # Výsledky nástrojů se posílají v každém dalším kroku znovu; s výchozím
        # oknem se konverzace tiše ořízne a agent zapomene, co mu nástroj vrátil.
        "num_ctx": 32768,
        "tool_model_enabled": True,
    })

    add_connection(flow, chat_in, "message", agent, "input_value")
    add_connection(flow, ollama, "model_output", agent, "model")
    add_connection(flow, agent, "response", chat_out, "input_value")

    # Pole `model` je typu `model`, což se v UI kreslí jako rozbalovací seznam.
    # Dokud se uzel nepřepne do „connection mode", hrana s modelem sice v datech
    # je, ale rozhraní i běh ji ignorují. Plátno ten příznak nastavuje samo při
    # propojení; low-level builder ne, tak ručně.
    agent_node = next(n for n in flow["data"]["nodes"] if n["id"] == agent)
    agent_node["data"]["_connectionMode"] = True

    for index, fn in enumerate(t["function"] for t in fetch_tools()):
        node_id = f"CustomComponent-{fn['name']}"
        inner = build_custom_node(component_code(fn), token)
        inner["display_name"] = fn["name"]
        inner["description"] = fn["description"]
        flow["data"]["nodes"].append({
            "id": node_id,
            "type": "genericNode",
            "position": {"x": -400 + index * 320, "y": 460},
            "data": {"id": node_id, "type": "CustomComponent", "node": inner},
        })
        add_connection(flow, node_id, "component_as_tool", agent, "tools")

    flow["name"] = "Výkazy — agent (HW2)"
    flow["description"] = "Agent nad výkazy odpracovaného času; nástroje z HW1 přes HTTP."
    return flow


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
