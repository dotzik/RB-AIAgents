"""Dočasná databáze s deterministickými demo daty.

Kopie `HW1/tests/conftest.py` — HW1 fixtures nevystavuje jako importovatelné API.
"""
from __future__ import annotations

from datetime import date

import pytest
from timeagent import db, seed

# Pevný kotevní den; data sahají od května do konce srpna 2026.
ANCHOR = date(2026, 8, 31)


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    path = tmp_path / "test.sqlite"
    conn = db.connect_rw(path)
    seed.seed_database(conn, anchor=ANCHOR, months=4, rng_seed=42)
    conn.close()
    monkeypatch.setenv("TIMEAGENT_DB", str(path))
    return path
