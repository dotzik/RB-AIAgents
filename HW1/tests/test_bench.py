"""Testy vyhodnocení benchmarku — bez volání modelu."""
from __future__ import annotations

import pytest

from timeagent import bench


@pytest.fixture(autouse=True)
def pevny_mesic(monkeypatch):
    """Všechny testy měří nad srpnem, ať nezávisí na dnešku."""
    monkeypatch.setenv("TIMEAGENT_BENCH_MONTH", "2026-08")


# --------------------------------------------------------------------------
# Rozpoznávání hodnot v odpovědi
# --------------------------------------------------------------------------

def test_mentions_tolerates_formatting():
    for written in ["93000", "93 000", "93 000,00", "93000.00", "93000.0 Kč"]:
        assert bench._mentions(f"Naúčtoval jsi {written} bez DPH.", 93000.0)


def test_mentions_rejects_other_numbers():
    assert not bench._mentions("Naúčtoval jsi 12 345 Kč.", 93000.0)


def test_mentions_rejects_substring_matches():
    """Správné číslo uvnitř jiného čísla není správná odpověď.

    Bez hranic číslic tyhle případy metrikou projdou — ověřeno na reálných
    odpovědích: „1143 hodin" místo 143, „24 projektů" místo 4.
    """
    assert not bench._mentions("Odpracoval jsi 1143 hodin.", 143.0)
    assert not bench._mentions("Aktivních projektů je 24.", 4.0)
    assert not bench._mentions("Sazba je 21800 Kč/h.", 1800.0)
    assert not bench._mentions("Bylo to 132.55 hodin.", 32.5)
    assert not bench._mentions("NWND, 150.5 hodin.", 50.5)


def test_mentions_still_accepts_number_at_boundaries():
    """Hranice nesmí zabít legitimní formáty."""
    assert bench._mentions("Odpracoval jsi 143 hodin.", 143.0)
    assert bench._mentions("(143)", 143.0)
    assert bench._mentions("143,00 h", 143.0)
    assert bench._mentions("celkem 143.", 143.0)


def test_mentions_handles_decimals():
    assert bench._mentions("Odpracoval jsi 179,5 hodiny.", 179.5)
    assert bench._mentions("Odpracoval jsi 179.5 hodiny.", 179.5)


def test_mentions_matches_text_case_insensitively():
    """Některé odpovědi jsou jména, ne čísla."""
    assert bench._mentions("Přestal jsi dělat na projektu Initech.", "initech")
    assert bench._mentions("Nejvíc hodin má NWND.", "nwnd")
    assert not bench._mentions("Nejvíc hodin má ACME.", "initech")


# --------------------------------------------------------------------------
# Očekávané hodnoty se čtou z databáze
# --------------------------------------------------------------------------

def test_expected_values_come_from_database(demo_db):
    (amount_group,) = bench._invoice_amount()
    assert len(amount_group) == 2                 # bez DPH i s DPH
    assert amount_group[1] > amount_group[0] > 0
    assert bench._capacity()[0][0] > 0
    assert len(bench._compare_months()) == 2


def test_invoice_accepts_amount_with_or_without_vat(demo_db):
    (amount_group,) = bench._invoice_amount()
    for amount in amount_group:
        assert bench._passes(f"Nafakturoval jsi {amount:g} Kč.", bench._invoice_amount())


def test_invoice_with_vat_rejects_amount_without_vat(demo_db):
    """Otázka na částku s DPH má jen jednu správnou odpověď."""
    excl, incl = bench._invoice_amount()[0]
    assert bench._passes(f"Celkem {incl:g} Kč.", bench._invoice_with_vat())
    assert not bench._passes(f"Celkem {excl:g} Kč.", bench._invoice_with_vat())


def test_invoice_rejects_answer_without_amount(demo_db):
    assert not bench._passes("Nafakturoval jsi 62 hodin.", bench._invoice_amount())


