"""HTTP most mezi no-code platformami a nástroji z HW1.

Ani n8n, ani LangFlow se k SQLite souboru rozumně nedostanou — n8n nemá SQLite
node v jádře, LangFlow by v kontejneru neviděl cestu na hostiteli. Obojí ale umí
zavolat HTTP. Tenhle modul proto vystavuje nástroje z HW1 jako REST a **žádnou
doménovou logiku sám nemá**: importuje `timeagent.tools` a jen ho obaluje.

Díky tomu volají obě platformy bit po bitu stejné nástroje, takže jejich srovnání
měří platformu, a ne dvě různé implementace téhož.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse
from timeagent import db, tools

app = FastAPI(
    title="timeagent-api",
    version="0.1.0",
    summary="Nástroje nad výkazy odpracovaného času pro n8n a LangFlow",
)

_SCHEMA_BY_NAME = {s["function"]["name"]: s for s in tools.TOOL_SCHEMAS}


@app.get("/health", tags=["provoz"])
def health() -> Any:
    """Ověří, že databáze existuje a jde otevřít.

    Vrací 503, když ne. Bez toho by se chyba projevila až jako podivná odpověď
    agenta a hledala by se ve workflow, kde není.
    """
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
    return {
        "status": "ok",
        "database": str(db.default_db_path()),
        "projects": projects,
        "time_entries": entries,
        "tools": len(tools.REGISTRY),
    }


@app.get("/tools", tags=["nástroje"])
def list_tools() -> Any:
    """Schémata všech nástrojů v OpenAI tvaru.

    Slouží jako dokumentace při skládání workflow — popis nástroje je rozhraní
    pro model, takže se má do platformy opsat doslova.
    """
    return {"count": len(tools.TOOL_SCHEMAS), "tools": tools.TOOL_SCHEMAS}


@app.get("/tools/{name}", tags=["nástroje"])
def tool_schema(name: str) -> Any:
    """Schéma jednoho nástroje."""
    schema = _SCHEMA_BY_NAME.get(name)
    if schema is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Neznámý nástroj {name!r}.", "available": list(tools.REGISTRY)},
        )
    return schema


@app.get("/run/{name}", tags=["nástroje"])
def run_tool_via_query(name: str, request: Request) -> Any:
    """Totéž co `POST /tools/{name}`, ale argumenty jdou v query stringu.

    Existuje kvůli LangFlow: jeho komponenta API Request vystavuje modelu jen
    URL (`tool_mode` má pouze `url_input`), takže tělo požadavku sestavit neumí.
    Bez GET varianty by se nad tímhle API v LangFlow nedal postavit nástroj.

    Hodnoty z query stringu jsou vždy řetězce; `coerce_arguments` v HW1 je
    narovná podle schématu ("160" na číslo, "true" na bool) a prázdné zahodí —
    tedy přesně to, co dělá i pro argumenty od modelu v POST variantě.
    """
    return tools.call_tool(name, dict(request.query_params))


@app.post("/tools/{name}", tags=["nástroje"])
def run_tool(name: str, arguments: dict[str, Any] = Body(default_factory=dict)) -> Any:
    """Spustí nástroj; tělo požadavku jsou jeho argumenty.

    **Chyba se vrací jako data se stavem 200**, ne jako 4xx/5xx. Není to nedbalost:
    `tools.call_tool` chytá výjimky a vrací `{"error": "..."}`, aby si model přečetl,
    co udělal špatně, a v dalším kroku se opravil. Kdyby tahle vrstva mapovala chyby
    na HTTP kódy, platforma by běh ukončila jako selhání requestu a model by tu
    zpětnou vazbu nikdy neviděl. Neopravovat na 500.
    """
    return tools.call_tool(name, arguments)
