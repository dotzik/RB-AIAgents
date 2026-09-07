"""Generátor anonymního demo datasetu.

Do repozitáře nesmí žádná reálná data ani jména klientů. Demo dataset je proto
generovaný a **deterministický** (pevný `rng_seed`) — stejný příkaz dá vždycky
stejná čísla, takže testy i ukázky v README sedí.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

from . import db

# Fiktivní klienti — záměrně notoricky známá "placeholder" jména z učebnic.
PROJECTS: list[dict] = [
    {"id": "ACME", "name": "Acme — platforma objednávek", "client": "Acme Corp",
     "hourly_rate": 1500.0, "currency": "CZK", "active": 1, "weight": 1.0},
    {"id": "NWND", "name": "Northwind — datový sklad", "client": "Northwind Trading",
     "hourly_rate": 1350.0, "currency": "CZK", "active": 1, "weight": 0.8},
    {"id": "GLBX", "name": "Globex — mobilní aplikace", "client": "Globex",
     "hourly_rate": 1800.0, "currency": "CZK", "active": 1, "weight": 0.5},
    # Ukončený projekt — záznamy končí tři měsíce zpět. Agent tak má co objevit.
    {"id": "INIT", "name": "Initech — bezpečnostní audit", "client": "Initech",
     "hourly_rate": 2100.0, "currency": "CZK", "active": 0, "weight": 0.5,
     "ended_months_ago": 3},
    {"id": "INTR", "name": "Interní — vlastní nástroje", "client": "Interní",
     "hourly_rate": 0.0, "currency": "CZK", "active": 1, "weight": 0.4},
]

ACTIVITIES: list[tuple[str, str]] = [
    ("vyvoj", "implementace {feature}"),
    ("vyvoj", "refaktoring {feature}"),
    ("analyza", "analýza požadavků — {feature}"),
    ("schuzka", "schůzka s klientem"),
    ("review", "code review PR"),
    ("nasazeni", "nasazení do produkce"),
    ("podpora", "řešení incidentu — {feature}"),
    ("dokumentace", "dokumentace {feature}"),
]

FEATURES = [
    "importní pipeline", "reporting", "autentizace", "notifikace",
    "fakturace", "vyhledávání", "exporty", "migrace dat",
]


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def seed_database(
    conn: sqlite3.Connection,
    *,
    anchor: date | None = None,
    months: int = 21,
    rng_seed: int = 42,
) -> dict[str, int]:
    """Naplní databázi demo daty za `months` měsíců zpět od `anchor` (dnešek).

    Vrací počty vložených řádků.
    """
    anchor = anchor or date.today()
    rng = random.Random(rng_seed)

    db.init_schema(conn)
    conn.execute("DELETE FROM time_entries")
    conn.execute("DELETE FROM projects")
    conn.executemany(
        "INSERT INTO projects (id, name, client, hourly_rate, currency, active) "
        "VALUES (:id, :name, :client, :hourly_rate, :currency, :active)",
        [{k: p[k] for k in ("id", "name", "client", "hourly_rate", "currency", "active")}
         for p in PROJECTS],
    )

    start = _add_months(_month_start(anchor), -(months - 1))
    weights = [p["weight"] for p in PROJECTS]
    entries: list[dict] = []
    counter = 0
    day = start
    while day <= anchor:
        if day.weekday() < 5:  # jen pracovní dny
            # Kolik záznamů ten den vznikne. Občas volno (dovolená, nemoc).
            n_entries = rng.choices([0, 2, 3, 4], weights=[5, 25, 45, 25])[0]
            for _ in range(n_entries):
                proj = rng.choices(PROJECTS, weights=weights)[0]
                ended = proj.get("ended_months_ago")
                if ended is not None and day >= _add_months(_month_start(anchor), -ended):
                    continue
                tag, template = rng.choice(ACTIVITIES)
                hours = round(rng.uniform(1.0, 4.5) * 2) / 2  # na půlhodiny
                if hours <= 0:
                    continue
                counter += 1
                entries.append({
                    "id": f"E{counter:05d}",
                    "project_id": proj["id"],
                    "date": day.isoformat(),
                    "hours": hours,
                    "description": template.format(feature=rng.choice(FEATURES)),
                    "billable": 0 if proj["id"] == "INTR" else 1,
                    "tag": tag,
                })
        day += timedelta(days=1)

    conn.executemany(
        "INSERT INTO time_entries (id, project_id, date, hours, description, billable, tag) "
        "VALUES (:id, :project_id, :date, :hours, :description, :billable, :tag)",
        entries,
    )
    conn.commit()
    return {"projects": len(PROJECTS), "time_entries": len(entries)}