def test_compare_accepts_any_project_from_each_month(demo_db):
    july, august = bench._compare_months()
    answer = f"Červenec: {min(july):g} hodin. Srpen: {min(august):g} hodin."
    assert bench._passes(answer, bench._compare_months())


def test_compare_rejects_numbers_from_wrong_month(demo_db):
    july, _ = bench._compare_months()
    assert not bench._passes(
        f"Červenec: {july[0]:g} hodin. Srpen: 9999 hodin.", bench._compare_months()
    )


def test_compare_covers_whole_month_not_first_28_days(demo_db):
    """Očekávané hodnoty musí sedět s tím, co nástroj vrátí modelu.

    Regrese: dřív se rozsah počítal jako 1.–28., takže věcně správné odpovědi
    za celý měsíc padaly jako chybné.
    """
    from timeagent import tools

    july, august = bench._compare_months()
    for month, expected in (("2026-07", july), ("2026-08", august)):
        first, last = tools._month_bounds(month)
        rows = tools.summarize_by("project", first, last)["groups"]
        assert sorted(expected) == sorted(r["hours"] for r in rows)

    partial = tools.summarize_by("project", "2026-08-01", "2026-08-28")["groups"]
    assert sorted(august) != sorted(r["hours"] for r in partial)


def test_top_client_wants_name_and_number(demo_db):
    """U seskupení musí zaznít jméno skupiny i hodnota."""
    jmena, hodiny = bench._top_client()
    assert bench._passes(
        f"Nejvíc na {jmena[0]}, {hodiny[0]:g} hodin.", bench._top_client()
    )
    assert not bench._passes(f"Nejvíc na {jmena[0]}.", bench._top_client())


def test_chained_invoice_targets_the_busiest_client(demo_db):
    """Řetězený případ počítá fakturu tomu klientovi, kdo má nejvíc hodin."""
    from timeagent import tools

    top = tools.summarize_by("client", "2026-08-01", "2026-08-31")["groups"][0]["bucket"]
    projekt = next(p for p in tools.list_projects()["projects"] if p["client"] == top)
    ocekavane = bench._chained_invoice()[0]
    assert tools.compute_invoice(projekt["id"], "2026-08")["amount_excl_vat"] in ocekavane


# --------------------------------------------------------------------------
# Sada dotazů a tabulka
# --------------------------------------------------------------------------

def test_case_keys_are_unique(demo_db):
    keys = [c.key for c in bench.cases()]
    assert len(keys) == len(set(keys))


def test_every_case_has_expected_values(demo_db):
    """Případ bez očekávaných hodnot by tiše procházel vždy."""
    for case in bench.cases():
        groups = case.expected()
        assert groups, case.key
        assert all(group for group in groups), case.key


def test_comparison_question_names_both_months(demo_db):
    """Zadání nesmí být dvojznačné vůči dnešnímu datu.

    Regrese: otázka zněla „předchozí měsíc", což je vůči dnešku něco jiného než
    měsíc, na kterém se měří — model pak správně namítl rozpor a byl za to
    ohodnocen jako chybující.
    """
    question = next(c.question for c in bench.cases() if c.key == "porovnani")
    assert "2026-07" in question
    assert "2026-08" in question
    assert "předchozí měsíc" not in question


def test_previous_month_crosses_year_boundary():
    assert bench._previous_month("2026-01") == "2025-12"
    assert bench._previous_month("2026-08") == "2026-07"


def _outcome(case, run, ok):
    return bench.Outcome("m1", case, run, ok, 1.0, 2, 1, 100, "…")


def test_markdown_single_run(demo_db):
    keys = [c.key for c in bench.cases()]
    outcomes = [_outcome(k, 0, i % 2 == 0) for i, k in enumerate(keys)]
    radek = bench.to_markdown(outcomes).splitlines()[2]

    assert "`m1`" in radek
    assert "✅" in radek and "❌" in radek
    assert f"{sum(i % 2 == 0 for i in range(len(keys)))}/{len(keys)}" in radek


