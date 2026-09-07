"""Nástroje, které smí agent volat.

Zásada: **žádný nástroj nebere SQL od modelu.** Každý má typované parametry a
dotaz si sestaví sám z parametrizovaných dotazů. Model tak nemůže vytvořit
dotaz, na který jsme nepomysleli — ani omylem, ani na podvrženou instrukci
schovanou v datech. Spojení je navíc read-only (`db.connect_ro`).

Schémata jsou v OpenAI formátu; LiteLLM je přeloží pro každého poskytovatele.
Modul nezná žádné LLM SDK — proto se dá beze změny použít i v HW3 jako MCP server.
"""
from __future__ import annotations

import calendar
import sqlite3
from collections.abc import Callable
from contextlib import closing, suppress
from datetime import date, datetime
from typing import Any

from . import db


class ToolError(Exception):
    """Chyba, kterou má smysl vrátit modelu, aby si opravil argumenty."""


# --------------------------------------------------------------------------
# Pomocné funkce
# --------------------------------------------------------------------------

def _parse_date(value: str, field: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (ValueError, TypeError):
        raise ToolError(
            f"{field}: očekávám datum ve formátu YYYY-MM-DD, dostal jsem {value!r}"
        ) from None


def _month_bounds(month: str) -> tuple[str, str]:
    """První a poslední den měsíce jako ISO data."""
    try:
        year, mon = (int(x) for x in str(month).split("-"))
        first = date(year, mon, 1)
    except (ValueError, TypeError):
        raise ToolError(f"month: očekávám formát YYYY-MM, dostal jsem {month!r}") from None
    last = date(year, mon, calendar.monthrange(year, mon)[1])
    return first.isoformat(), last.isoformat()


def _normalize_month(month: str) -> str:
    """`2026-8` na `2026-08` — ať výstup nekopíruje překlepy ze vstupu."""
    return _month_bounds(month)[0][:7]


def _resolve_project(conn: sqlite3.Connection, needle: str) -> sqlite3.Row:
    """Najde projekt podle id, názvu nebo klienta (case-insensitive, částečná shoda)."""
    if not needle:
        raise ToolError("project: prázdná hodnota")
    rows = conn.execute(
        "SELECT * FROM projects WHERE lower(id) = lower(?)", (needle,)
    ).fetchall()
    if not rows:
        # % a _ ve vstupu jsou hledaný text, ne zástupné znaky vzoru
        escaped = (
            needle.lower()
            .replace("!", "!!")
            .replace("%", "!%")
            .replace("_", "!_")
        )
        like = f"%{escaped}%"
        rows = conn.execute(
            "SELECT * FROM projects "
            "WHERE lower(name) LIKE ? ESCAPE '!' "
            "OR lower(client) LIKE ? ESCAPE '!'",
            (like, like),
        ).fetchall()
    if not rows:
        known = conn.execute("SELECT id, name, client FROM projects").fetchall()
        raise ToolError(
            f"Projekt {needle!r} neexistuje. Dostupné: "
            + ", ".join(f"{r['id']} ({r['client']})" for r in known)
        )
    if len(rows) > 1:
        raise ToolError(
            f"Projekt {needle!r} je nejednoznačný, odpovídá: "
            + ", ".join(f"{r['id']} — {r['name']}" for r in rows)
            + ". Upřesni ho identifikátorem."
        )
    return rows[0]


def _billable_clause(billable: bool | None) -> tuple[str, list[Any]]:
    if billable is None:
        return "", []
    return " AND e.billable = ?", [1 if billable else 0]


def _empty_note(conn: sqlite3.Connection) -> str:
    """Věta do výsledku, když dotaz nic nenašel.

    Nula sama o sobě je pro model dvojznačná: neví, jestli se v tom období
    nepracovalo, nebo jestli tam databáze prostě nesahá. Když to nedostane
    řečené, dopočítá si „pokračování trendu" a vydá vymyšlená čísla — pozorováno
    na dotazech na říjen a listopad, které v datech nejsou.

    Proto se vrací hotová věta včetně rozsahu dat, kterou může model rovnou
    zopakovat. Je to táž zásada jako u `{"error": ...}`: dát modelu fakt
    v podobě, se kterou umí pracovat, místo aby si domýšlel.
    """
    row = conn.execute("SELECT MIN(date) AS od, MAX(date) AS do FROM time_entries").fetchone()
    if not row or not row["od"]:
        return "Databáze neobsahuje žádné výkazy."
    return (
        "Za zadané období nejsou v databázi žádné záznamy. "
        f"Data jsou k dispozici od {row['od']} do {row['do']}. "
        "Neodhaduj chybějící hodnoty — odpověz, že za dané období záznamy nejsou."
    )


# --------------------------------------------------------------------------
# Nástroje
# --------------------------------------------------------------------------

def list_projects(active_only: bool = False) -> dict[str, Any]:
    """Seznam projektů včetně klientů a hodinových sazeb."""
    with closing(db.connect_ro()) as conn:
        sql = "SELECT id, name, client, hourly_rate, currency, active FROM projects"
        if active_only:
            sql += " WHERE active = 1"
        rows = conn.execute(sql + " ORDER BY id").fetchall()
    return {"count": len(rows), "projects": db.rows_to_dicts(rows)}


def query_time_entries(
    date_from: str,
    date_to: str,
    project: str | None = None,
    billable: bool | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Součet odpracovaných hodin za období, volitelně jen za jeden projekt.

    Vrací agregát (hodiny, počet záznamů, počet dnů) a malý vzorek záznamů.
    Vzorek je záměrně krátký: výsledky nástrojů se posílají modelu v každém
    dalším kroku znovu, takže každý ušetřený řádek se počítá vícekrát.
    """
    date_from = _parse_date(date_from, "date_from")
    date_to = _parse_date(date_to, "date_to")
    if date_from > date_to:
        raise ToolError("date_from je pozdější než date_to")
    limit = max(0, min(int(limit), 20))

    with closing(db.connect_ro()) as conn:
        where = "WHERE e.date BETWEEN ? AND ?"
        params: list[Any] = [date_from, date_to]
        proj_row = None
        if project:
            proj_row = _resolve_project(conn, project)
            where += " AND e.project_id = ?"
            params.append(proj_row["id"])
        clause, extra = _billable_clause(billable)
        where += clause
        params += extra

        agg = conn.execute(
            f"""SELECT COALESCE(SUM(e.hours), 0) AS hours,
                       COUNT(*) AS entries,
                       COUNT(DISTINCT e.date) AS days
                FROM time_entries e {where}""",
            params,
        ).fetchone()
        sample = conn.execute(
            f"""SELECT e.date, e.project_id, p.client, e.hours, e.description,
                       e.billable, e.tag
                FROM time_entries e JOIN projects p ON p.id = e.project_id
                {where} ORDER BY e.date DESC LIMIT ?""",
            [*params, limit],
        ).fetchall()

        note = _empty_note(conn) if agg["entries"] == 0 else None

    out = {
        "date_from": date_from,
        "date_to": date_to,
        "project": proj_row["id"] if proj_row else None,
        "billable_filter": billable,
        "total_hours": round(agg["hours"], 2),
        "entry_count": agg["entries"],
        "days_worked": agg["days"],
        "sample_entries": db.rows_to_dicts(sample),
    }
    if note:
        out["note"] = note
    return out


# Kolik skupin summarize_by vypíše. Zbytek se ořízne a řekne se to v `note`.
MAX_GROUPS = 30

_DIMENSIONS: dict[str, str] = {
    "project": "e.project_id",
    "client": "p.client",
    "day": "e.date",
    "week": "strftime('%Y-W%W', e.date)",
    "month": "substr(e.date, 1, 7)",
    "tag": "COALESCE(e.tag, 'bez tagu')",
}


def summarize_by(
    dimension: str,
    date_from: str,
    date_to: str,
    project: str | None = None,
    billable: bool | None = None,
) -> dict[str, Any]:
    """Souhrn hodin seskupený podle projektu, klienta, dne, týdne, měsíce nebo tagu."""
    if dimension not in _DIMENSIONS:
        raise ToolError(
            f"dimension: {dimension!r} neznám, použij jednu z: {', '.join(_DIMENSIONS)}"
        )
    date_from = _parse_date(date_from, "date_from")
    date_to = _parse_date(date_to, "date_to")
    expr = _DIMENSIONS[dimension]  # z whitelistu, ne od modelu

    with closing(db.connect_ro()) as conn:
        where = "WHERE e.date BETWEEN ? AND ?"
        params: list[Any] = [date_from, date_to]
        if project:
            where += " AND e.project_id = ?"
            params.append(_resolve_project(conn, project)["id"])
        clause, extra = _billable_clause(billable)
        where += clause
        params += extra

        rows = conn.execute(
            f"""SELECT {expr} AS bucket,
                       ROUND(SUM(e.hours), 2) AS hours,
                       COUNT(*) AS entries
                FROM time_entries e JOIN projects p ON p.id = e.project_id
                {where}
                GROUP BY bucket ORDER BY hours DESC""",
            params,
        ).fetchall()

        note = _empty_note(conn) if not rows else None

    groups = db.rows_to_dicts(rows)
    # Součet ze všech skupin, i těch odříznutých — strop platí na výpis, ne na
    # matematiku.
    total = round(sum(g["hours"] for g in groups), 2)

    # Strop výpisu ze stejného důvodu jako u `query_time_entries`: výsledek
    # nástroje se posílá modelu v každém dalším kroku znovu. Rozpad po dnech za
    # dva roky je legitimní dotaz a dá 425 skupin, tedy ~7 700 tokenů v jednom
    # výsledku — čtvrtina okna, na každý krok. Skupiny jsou seřazené sestupně,
    # takže odříznuté jsou ty nejmenší.
    omitted = max(0, len(groups) - MAX_GROUPS)
    out = {
        "dimension": dimension,
        "date_from": date_from,
        "date_to": date_to,
        "total_hours": total,
        "group_count": len(groups),
        "groups": groups[:MAX_GROUPS],
    }
    if omitted:
        out["note"] = (
            f"Zobrazeno {MAX_GROUPS} největších skupin z {len(groups)}; "
            f"zbylých {omitted} je menších. `total_hours` je součet ze všech."
        )
    elif note:
        out["note"] = note
    return out


def compute_invoice(project: str, month: str, vat_rate: float = 0.21) -> dict[str, Any]:
    """Fakturační podklad za projekt a měsíc: hodiny x sazba, základ, DPH, celkem.

    Počítá jen fakturovatelné (`billable`) záznamy.
    """
    date_from, date_to = _month_bounds(month)
    month = _normalize_month(month)
    try:
        vat_rate = float(vat_rate)
    except (TypeError, ValueError):
        raise ToolError(f"vat_rate: očekávám číslo, dostal jsem {vat_rate!r}") from None
    if not 0 <= vat_rate < 1:
        raise ToolError("vat_rate: sazba je desetinné číslo, např. 0.21 pro 21 %")

    with closing(db.connect_ro()) as conn:
        proj = _resolve_project(conn, project)
        row = conn.execute(
            """SELECT COALESCE(SUM(hours), 0) AS hours, COUNT(*) AS entries
               FROM time_entries
               WHERE project_id = ? AND billable = 1 AND date BETWEEN ? AND ?""",
            (proj["id"], date_from, date_to),
        ).fetchone()

        note = _empty_note(conn) if row["entries"] == 0 else None

    hours = round(row["hours"], 2)
    base = round(hours * proj["hourly_rate"], 2)
    vat = round(base * vat_rate, 2)
    return {
        "project": proj["id"],
        "project_name": proj["name"],
        "client": proj["client"],
        "month": month,
        "billable_hours": hours,
        "entry_count": row["entries"],
        "hourly_rate": proj["hourly_rate"],
        "currency": proj["currency"],
        "amount_excl_vat": base,
        "vat_rate": vat_rate,
        "vat_amount": vat,
        "amount_incl_vat": round(base + vat, 2),
        **({"note": note} if note else {}),
    }


def capacity_check(month: str, target_hours: float = 160.0) -> dict[str, Any]:
    """Porovná odpracované hodiny v měsíci proti cíli — kolik chybí nebo přebývá."""
    date_from, date_to = _month_bounds(month)
    month = _normalize_month(month)
    try:
        target = float(target_hours)
    except (TypeError, ValueError):
        raise ToolError(
            f"target_hours: očekávám číslo, dostal jsem {target_hours!r}"
        ) from None
    if target <= 0:
        raise ToolError("target_hours musí být kladné číslo")

    with closing(db.connect_ro()) as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(hours), 0) AS total,
                      COALESCE(SUM(CASE WHEN billable = 1 THEN hours END), 0) AS billable,
                      COUNT(DISTINCT date) AS days
               FROM time_entries WHERE date BETWEEN ? AND ?""",
            (date_from, date_to),
        ).fetchone()

        note = _empty_note(conn) if row["days"] == 0 else None

    total = round(row["total"], 2)
    billable = round(row["billable"], 2)
    return {
        "month": month,
        "total_hours": total,
        "billable_hours": billable,
        "non_billable_hours": round(total - billable, 2),
        "days_worked": row["days"],
        "target_hours": target,
        "difference": round(total - target, 2),
        "fulfilment_pct": round(total / target * 100, 1),
        "status": "splněno" if total >= target else "nesplněno",
        **({"note": note} if note else {}),
    }


# --------------------------------------------------------------------------
# Registr a schémata
# --------------------------------------------------------------------------

REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "list_projects": list_projects,
    "query_time_entries": query_time_entries,
    "summarize_by": summarize_by,
    "compute_invoice": compute_invoice,
    "capacity_check": capacity_check,
}

