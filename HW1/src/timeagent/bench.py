"""Srovnání modelů a backendů na jedné sadě dotazů.

Otázka „který model na tohle stačí" se nedá zodpovědět dojmem. `bench` proto
pustí stejné tři dotazy proti každému zadanému modelu, změří čas a tokeny
a ověří, jestli v odpovědi jsou správná čísla — ta se berou přímo z databáze,
takže kontrola platí i po přegenerování demo dat.

    uv run timeagent bench --models ollama/llama3.2:3b,ollama/qwen2.5:7b
    uv run timeagent bench --models ollama/qwen2.5:32b --api-base http://192.168.0.24:11434

Výstup je markdownová tabulka — rovnou k vložení do README.
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import agent as agent_mod
from . import llm, tools


@dataclass
class Case:
    """Dotaz a čísla, která v odpovědi musí zaznít.

    `expected` vrací **skupiny** hodnot: z každé skupiny musí v odpovědi zaznít
    aspoň jedna. Skupina se tak dá použít pro rovnocenné varianty — u faktury
    je správně částka s DPH i bez ní, jen o ni musí jít.
    """

    key: str
    question: str
    expected: Callable[[], list[list[float]]]
    note: str


def _invoice_acme() -> list[list[float]]:
    """Otázka se ptá na částku — hodiny jsou bonus, ne podmínka.

    Správná odpověď je částka s DPH i bez ní; model si vybere, kterou uvede.
    """
    out = tools.compute_invoice("ACME", _bench_month())
    return [[out["amount_excl_vat"], out["amount_incl_vat"]]]


def _capacity() -> list[list[float]]:
    out = tools.capacity_check(_bench_month(), 160)
    return [[out["total_hours"]]]


def _compare() -> list[list[float]]:
    """Za každý z obou měsíců musí zaznít hodiny aspoň jednoho projektu.

    Model si může vybrat, které projekty vypíchne — netrváme na pořadí ani na
    úplnosti, jen na tom, že čísla jsou z toho správného měsíce. Rozsah je vždy
    celý měsíc, aby očekávané hodnoty seděly s tím, co nástroj vrátí modelu.
    """
    month = _bench_month()
    prev = _previous_month(month)
    groups: list[list[float]] = []
    for m in (prev, month):
        first, last = tools._month_bounds(m)
        rows = tools.summarize_by("project", first, last)["groups"]
        groups.append([r["hours"] for r in rows] or [0.0])
    return groups


def _bench_month() -> str:
    """Měsíc, na kterém se měří — přebitelný přes env kvůli reprodukovatelnosti."""
    return os.environ.get("TIMEAGENT_BENCH_MONTH", "2026-08")


def _previous_month(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    return f"{year}-{mon - 1:02d}" if mon > 1 else f"{year - 1}-12"


def cases() -> list[Case]:
    month = _bench_month()
    prev = _previous_month(month)
    return [
        Case(
            "faktura",
            f"Kolik jsem v {month} nafakturoval klientovi Acme?",
            _invoice_acme,
            "jeden nástroj, přímá odpověď",
        ),
        Case(
            "kapacita",
            f"Kolik hodin jsem odpracoval v {month} a chybělo mi něco do 160 hodin?",
            _capacity,
            "jeden nástroj, dvě čísla v odpovědi",
        ),
        Case(
            "porovnani",
            # Oba měsíce výslovně: „předchozí měsíc" by bylo dvojznačné vůči dnešku.
            f"Porovnej {prev} a {month} podle projektů.",
            _compare,
            "dvě volání, srovnání období",
        ),
    ]


_NUMBER_NOISE = re.compile(r"[\s  ]")


def _mentions(answer: str, value: float) -> bool:
    """Je číslo v odpovědi? Tolerantně k formátování i zaokrouhlení."""
    haystack = _NUMBER_NOISE.sub("", answer).replace(",", ".")
    candidates = {f"{value:.2f}", f"{value:.1f}", f"{value:g}", f"{round(value):d}"}
    return any(c in haystack for c in candidates)


@dataclass
class Outcome:
    model: str
    case: str
    ok: bool
    seconds: float
    iterations: int
    tool_calls: int
    tokens: int
    answer: str


def run_case(model: str, case: Case, max_iterations: int, trace: bool) -> Outcome:
    expected = case.expected()
    started = time.perf_counter()
    try:
        result = agent_mod.ReactAgent(
            model=model, max_iterations=max_iterations, trace=trace
        ).run(case.question)
        answer = result.answer
        iterations, tool_calls = result.iterations, len(result.steps)
        tokens = result.total_tokens
    except llm.LLMError as exc:
        return Outcome(model, case.key, False, time.perf_counter() - started,
                       0, 0, 0, f"[chyba] {exc}")
    return Outcome(
        model, case.key,
        all(any(_mentions(answer, v) for v in group) for group in expected),
        time.perf_counter() - started,
        iterations, tool_calls, tokens, answer,
    )


def to_markdown(outcomes: list[Outcome]) -> str:
    by_model: dict[str, list[Outcome]] = {}
    for o in outcomes:
        by_model.setdefault(o.model, []).append(o)

    keys = [c.key for c in cases()]
    header = "| Model | " + " | ".join(keys) + " | čas celkem | tokeny |"
    divider = "|---|" + "---|" * (len(keys) + 2)
    lines = [header, divider]
    for model, results in by_model.items():
        got = {o.case: o for o in results}
        cells = ["✅" if got[k].ok else "❌" if k in got else "—" for k in keys]
        total_s = sum(o.seconds for o in results)
        total_t = sum(o.tokens for o in results)
        lines.append(
            f"| `{model}` | " + " | ".join(cells)
            + f" | {total_s:.0f} s | {total_t} |"
        )
    return "\n".join(lines)


def run(
    models: list[str],
    *,
    api_base: str | None = None,
    max_iterations: int = agent_mod.MAX_ITERATIONS,
    trace: bool = False,
) -> list[Outcome]:
    if api_base:
        os.environ["TIMEAGENT_API_BASE"] = api_base

    outcomes: list[Outcome] = []
    for model in models:
        print(f"\n### {model}" + (f"  ({api_base})" if api_base else ""), flush=True)
        for case in cases():
            outcome = run_case(model, case, max_iterations, trace)
            outcomes.append(outcome)
            mark = "ok " if outcome.ok else "CHYBA"
            print(
                f"  {case.key:<10} {mark:<6} {outcome.seconds:6.1f} s  "
                f"{outcome.iterations} kroků, {outcome.tokens} tokenů",
                flush=True,
            )
            if not outcome.ok:
                print(f"    odpověď: {outcome.answer[:200]}", flush=True)
    return outcomes


def as_rows(outcomes: list[Outcome]) -> list[dict[str, Any]]:
    return [
        {
            "model": o.model, "case": o.case, "ok": o.ok,
            "seconds": round(o.seconds, 1), "iterations": o.iterations,
            "tool_calls": o.tool_calls, "tokens": o.tokens, "answer": o.answer,
        }
        for o in outcomes
    ]