def test_markdown_shows_ratio_when_repeated(demo_db):
    outcomes = [
        _outcome("faktura", 0, True),
        _outcome("faktura", 1, False),
        _outcome("faktura", 2, True),
    ]
    radek = bench.to_markdown(outcomes).splitlines()[2]

    assert "2/3" in radek        # dvakrát ze tří u toho případu
    assert "(67 %)" in radek     # a totéž jako celková úspěšnost


def test_rows_are_serialisable(demo_db):
    import json

    rows = bench.as_rows([_outcome("faktura", 0, True)])
    assert json.loads(json.dumps(rows))[0]["run"] == 0


def test_mentions_ignores_diacritics():
    """Tagy jsou v databázi bez diakritiky, model je píše správně česky."""
    assert bench._mentions("Nejvíc času zabral vývoj.", "vyvoj")
    assert bench._mentions("Nejvíc času zabrala analýza.", "analyza")
    assert bench._mentions("Šlo o nasazení.", "nasazeni")
    assert not bench._mentions("Nejvíc času zabral vývoj.", "schuzka")


def test_date_is_accepted_in_czech_wording(demo_db):
    """Model smí datum napsat česky, nemusí opisovat ISO tvar z databáze."""
    iso = str(bench._busiest_day()[0][0])
    den, mesic = int(iso[8:10]), int(iso[5:7])

    zapisy = (
        iso,
        f"{den}. {bench._MESICE[mesic - 1]} 2026",
        f"{den}.{mesic}.2026",
        f"{den}. {mesic}. 2026",
    )
    for zapis in zapisy:
        assert bench._passes(f"Nejvíc jsi odpracoval {zapis}.", bench._busiest_day()), zapis


def test_date_rejects_wrong_day(demo_db):
    assert not bench._passes(
        "Nejvíc jsi odpracoval 1. ledna 2026.", bench._busiest_day()
    )


# --------------------------------------------------------------------------
# Pojistka proti chybné metrice
# --------------------------------------------------------------------------

def test_kazdy_pripad_ma_konzistentni_vzory(demo_db):
    """Vzorová odpověď musí projít a protipříklad neprojít.

    Tohle je pojistka proti nejčastější vadě benchmarku: očekávaná hodnota se
    odvodí z databázového zápisu (`vyvoj`, `2026-08-28`) místo z toho, jak
    odpověď napíše člověk (`vývoj`, `28. srpna`). Pak vypadá jako chyba modelu
    něco, co je chyba měření. Druhá polovina hlídá opak — metriku tak měkkou,
    že projde i špatná odpověď.
    """
    for case in bench.cases():
        expected = case.expected()
        assert bench._passes(case.sample(), expected), (
            f"{case.key}: vzorová správná odpověď neprošla kontrolou — "
            f"{case.sample()!r}"
        )
        assert not bench._passes(case.counter_sample(), expected), (
            f"{case.key}: kontrolou prošla i špatná odpověď — "
            f"{case.counter_sample()!r}"
        )


def test_rescore_reuses_stored_answers(demo_db):
    """Uložené odpovědi jdou obodovat znovu, bez opakovaného volání modelu."""
    rows = [
        {"model": "m1", "case": "kapacita", "run": 0, "ok": False,
         "seconds": 1.0, "iterations": 2, "tool_calls": 1, "tokens": 10,
         "answer": f"Odpracoval jsi {bench._capacity()[0][0]:g} hodin."},
    ]
    prehodnocene = bench.rescore(rows)

    assert len(prehodnocene) == 1
    assert prehodnocene[0].ok is True          # dřív False, teď kontrola projde
    assert prehodnocene[0].model == "m1"
    assert prehodnocene[0].seconds == 1.0      # měřené hodnoty zůstávají


def test_rescore_skips_unknown_cases(demo_db):
    rows = [{"model": "m1", "case": "uz_neexistuje", "run": 0, "ok": True,
             "seconds": 1.0, "iterations": 1, "tool_calls": 0, "tokens": 5,
             "answer": "cokoli"}]
    assert bench.rescore(rows) == []