_DATE_PROP = {"type": "string", "description": "Datum ve formátu YYYY-MM-DD"}
_PROJECT_PROP = {
    "type": "string",
    "description": "Projekt — identifikátor, část názvu nebo jméno klienta",
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": (
                "Vypíše projekty: identifikátor, název, jméno klienta, hodinovou "
                "sazbu a měnu. Zavolej jako první, když neznáš přesný název "
                "projektu nebo potřebuješ sazbu. Sazby jinde nezjistíš."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "active_only": {
                        "type": "boolean",
                        "description": "Jen aktivní projekty (výchozí false)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_time_entries",
            "description": (
                "Součet odpracovaných hodin za libovolné období, volitelně jen za "
                "jeden projekt. Vrací celkové hodiny, počet záznamů, počet "
                "odpracovaných dnů a několik ukázkových záznamů. Použij na období, "
                "která nejsou celý měsíc; na jeden měsíc je vhodnější "
                "capacity_check, na rozpady summarize_by."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": _DATE_PROP,
                    "date_to": _DATE_PROP,
                    "project": _PROJECT_PROP,
                    "billable": {
                        "type": "boolean",
                        "description": (
                            "Fakturovatelnost: true = jen práce účtovaná klientovi, "
                            "false = jen neúčtovaná (interní). Vynech pro obojí."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Kolik ukázkových záznamů vrátit (výchozí 3, max 20). "
                            "Součty se počítají ze všech záznamů, limit je neovlivní."
                        ),
                    },
                },
                "required": ["date_from", "date_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_by",
            "description": (
                "Souhrn hodin seskupený podle zvolené dimenze, seřazený sestupně. "
                "Vrací pro každou skupinu její název a odpracované hodiny. Použij "
                "vždy, když se ptáš 'na čem/kdy nejvíc' nebo potřebuješ rozpad — "
                "první skupina ve výsledku je ta s nejvíce hodinami. Vypíše se "
                "nejvýš 30 největších skupin; total_hours je vždy součet ze všech."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension": {
                        "type": "string",
                        "enum": list(_DIMENSIONS),
                        "description": (
                            "Podle čeho seskupit. "
                            "project = zakázka, client = odběratel, "
                            "tag = druh činnosti (vývoj, analýza, schůzka, "
                            "code review, nasazení, podpora, dokumentace), "
                            "day / week / month = časové období."
                        ),
                    },
                    "date_from": _DATE_PROP,
                    "date_to": _DATE_PROP,
                    "project": _PROJECT_PROP,
                    "billable": {
                        "type": "boolean",
                        "description": (
                            "Fakturovatelnost: true = jen účtované klientovi, "
                            "false = jen interní. Vynech pro obojí."
                        ),
                    },
                },
                "required": ["dimension", "date_from", "date_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_invoice",
            "description": (
                "Fakturační podklad za jeden projekt a měsíc. Vrací fakturovatelné "
                "hodiny, sazbu, částku bez DPH (amount_excl_vat), DPH a částku "
                "celkem (amount_incl_vat). Nefakturovatelné hodiny ignoruje. "
                "Když se ptáš 'kolik naúčtovat', použij tenhle nástroj, ne "
                "násobení hodin sazbou."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project": _PROJECT_PROP,
                    "month": {"type": "string", "description": "Měsíc ve formátu YYYY-MM"},
                    "vat_rate": {
                        "type": "number",
                        "description": "Sazba DPH jako desetinné číslo, výchozí 0.21",
                    },
                },
                "required": ["project", "month"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capacity_check",
            "description": (
                "Přehled celého měsíce přes všechny projekty: odpracované hodiny "
                "celkem, z toho fakturovatelné a nefakturovatelné, počet "
                "odpracovaných dnů, rozdíl proti cíli a plnění v procentech. "
                "Nejrychlejší cesta k otázkám typu 'kolik hodin jsem odpracoval "
                "v měsíci'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Měsíc ve formátu YYYY-MM"},
                    "target_hours": {
                        "type": "number",
                        "description": "Cílový počet hodin, výchozí 160",
                    },
                },
                "required": ["month"],
            },
        },
    },
]


