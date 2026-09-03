"""Testy importu z Clockify — jen čisté funkce, bez volání API."""
from __future__ import annotations

import pytest

from timeagent.importers import clockify


@pytest.mark.parametrize(
    ("trvani", "hodin"),
    [
        ("PT1H", 1.0),
        ("PT30M", 0.5),
        ("PT1H30M", 1.5),
        ("PT8H15M", 8.25),
        ("PT45S", 0.0125),
        ("P1DT2H", 26.0),
        ("PT0S", 0.0),
    ],
)
def test_parse_duration(trvani, hodin):
    assert clockify.parse_duration(trvani) == pytest.approx(hodin)


def test_parse_duration_of_running_entry():
    """Běžící záznam trvání nemá — nesmí spadnout, jen vrátit nulu."""
    assert clockify.parse_duration(None) == 0.0
    assert clockify.parse_duration("") == 0.0


def test_parse_duration_of_garbage():
    assert clockify.parse_duration("tohle není ISO trvání") == 0.0


def test_month_bounds_covers_whole_month():
    start, end = clockify._month_bounds("2026-02")
    assert (start.year, start.month, start.day) == (2026, 2, 1)
    assert end.day == 28          # 2026 není přestupný
    assert (end.hour, end.minute, end.second) == (23, 59, 59)


def test_month_bounds_rejects_bad_format():
    with pytest.raises(clockify.ClockifyError, match="YYYY-MM"):
        clockify._month_bounds("únor 2026")


def test_rate_is_converted_from_cents():
    """Clockify drží sazbu v haléřích; bez sazby se použije záloha."""
    assert clockify._rate_of({"hourlyRate": {"amount": 150000}}, 0.0) == 1500.0
    assert clockify._rate_of({}, 1234.0) == 1234.0
    assert clockify._rate_of({"hourlyRate": None}, 999.0) == 999.0


def test_currency_defaults_to_czk():
    assert clockify._currency_of({"hourlyRate": {"currency": "EUR"}}) == "EUR"
    assert clockify._currency_of({}) == "CZK"
