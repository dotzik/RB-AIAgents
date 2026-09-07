"""Testy nástrojů — běží nad dočasnou databází, bez jakéhokoli volání LLM."""
from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from timeagent import tools


def _sql(path, query, params=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(query, params).fetchone()[0]
    finally:
        conn.close()


def test_list_projects(demo_db):
    out = tools.list_projects()
    assert out["count"] == 5
    ids = {p["id"] for p in out["projects"]}
    assert ids == {"ACME", "NWND", "GLBX", "INIT", "INTR"}

    active = tools.list_projects(active_only=True)
    assert active["count"] == 4
    assert all(p["active"] == 1 for p in active["projects"])


def test_query_time_entries_matches_sql(demo_db):
    out = tools.query_time_entries(date_from="2026-08-01", date_to="2026-08-31")
    expected = _sql(
        demo_db,
        "SELECT ROUND(COALESCE(SUM(hours), 0), 2) FROM time_entries "
        "WHERE date BETWEEN ? AND ?",
        ("2026-08-01", "2026-08-31"),
    )
    assert out["total_hours"] == expected
    assert out["entry_count"] > 0
    assert len(out["sample_entries"]) <= 10


def test_query_respects_month_boundary(demo_db):
    july = tools.query_time_entries(date_from="2026-07-01", date_to="2026-07-31")
    august = tools.query_time_entries(date_from="2026-08-01", date_to="2026-08-31")
    both = tools.query_time_entries(date_from="2026-07-01", date_to="2026-08-31")
    assert round(july["total_hours"] + august["total_hours"], 2) == both["total_hours"]


def test_query_project_filter(demo_db):
    by_id = tools.query_time_entries("2026-08-01", "2026-08-31", project="ACME")
    by_client = tools.query_time_entries("2026-08-01", "2026-08-31", project="acme corp")
    assert by_id["total_hours"] == by_client["total_hours"]
    assert by_id["project"] == "ACME"


def test_billable_filter_splits_total(demo_db):
    total = tools.query_time_entries("2026-08-01", "2026-08-31")
    billable = tools.query_time_entries("2026-08-01", "2026-08-31", billable=True)
    non = tools.query_time_entries("2026-08-01", "2026-08-31", billable=False)
    assert round(billable["total_hours"] + non["total_hours"], 2) == total["total_hours"]
    # nefakturovatelný je jen interní projekt
    assert non["total_hours"] > 0


def test_summarize_by_project_sums_to_total(demo_db):
    out = tools.summarize_by("project", "2026-08-01", "2026-08-31")
    total = tools.query_time_entries("2026-08-01", "2026-08-31")["total_hours"]
    assert round(sum(g["hours"] for g in out["groups"]), 2) == total
    assert out["groups"] == sorted(out["groups"], key=lambda g: -g["hours"])


@pytest.mark.parametrize("dimension", ["project", "client", "day", "week", "month", "tag"])
def test_summarize_all_dimensions(demo_db, dimension):
    out = tools.summarize_by(dimension, "2026-06-01", "2026-08-31")
    assert out["groups"]
    assert out["total_hours"] > 0


def test_compute_invoice(demo_db):
    out = tools.compute_invoice(project="ACME", month="2026-08")
    hours = _sql(
        demo_db,
        "SELECT ROUND(COALESCE(SUM(hours), 0), 2) FROM time_entries "
        "WHERE project_id = 'ACME' AND billable = 1 AND date BETWEEN ? AND ?",
        ("2026-08-01", "2026-08-31"),
    )
    assert out["billable_hours"] == hours
    assert out["amount_excl_vat"] == round(hours * 1500.0, 2)
    assert out["vat_amount"] == round(out["amount_excl_vat"] * 0.21, 2)
    assert out["amount_incl_vat"] == round(
        out["amount_excl_vat"] + out["vat_amount"], 2
    )


def test_compute_invoice_ignores_non_billable(demo_db):
    out = tools.compute_invoice(project="INTR", month="2026-08")
    assert out["billable_hours"] == 0.0
    assert out["amount_incl_vat"] == 0.0


def test_capacity_check(demo_db):
    out = tools.capacity_check(month="2026-08", target_hours=100)
    total = tools.query_time_entries("2026-08-01", "2026-08-31")["total_hours"]
    assert out["total_hours"] == total
    assert out["difference"] == round(total - 100, 2)
    assert out["status"] == ("splněno" if total >= 100 else "nesplněno")
    assert round(out["billable_hours"] + out["non_billable_hours"], 2) == total


# --------------------------------------------------------------------------
# Chybové cesty — model musí dostat srozumitelnou chybu, ne výjimku
# --------------------------------------------------------------------------

def test_unknown_project_lists_options(demo_db):
    out = tools.call_tool("compute_invoice", {"project": "Nexus", "month": "2026-08"})
    assert "error" in out
    assert "ACME" in out["error"]


def test_bad_month_format(demo_db):
    out = tools.call_tool("capacity_check", {"month": "srpen 2026"})
    assert "YYYY-MM" in out["error"]


def test_bad_date_format(demo_db):
    out = tools.call_tool(
        "query_time_entries", {"date_from": "1.8.2026", "date_to": "2026-08-31"}
    )
    assert "YYYY-MM-DD" in out["error"]


def test_reversed_range(demo_db):
    out = tools.call_tool(
        "query_time_entries", {"date_from": "2026-08-31", "date_to": "2026-08-01"}
    )
    assert "error" in out


def test_unknown_tool():
    out = tools.call_tool("drop_database", {})
    assert "Neznámý nástroj" in out["error"]


def test_unknown_dimension(demo_db):
    out = tools.call_tool(
        "summarize_by",
        {"dimension": "barva", "date_from": "2026-08-01", "date_to": "2026-08-31"},
    )
    assert "neznám" in out["error"]


def test_bad_arguments(demo_db):
    out = tools.call_tool("compute_invoice", {"projekt": "ACME"})
    assert "Špatné argumenty" in out["error"]


def test_database_is_read_only(demo_db):
    from timeagent import db as dbmod

    with closing(dbmod.connect_ro()) as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM time_entries")


def test_every_schema_has_implementation():
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    assert names == set(tools.REGISTRY)


# --------------------------------------------------------------------------
# Narovnání argumentů — menší modely posílají všechno jako řetězce
# --------------------------------------------------------------------------

def test_coerce_drops_string_null(demo_db):
    out = tools.call_tool("summarize_by", {
        "dimension": "day", "date_from": "2026-08-01", "date_to": "2026-08-31",
        "project": "null",
    })
    assert "error" not in out
    assert out["total_hours"] > 0


def test_coerce_string_booleans(demo_db):
    as_string = tools.call_tool("query_time_entries", {
        "date_from": "2026-08-01", "date_to": "2026-08-31", "billable": "false",
    })
    as_bool = tools.query_time_entries("2026-08-01", "2026-08-31", billable=False)
    assert as_string["total_hours"] == as_bool["total_hours"]
    assert as_string["billable_filter"] is False


def test_coerce_string_numbers(demo_db):
    out = tools.call_tool("capacity_check", {"month": "2026-08", "target_hours": "120"})
    assert out["target_hours"] == 120.0


def test_coerce_leaves_valid_arguments_alone(demo_db):
    assert tools.coerce_arguments(
        "capacity_check", {"month": "2026-08", "target_hours": 160.0}
    ) == {"month": "2026-08", "target_hours": 160.0}


def test_month_is_normalised_in_output(demo_db):
    """Výstup nekopíruje překlepy ze vstupu — `2026-8` vrátí `2026-08`."""
    assert tools.compute_invoice("ACME", "2026-8")["month"] == "2026-08"
    assert tools.capacity_check("2026-8")["month"] == "2026-08"
    # a čísla sedí s kanonickým zápisem
    assert tools.capacity_check("2026-8") == tools.capacity_check("2026-08")


def test_wildcards_in_project_name_are_literal(demo_db):
    """`%` ve vstupu je hledaný znak, ne zástupný symbol pro cokoli."""
    out = tools.call_tool("compute_invoice", {"project": "%", "month": "2026-08"})
    assert "neexistuje" in out["error"]

    out = tools.call_tool("compute_invoice", {"project": "_", "month": "2026-08"})
    assert "neexistuje" in out["error"]


def test_project_lookup_still_matches_substrings(demo_db):
    """Escapování nesmí rozbít běžné částečné hledání."""
    assert tools.compute_invoice("acme", "2026-08")["project"] == "ACME"
    assert tools.compute_invoice("Northwind", "2026-08")["project"] == "NWND"


# --------------------------------------------------------------------------
# Prázdné období — regrese proti vymýšlení čísel
# --------------------------------------------------------------------------

def test_empty_period_carries_note_with_data_range(demo_db):
    """Nula musí být doprovázená větou, že tam data nesahají.

    Regrese: agent dostal na dotaz za listopad nulu, vyložil si ji jako
    „pokračuj v trendu" a vydal vymyšlený rozpad po projektech. Ta čísla se
    pak z paměti konverzace přenesla i do odpovědí o měsících, které v datech
    jsou. Samotná nula je dvojznačná — model nepozná „nepracovalo se" od
    „databáze tam nesahá", takže mu to musí říct nástroj.
    """
    out = tools.capacity_check(month="2026-12")

    assert out["total_hours"] == 0
    assert "note" in out
    assert "nejsou v databázi žádné záznamy" in out["note"]
    assert "2026-" in out["note"]          # rozsah dat, ať ho může model zopakovat


def test_note_appears_only_when_nothing_found(demo_db):
    """Měsíc s daty poznámku nemá — jinak by kalila normální odpovědi."""
    assert "note" not in tools.capacity_check(month="2026-08")
    assert "note" not in tools.summarize_by(
        dimension="project", date_from="2026-08-01", date_to="2026-08-31"
    )


def test_empty_period_note_in_every_aggregating_tool(demo_db):
    """Všechny tři agregující nástroje se chovají stejně."""
    empty = [
        tools.query_time_entries(date_from="2026-12-01", date_to="2026-12-31"),
        tools.summarize_by(dimension="project", date_from="2026-12-01", date_to="2026-12-31"),
        tools.capacity_check(month="2026-12"),
    ]
    assert all("note" in out for out in empty)


def test_invoice_for_month_without_entries_has_note(demo_db):
    """Faktura na nulu je podezřelá vždycky — model má vědět proč."""
    out = tools.compute_invoice(project="ACME", month="2026-12")

    assert out["billable_hours"] == 0
    assert out["amount_excl_vat"] == 0
    assert "note" in out