_SCHEMA_BY_NAME = {s["function"]["name"]: s["function"]["parameters"] for s in TOOL_SCHEMAS}
_NULLISH = {"null", "none", "nil", "undefined", ""}


def coerce_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Srovná argumenty od modelu podle schématu.

    Menší modely posílají všechno jako řetězce — `"true"` místo `true`,
    `"null"` místo vynechaného parametru. Místo aby to každý nástroj řešil sám
    (nebo aby to tiše prošlo jako pravdivý řetězec), narovná se to tady na jednom
    místě podle typů, které máme ve schématu.
    """
    schema = _SCHEMA_BY_NAME.get(name)
    if not schema:
        return arguments
    properties = schema.get("properties", {})
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        expected = properties.get(key, {}).get("type")
        if isinstance(value, str):
            if value.strip().lower() in _NULLISH:
                continue  # vynechaný parametr, ne hodnota "null"
            if expected == "boolean":
                lowered = value.strip().lower()
                if lowered in {"true", "yes", "1"}:
                    value = True
                elif lowered in {"false", "no", "0"}:
                    value = False
            elif expected in {"number", "integer"}:
                # Nepřevoditelnou hodnotu necháme být — nástroj si na ni
                # postěžuje sám a s vlastní, srozumitelnější hláškou.
                with suppress(ValueError):
                    value = float(value) if expected == "number" else int(float(value))
        elif value is None:
            continue
        out[key] = value
    return out


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Spustí nástroj a chyby vrátí jako data.

    Výjimka by smyčku agenta shodila; jako `{"error": ...}` ji model uvidí
    a může si opravit argumenty a zkusit to znovu.
    """
    fn = REGISTRY.get(name)
    if fn is None:
        return {"error": f"Neznámý nástroj {name!r}. Dostupné: {', '.join(REGISTRY)}"}
    try:
        return fn(**coerce_arguments(name, arguments))
    except ToolError as exc:
        return {"error": str(exc)}
    except TypeError as exc:
        return {"error": f"Špatné argumenty pro {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 — model má chybu vidět, ne spadnout
        return {"error": f"{type(exc).__name__}: {exc}"}
