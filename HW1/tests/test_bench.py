"""Testy vyhodnocení benchmarku — bez volání modelu."""
from __future__ import annotations

from timeagent import bench


def test_mentions_tolerates_formatting():
    # 93000.0 zapsané různě, jak to modely píšou
    for written in ["93000", "93 000", "93 000,00", "93000.00", "93000.0 Kč"]:
        assert bench._mentions(f"Naúčtoval jsi {written} bez DPH.", 93000.0)


def test_mentions_rejects_other_numbers():
    assert not bench._mentions("Naúčtoval jsi 12 345 Kč.", 93000.0)


def test_mentions_handles_decimals():
    assert bench._mentions("Odpracoval jsi 179,5 hodiny.", 179.5)
    assert bench._mentions("Odpracoval jsi 179.5 hodiny.", 179.5)


def test_expected_values_come_from_database(demo_db, monkeypatch):
    """Očekávaná čísla se čtou z databáze, ne z konstant v testu."""
    monkeypatch.setenv("TIMEAGENT_BENCH_MONTH", "2026-08")
    (amount_group,) = bench._invoice_acme()
    # ve skupině je částka bez DPH i s DPH — obojí je správná odpověď
    assert len(amount_group) == 2
    assert amount_group[1] > amount_group[0] > 0
    assert bench._capacity()[0][0] > 0
    assert len(bench._compare()) == 2


def _passes(answer: str, expected) -> bool:
    return all(any(bench._mentions(answer, v) for v in group) for group in expected)


def test_invoice_accepts_amount_with_or_without_vat(demo_db, monkeypatch):
    """Odpověď s DPH i bez DPH musí projít — obojí je věcně správně."""
    monkeypatch.setenv("TIMEAGENT_BENCH_MONTH", "2026-08")
    (amount_group,) = bench._invoice_acme()
    for amount in amount_group:
        answer = f"Nafakturoval jsi {amount:g} Kč."
        assert _passes(answer, bench._invoice_acme()), f"neprošla částka {amount}"


def test_invoice_rejects_answer_without_amount(demo_db, monkeypatch):
    monkeypatch.setenv("TIMEAGENT_BENCH_MONTH", "2026-08")
    assert not _passes("Nafakturoval jsi 62 hodin.", bench._invoice_acme())


def test_compare_accepts_any_project_from_each_month(demo_db, monkeypatch):
    """Model si smí vybrat, které projekty vypíchne — jen musí být z těch měsíců."""
    monkeypatch.setenv("TIMEAGENT_BENCH_MONTH", "2026-08")
    july, august = bench._compare()
    # nejmenší projekt v každém měsíci, tedy ne ten první v pořadí
    answer = f"Červenec: {min(july):g} hodin. Srpen: {min(august):g} hodin."
    assert _passes(answer, bench._compare())


def test_compare_rejects_numbers_from_wrong_month(demo_db, monkeypatch):
    monkeypatch.setenv("TIMEAGENT_BENCH_MONTH", "2026-08")
    july, _ = bench._compare()
    answer = f"Červenec: {july[0]:g} hodin. Srpen: 9999 hodin."
    assert not _passes(answer, bench._compare())


def test_markdown_table_shape(demo_db):
    outcomes = [
        bench.Outcome("m1", "faktura", True, 1.0, 2, 1, 100, "ok"),
        bench.Outcome("m1", "kapacita", False, 2.0, 3, 2, 200, "špatně"),
        bench.Outcome("m1", "porovnani", True, 3.0, 4, 2, 300, "ok"),
    ]
    table = bench.to_markdown(outcomes)
    lines = table.splitlines()
    assert lines[0].startswith("| Model |")
    assert "`m1`" in lines[2]
    assert lines[2].count("✅") == 2
    assert lines[2].count("❌") == 1
    assert "600" in lines[2]  # součet tokenů


def test_rows_are_serialisable(demo_db):
    import json

    rows = bench.as_rows([bench.Outcome("m", "faktura", True, 1.5, 2, 1, 10, "ok")])
    assert json.loads(json.dumps(rows))[0]["model"] == "m"


def test_compare_covers_whole_month_not_first_28_days(demo_db, monkeypatch):
    """Očekávané hodnoty musí sedět s tím, co nástroj vrátí modelu.

    Regrese: dřív se rozsah počítal jako 1.–28., takže věcně správné odpovědi
    za celý měsíc padaly jako chybné.
    """
    from timeagent import tools

    monkeypatch.setenv("TIMEAGENT_BENCH_MONTH", "2026-08")
    july, august = bench._compare()

    for month, expected in (("2026-07", july), ("2026-08", august)):
        first, last = tools._month_bounds(month)
        rows = tools.summarize_by("project", first, last)["groups"]
        assert sorted(expected) == sorted(r["hours"] for r in rows)

    # a doopravdy jde o víc než prvních 28 dní
    partial = tools.summarize_by("project", "2026-08-01", "2026-08-28")["groups"]
    assert sorted(august) != sorted(r["hours"] for r in partial)


def test_comparison_question_names_both_months(demo_db, monkeypatch):
    """Zadání nesmí být dvojznačné vůči dnešnímu datu.

    Regrese: otázka zněla „předchozí měsíc", což je vůči dnešku něco jiného než
    měsíc, na kterém se měří — model pak správně namítl rozpor a byl za to
    ohodnocen jako chybující.
    """
    monkeypatch.setenv("TIMEAGENT_BENCH_MONTH", "2026-08")
    question = next(c.question for c in bench.cases() if c.key == "porovnani")
    assert "2026-07" in question
    assert "2026-08" in question
    assert "předchozí měsíc" not in question


def test_previous_month_crosses_year_boundary():
    assert bench._previous_month("2026-01") == "2025-12"
    assert bench._previous_month("2026-08") == "2026-07"
