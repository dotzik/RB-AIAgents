"""Sdílené fixtures — dočasná databáze s deterministickými demo daty."""
from __future__ import annotations

from datetime import date

import pytest

from timeagent import db, seed

# Pevný kotevní den, aby testy nezávisely na dnešku.
ANCHOR = date(2026, 8, 31)


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    """Vytvoří dočasnou databázi a nasměruje na ni `TIMEAGENT_DB`."""
    path = tmp_path / "test.sqlite"
    conn = db.connect_rw(path)
    seed.seed_database(conn, anchor=ANCHOR, months=4, rng_seed=42)
    conn.close()
    monkeypatch.setenv("TIMEAGENT_DB", str(path))
    return path
