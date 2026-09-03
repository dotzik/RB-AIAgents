"""Volitelný import reálných výkazů z Clockify do lokální SQLite.

Bez tohohle modulu je projekt plně funkční — demo databáze stačí. Je tu proto,
aby agent nebyl jen cvičení: po `timeagent import` počítá nad skutečnými
odpracovanými hodinami.

Data zůstávají **výhradně lokálně**: `*.sqlite` je v `.gitignore` a do
repozitáře se nikdy nedostane.

Potřebné proměnné v `.env`:
    CLOCKIFY_API_KEY        Clockify → Profile settings → API → Generate
    CLOCKIFY_WORKSPACE_ID   volitelné, jinak se vezme výchozí workspace
    CLOCKIFY_DEFAULT_RATE   hodinová sazba pro projekty, které ji v Clockify nemají
"""
from __future__ import annotations

import calendar
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.clockify.me/api/v1"
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>[\d.]+)S)?)?$"
)


class ClockifyError(RuntimeError):
    """Import selhal — chybí konfigurace nebo API vrátilo chybu."""


def parse_duration(value: str | None) -> float:
    """ISO 8601 trvání (`PT1H30M`) na hodiny. Běžící záznam nemá trvání → 0."""
    if not value:
        return 0.0
    m = _DURATION_RE.match(value)
    if not m:
        return 0.0
    days = int(m.group("days") or 0)
    hours = int(m.group("h") or 0)
    minutes = int(m.group("m") or 0)
    seconds = float(m.group("s") or 0)
    return round(days * 24 + hours + minutes / 60 + seconds / 3600, 4)


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    try:
        year, mon = (int(x) for x in month.split("-"))
    except ValueError:
        raise ClockifyError(f"month: očekávám YYYY-MM, dostal jsem {month!r}")
    last_day = calendar.monthrange(year, mon)[1]
    return (
        datetime(year, mon, 1, tzinfo=timezone.utc),
        datetime(year, mon, last_day, 23, 59, 59, tzinfo=timezone.utc),
    )


class ClockifyClient:
    """Minimální REST klient — jen to, co import potřebuje."""

    def __init__(self, api_key: str, workspace_id: str | None = None) -> None:
        self.api_key = api_key
        self.workspace_id = workspace_id

    @classmethod
    def from_env(cls) -> "ClockifyClient":
        key = os.environ.get("CLOCKIFY_API_KEY")
        if not key:
            raise ClockifyError(
                "Chybí CLOCKIFY_API_KEY v .env "
                "(Clockify → Profile settings → API → Generate). "
                "Bez klíče použij `timeagent seed` a demo data."
            )
        return cls(key, os.environ.get("CLOCKIFY_WORKSPACE_ID") or None)

    def _get(self, path: str, **params: Any) -> Any:
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.get(
                    f"{BASE_URL}{path}",
                    headers={"X-Api-Key": self.api_key},
                    params=params,
                )
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as exc:
            raise ClockifyError(f"Clockify API selhalo na {path}: {exc}") from exc

    def whoami(self) -> dict[str, Any]:
        return self._get("/user")

    def resolve_workspace(self, user: dict[str, Any]) -> str:
        ws = self.workspace_id or user.get("defaultWorkspace")
        if not ws:
            raise ClockifyError("Nepodařilo se určit workspace — nastav CLOCKIFY_WORKSPACE_ID")
        return ws

    def projects(self, workspace_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._get(
                f"/workspaces/{workspace_id}/projects",
                **{"page": page, "page-size": 200, "archived": "false"},
            )
            out.extend(batch)
            if len(batch) < 200:
                return out
            page += 1

    def time_entries(
        self, workspace_id: str, user_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._get(
                f"/workspaces/{workspace_id}/user/{user_id}/time-entries",
                start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                **{"page": page, "page-size": 200},
            )
            out.extend(batch)
            if len(batch) < 200:
                return out
            page += 1


def _rate_of(project: dict[str, Any], fallback: float) -> float:
    """Clockify drží sazbu v haléřích/centech, a často vůbec."""
    rate = project.get("hourlyRate") or {}
    amount = rate.get("amount")
    return round(amount / 100, 2) if amount else fallback


def _currency_of(project: dict[str, Any]) -> str:
    return (project.get("hourlyRate") or {}).get("currency") or "CZK"


def import_month(
    conn: sqlite3.Connection,
    *,
    month: str,
    replace: bool = True,
    verbose: bool = False,
    client: ClockifyClient | None = None,
) -> dict[str, int]:
    """Načte projekty a záznamy za daný měsíc do databáze."""
    from .. import db as dbmod

    start, end = _month_bounds(month)
    api = client or ClockifyClient.from_env()
    fallback_rate = float(os.environ.get("CLOCKIFY_DEFAULT_RATE", "0") or 0)

    user = api.whoami()
    workspace = api.resolve_workspace(user)
    if verbose:
        print(f"Clockify: {user.get('name', user.get('id'))}, workspace {workspace}")

    dbmod.init_schema(conn)

    projects = api.projects(workspace)
    conn.executemany(
        "INSERT INTO projects (id, name, client, hourly_rate, currency, active) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, client=excluded.client, "
        "hourly_rate=excluded.hourly_rate, currency=excluded.currency, "
        "active=excluded.active",
        [
            (
                p["id"],
                p.get("name", p["id"]),
                (p.get("clientName") or "bez klienta"),
                _rate_of(p, fallback_rate),
                _currency_of(p),
                0 if p.get("archived") else 1,
            )
            for p in projects
        ],
    )

    entries = api.time_entries(workspace, user["id"], start, end)
    known = {p["id"] for p in projects}
    rows = []
    skipped = 0
    for e in entries:
        interval = e.get("timeInterval") or {}
        hours = parse_duration(interval.get("duration"))
        project_id = e.get("projectId")
        if hours <= 0 or project_id not in known:
            skipped += 1
            continue
        day = (interval.get("start") or "")[:10]
        rows.append((
            e["id"], project_id, day, hours,
            e.get("description") or "", 1 if e.get("billable", True) else 0,
            (e.get("tagIds") or [None])[0],
        ))

    if replace:
        first, last = start.date().isoformat(), end.date().isoformat()
        conn.execute("DELETE FROM time_entries WHERE date BETWEEN ? AND ?", (first, last))
    conn.executemany(
        "INSERT OR REPLACE INTO time_entries "
        "(id, project_id, date, hours, description, billable, tag) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    if verbose and skipped:
        print(f"Přeskočeno {skipped} záznamů (běžící nebo bez projektu).")
    return {"projects": len(projects), "time_entries": len(rows)}


def today_month() -> str:
    return date.today().strftime("%Y-%m")
