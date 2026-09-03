"""Datová vrstva — SQLite se schématem výkazů času.

Cesta k databázi se bere z env `TIMEAGENT_DB`, jinak `data/timeagent.sqlite`
vedle balíčku. Dotazovací cesta otevírá spojení **read-only**, aby se přes
nástroje agenta nedalo do dat zapsat; zápis mají jen `seed` a `importers`.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    client       TEXT NOT NULL,
    hourly_rate  REAL NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'CZK',
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS time_entries (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id),
    date        TEXT NOT NULL,          -- ISO YYYY-MM-DD
    hours       REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    billable    INTEGER NOT NULL DEFAULT 1,
    tag         TEXT
);

CREATE INDEX IF NOT EXISTS idx_entries_date    ON time_entries(date);
CREATE INDEX IF NOT EXISTS idx_entries_project ON time_entries(project_id);
"""


def default_db_path() -> Path:
    """Kde databáze leží, pokud ji nepřepíše env `TIMEAGENT_DB`."""
    env = os.environ.get("TIMEAGENT_DB")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "timeagent.sqlite"


def connect_rw(path: Path | None = None) -> sqlite3.Connection:
    """Zapisovatelné spojení — jen pro seed a import."""
    p = path or default_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_ro(path: Path | None = None) -> sqlite3.Connection:
    """Read-only spojení — touto cestou chodí všechny nástroje agenta."""
    p = path or default_db_path()
    if not p.exists():
        raise FileNotFoundError(
            f"Databáze {p} neexistuje. Vytvoř ji příkazem `uv run timeagent seed`."
        )
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
