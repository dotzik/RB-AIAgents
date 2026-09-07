"""Srovnání modelů a backendů na jedné sadě dotazů.

Otázka „který model na tohle stačí" se nedá zodpovědět dojmem. `bench` proto
pustí stejnou sadu dotazů proti každému zadanému modelu, změří čas a tokeny
a ověří, jestli v odpovědi jsou správné údaje — ty se berou přímo z databáze,
takže kontrola platí i po přegenerování demo dat.

    uv run timeagent bench --models ollama_chat/qwen2.5:14b --repeat 3
    uv run timeagent bench --models ollama_chat/qwen2.5:32b --api-base http://ollama.lan:11434

Výstup je markdownová tabulka — rovnou k vložení do dokumentace.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import agent as agent_mod
from . import llm, tools

# Očekávaná hodnota je číslo nebo kus textu; skupina jsou rovnocenné varianty.
Hodnota = float | str
Skupina = list[Hodnota]


@dataclass
class Case:
    """Dotaz a údaje, které v odpovědi musí zaznít.

    `expected` vrací **skupiny**: z každé skupiny musí v odpovědi zaznít aspoň
    jedna hodnota. Skupina tak pokrývá rovnocenné varianty — u faktury je
    správně částka s DPH i bez ní, u projektu jeho zkratka i celé jméno.
    """

    key: str
    question: str
    expected: Callable[[], list[Skupina]]
    note: str
    sample: Callable[[], str]
    """Jak by správnou odpověď napsal člověk.

    Píše se **dřív než kontrola** a testem se ověřuje, že jí projde. Kdyby se
    očekávaná hodnota odvodila z databázového zápisu (`vyvoj` místo „vývoj",
    `2026-08-28` místo „28. srpna"), vzorová odpověď neprojde a je to vidět
    hned, ne až v tabulce, kde to vypadá jako chyba modelu.
    """

    counter_sample: Callable[[], str]
    """Věrohodně vypadající, ale věcně špatná odpověď. Kontrola ji musí odmítnout."""


def _bench_month() -> str:
    """Měsíc, na kterém se měří — přebitelný přes env kvůli reprodukovatelnosti."""
    return os.environ.get("TIMEAGENT_BENCH_MONTH", "2026-08")


def _previous_month(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    return f"{year}-{mon - 1:02d}" if mon > 1 else f"{year - 1}-12"


def _range(month: str) -> tuple[str, str]:
    return tools._month_bounds(month)


# --------------------------------------------------------------------------
# Očekávané hodnoty — vždy dopočítané z databáze, nikdy zapsané konstantou
# --------------------------------------------------------------------------

def _castka(*, vcetne_dph: bool = False) -> float:
    out = tools.compute_invoice("ACME", _bench_month())
    return out["amount_incl_vat"] if vcetne_dph else out["amount_excl_vat"]


def _invoice_amount() -> list[Skupina]:
    out = tools.compute_invoice("ACME", _bench_month())
    return [[out["amount_excl_vat"], out["amount_incl_vat"]]]


def _invoice_with_vat() -> list[Skupina]:
    return [[tools.compute_invoice("ACME", _bench_month())["amount_incl_vat"]]]


def _capacity() -> list[Skupina]:
    return [[tools.capacity_check(_bench_month(), 160)["total_hours"]]]


def _non_billable() -> list[Skupina]:
    return [[tools.capacity_check(_bench_month(), 160)["non_billable_hours"]]]


def _active_projects() -> list[Skupina]:
    return [[float(tools.list_projects(active_only=True)["count"])]]


def _hourly_rate() -> list[Skupina]:
    projekty = tools.list_projects()["projects"]
    return [[next(p for p in projekty if p["id"] == "GLBX")["hourly_rate"]]]


def _top_client() -> list[Skupina]:
    """Klient s nejvíc hodinami — jméno i identifikátor projdou.

    Obojí se dopočítá z databáze. Dřív tu bylo natvrdo "NWND" jako rovnocenná
    varianta; po přegenerování dat by tím prošla odpověď se špatným klientem.
    """
    first, last = _range(_bench_month())
    top = tools.summarize_by("client", first, last)["groups"][0]
    ids = {
        p["id"]
        for p in tools.list_projects()["projects"]
        if p["client"] == top["bucket"]
    }
    return [[top["bucket"], *sorted(ids)], [top["hours"]]]


# Jak se tag jmenuje v běžné češtině. V databázi je bez diakritiky, protože
# je to identifikátor; ve vzorové odpovědi musí být tak, jak ho napíše člověk.
_TAGY_CESKY = {
    "vyvoj": "vývoj",
    "analyza": "analýza",
    "schuzka": "schůzky",
    "review": "code review",
    "nasazeni": "nasazení",
    "podpora": "podpora",
    "dokumentace": "dokumentace",
}


def _top_tag() -> list[Skupina]:
    first, last = _range(_bench_month())
    top = tools.summarize_by("tag", first, last)["groups"][0]
    return [[top["bucket"]], [top["hours"]]]


_MESICE = [
    "ledna", "února", "března", "dubna", "května", "června",
    "července", "srpna", "září", "října", "listopadu", "prosince",
]


def _date_variants(iso: str) -> Skupina:
    """Tvary, ve kterých může model datum napsat, aniž by chyboval."""
    _, mesic, den = (int(x) for x in iso.split("-"))
    return [
        iso,
        f"{den}. {_MESICE[mesic - 1]}",
        f"{den}.{mesic}.",
        f"{den}. {mesic}.",
    ]


def _busiest_day() -> list[Skupina]:
    """Otázka se ptá na den; hodiny jsou bonus, ne podmínka."""
    first, last = _range(_bench_month())
    top = tools.summarize_by("day", first, last)["groups"][0]
    return [_date_variants(top["bucket"])]


def _quarter_total() -> list[Skupina]:
    month = _bench_month()
    start = _previous_month(_previous_month(month))
    total = tools.query_time_entries(_range(start)[0], _range(month)[1])["total_hours"]
    return [[total]]


def _compare_months() -> list[Skupina]:
    """Za každý z obou měsíců musí zaznít hodiny aspoň jednoho projektu.

    Model si smí vybrat, které projekty vypíchne — netrváme na pořadí ani na
    úplnosti, jen na tom, že čísla jsou z toho správného měsíce. Rozsah je vždy
    celý měsíc, aby očekávané hodnoty seděly s tím, co nástroj vrátí modelu.
    """
    month = _bench_month()
    groups: list[Skupina] = []
    for m in (_previous_month(month), month):
        first, last = _range(m)
        rows = tools.summarize_by("project", first, last)["groups"]
        groups.append([r["hours"] for r in rows] or [0.0])
    return groups


def _finished_project() -> list[Skupina]:
    """Projekt, na kterém se v měřeném měsíci nedělalo. Zkratka i jméno projdou.

    Dopočítá se z databáze, ne konstantou: po přegenerování dat může být
    nečinný jiný projekt a natvrdo zapsaná dvojice by měřila něco jiného.
    """
    first, last = _range(_bench_month())
    aktivni = {
        g["bucket"] for g in tools.summarize_by("project", first, last)["groups"]
    }
    necinne = [p for p in tools.list_projects()["projects"] if p["id"] not in aktivni]
    if not necinne:
        raise RuntimeError(
            "Všechny projekty mají v měřeném měsíci hodiny — dotaz na ukončený "
            "projekt nemá co měřit. Přegeneruj data `timeagent seed`."
        )
    projekt = necinne[0]
    return [[projekt["id"], projekt["name"]]]


def _chained_invoice() -> list[Skupina]:
    """Faktura pro klienta s nejvíc hodinami — druhé volání závisí na prvním."""
    month = _bench_month()
    first, last = _range(month)
    top = tools.summarize_by("client", first, last)["groups"][0]["bucket"]
    projekt = next(p for p in tools.list_projects()["projects"] if p["client"] == top)
    out = tools.compute_invoice(projekt["id"], month)
    return [[out["amount_excl_vat"], out["amount_incl_vat"]]]


def _iso_cesky(iso: str) -> str:
    _, mesic, den = (int(x) for x in iso.split("-"))
    return f"{den}. {_MESICE[mesic - 1]}"


def cases() -> list[Case]:
    """Sada dotazů stoupající obtížnosti.

    Ke každému patří vzorová správná odpověď a protipříklad. Píšou se dřív než
    kontrola a hlídá je `test_kazdy_pripad_ma_konzistentni_vzory` — právě tenhle
    krok chytá metriku, která měří databázový zápis místo odpovědi pro člověka.
    """
    m = _bench_month()
    prev = _previous_month(m)
    return [
        Case(
            "faktura",
            f"Kolik jsem v {m} nafakturoval klientovi Acme?",
            _invoice_amount,
            "jedno volání, přímá odpověď",
            lambda: f"Klientovi Acme Corp jsi naúčtoval {_castka():g} Kč bez DPH.",
            lambda: "Klientovi Acme Corp jsi naúčtoval 12 345 Kč bez DPH.",
        ),
        Case(
            "faktura_dph",
            f"Kolik jsem v {m} naúčtoval Acme včetně DPH?",
            _invoice_with_vat,
            "jedno volání, správná z dvojice částek",
            lambda: f"Včetně DPH to je {_castka(vcetne_dph=True):g} Kč.",
            lambda: f"Včetně DPH to je {_castka():g} Kč.",
        ),
        Case(
            "kapacita",
            f"Kolik hodin jsem odpracoval v {m}?",
            _capacity,
            "jedno volání, jedno číslo",
            lambda: f"V {m} jsi odpracoval {_capacity()[0][0]:g} hodin.",
            lambda: f"V {m} jsi odpracoval 42 hodin.",
        ),
        Case(
            "nefakturovatelne",
            f"Kolik hodin z {m} bylo nefakturovatelných?",
            _non_billable,
            "jedno volání, méně obvyklé pole",
            lambda: f"Nefakturovatelných bylo {_non_billable()[0][0]:g} hodin.",
            lambda: f"Nefakturovatelných bylo {_capacity()[0][0]:g} hodin.",
        ),
        Case(
            "pocet_projektu",
            "Kolik mám aktivních projektů?",
            _active_projects,
            "jedno volání, volitelný parametr",
            lambda: f"Aktivní jsou {_active_projects()[0][0]:g} projekty.",
            lambda: "Aktivních projektů je 9.",
        ),
        Case(
            "sazba",
            "Jakou mám hodinovou sazbu na projektu Globex?",
            _hourly_rate,
            "jedno volání, dohledání v seznamu",
            lambda: f"Na Globexu máš sazbu {_hourly_rate()[0][0]:g} Kč/h.",
            lambda: "Na Globexu máš sazbu 1500 Kč/h.",
        ),
        Case(
            "klient_nejvic",
            f"Na kterém klientovi jsem v {m} strávil nejvíc hodin?",
            _top_client,
            "seskupení, jméno i číslo",
            lambda: (
                f"Nejvíc času sis vybral klient {_top_client()[0][0]} — "
                f"{_top_client()[1][0]:g} hodin."
            ),
            lambda: f"Nejvíc času sis vybral klient {_top_client()[0][0]}.",
        ),
        Case(
            "tag_nejvic",
            f"Jaká činnost mi v {m} zabrala nejvíc času?",
            _top_tag,
            "seskupení podle tagu; odpověď je česky, v databázi je tag bez diakritiky",
            lambda: (
                f"Nejvíc času zabral {_TAGY_CESKY[str(_top_tag()[0][0])]} — "
                f"{_top_tag()[1][0]:g} hodin."
            ),
            lambda: f"Nejvíc času zabralo lyžování — {_top_tag()[1][0]:g} hodin.",
        ),
        Case(
            "nejvytizenejsi_den",
            f"Který den v {m} jsem odpracoval nejvíc hodin?",
            _busiest_day,
            "seskupení podle dne; datum smí být i v běžném českém tvaru",
            lambda: f"Nejvíc jsi odpracoval {_iso_cesky(str(_busiest_day()[0][0]))}.",
            lambda: "Nejvíc jsi odpracoval 1. ledna.",
        ),
        Case(
            "ctvrtleti",
            f"Kolik hodin jsem odpracoval od {_previous_month(prev)} do {m}?",
            _quarter_total,
            "období přes tři měsíce",
            lambda: f"Za to období jsi odpracoval {_quarter_total()[0][0]:g} hodin.",
            lambda: f"Za to období jsi odpracoval {_capacity()[0][0]:g} hodin.",
        ),
        Case(
            "porovnani",
            f"Porovnej {prev} a {m} podle projektů.",
            _compare_months,
            "dvě volání, srovnání období",
            lambda: (
                f"{prev}: {_compare_months()[0][0]:g} hodin, "
                f"{_bench_month()}: {_compare_months()[1][0]:g} hodin."
            ),
            lambda: f"{prev}: 111 hodin, {_bench_month()}: 222 hodin.",
        ),
        Case(
            "ukonceny_projekt",
            "Na kterém projektu jsem přestal pracovat?",
            _finished_project,
            "vyžaduje průzkum, žádný nástroj to neřekne přímo",
            lambda: "Poslední měsíce jsi nedělal na projektu Initech.",
            lambda: "Poslední měsíce jsi nedělal na projektu Globex.",
        ),
        Case(
            "retezeni",
            f"Vystav fakturu klientovi, na kterém jsem v {m} dělal nejvíc.",
            _chained_invoice,
            "dvě volání, druhé závisí na prvním",
            lambda: f"Fakturuj {_chained_invoice()[0][0]:g} Kč bez DPH.",
            lambda: f"Fakturuj {_castka():g} Kč bez DPH.",
        ),
    ]


# --------------------------------------------------------------------------
# Vyhodnocení
# --------------------------------------------------------------------------

_NUMBER_NOISE = re.compile(r"[\s  ]")


def _mentions_number(answer: str, value: float) -> bool:
    """Je číslo v odpovědi? Tolerantně k formátování i zaokrouhlení.

    Hledá se na hranicích číslic, ne jako podřetězec. Bez toho projde `1143`
    jako `143` a `24` jako `4` — metrika by pak propustila odpověď, která se
    liší o řád. Vlevo nesmí předcházet číslice, vpravo nesmí následovat
    číslice ani desetinná část (`143` se nesmí chytit na `143.75`).
    """
    haystack = _NUMBER_NOISE.sub("", answer).replace(",", ".")
    candidates = {f"{value:.2f}", f"{value:.1f}", f"{value:g}", f"{round(value):d}"}
    return any(
        re.search(rf"(?<!\d){re.escape(c)}(?!\d)(?!\.\d)", haystack) for c in candidates
    )


def _bez_diakritiky(text: str) -> str:
    """Tagy jsou v databázi bez diakritiky, model je píše správně česky."""
    rozlozene = unicodedata.normalize("NFD", text.lower())
    return "".join(z for z in rozlozene if not unicodedata.combining(z))


def _mentions(answer: str, value: Hodnota) -> bool:
    if isinstance(value, str):
        return _bez_diakritiky(value) in _bez_diakritiky(answer)
    return _mentions_number(answer, value)


def _passes(answer: str, expected: list[Skupina]) -> bool:
    return all(any(_mentions(answer, v) for v in group) for group in expected)


@dataclass
class Outcome:
    model: str
    case: str
    run: int
    ok: bool
    seconds: float
    iterations: int
    tool_calls: int
    tokens: int
    answer: str


def run_case(
    model: str, case: Case, run: int, max_iterations: int, trace: bool
) -> Outcome:
    expected = case.expected()
    started = time.perf_counter()
    try:
        result = agent_mod.ReactAgent(
            model=model, max_iterations=max_iterations, trace=trace
        ).run(case.question)
    except llm.LLMError as exc:
        return Outcome(model, case.key, run, False, time.perf_counter() - started,
                       0, 0, 0, f"[chyba] {exc}")
    return Outcome(
        model, case.key, run,
        _passes(result.answer, expected),
        time.perf_counter() - started,
        result.iterations, len(result.steps), result.total_tokens, result.answer,
    )


def to_markdown(outcomes: list[Outcome]) -> str:
    """Tabulka: řádek na model, sloupec na případ, v buňce úspěšnost."""
    modely: dict[str, list[Outcome]] = {}
    for o in outcomes:
        modely.setdefault(o.model, []).append(o)

    keys = [c.key for c in cases()]
    opakovani = max((o.run for o in outcomes), default=0) + 1

    lines = [
        "| Model | " + " | ".join(keys) + " | úspěšnost | čas | tokeny |",
        "|---|" + "---|" * (len(keys) + 3),
    ]
    for model, results in modely.items():
        cells = []
        celkem_ok = celkem = 0
        for k in keys:
            pro_case = [o for o in results if o.case == k]
            if not pro_case:
                cells.append("—")
                continue
            ok = sum(o.ok for o in pro_case)
            celkem_ok += ok
            celkem += len(pro_case)
            cells.append(("✅" if ok else "❌") if opakovani == 1
                         else f"{ok}/{len(pro_case)}")
        pct = round(celkem_ok / celkem * 100) if celkem else 0
        lines.append(
            f"| `{model}` | " + " | ".join(cells)
            + f" | **{celkem_ok}/{celkem}** ({pct} %)"
            + f" | {sum(o.seconds for o in results):.0f} s"
            + f" | {sum(o.tokens for o in results)} |"
        )
    return "\n".join(lines)


def run(
    models: list[str],
    *,
    api_base: str | None = None,
    max_iterations: int = agent_mod.MAX_ITERATIONS,
    trace: bool = False,
    repeat: int = 1,
) -> list[Outcome]:
    if api_base:
        os.environ["TIMEAGENT_API_BASE"] = api_base

    outcomes: list[Outcome] = []
    for model in models:
        print(f"\n### {model}" + (f"  ({api_base})" if api_base else ""), flush=True)
        for case in cases():
            pro_case: list[Outcome] = []
            for run_index in range(repeat):
                outcome = run_case(model, case, run_index, max_iterations, trace)
                outcomes.append(outcome)
                pro_case.append(outcome)
                if not outcome.ok:
                    print(f"    [{case.key} #{run_index + 1}] {outcome.answer[:160]}",
                          flush=True)
            ok = sum(o.ok for o in pro_case)
            print(
                f"  {case.key:<20} {ok}/{repeat}  "
                f"{sum(o.seconds for o in pro_case):6.1f} s  "
                f"{sum(o.tokens for o in pro_case)} tokenů",
                flush=True,
            )
    return outcomes


def rescore(rows: list[dict[str, Any]]) -> list[Outcome]:
    """Obodovat uložené odpovědi znovu, aktuální kontrolou.

    Když se opraví vyhodnocení, není důvod pouštět modely znovu — odpovědi už
    máme z `--json`. Jeden běh přes všechny backendy stojí hodiny, přehodnocení
    vteřiny. Případy, které mezitím ze sady zmizely, se přeskočí.
    """
    podle_klice = {c.key: c for c in cases()}
    out: list[Outcome] = []
    for row in rows:
        case = podle_klice.get(row.get("case", ""))
        if case is None:
            continue
        odpoved = row.get("answer", "")
        out.append(Outcome(
            row["model"], case.key, row.get("run", 0),
            _passes(odpoved, case.expected()),
            row.get("seconds", 0.0), row.get("iterations", 0),
            row.get("tool_calls", 0), row.get("tokens", 0), odpoved,
        ))
    return out


def as_rows(outcomes: list[Outcome]) -> list[dict[str, Any]]:
    return [
        {
            "model": o.model, "case": o.case, "run": o.run, "ok": o.ok,
            "seconds": round(o.seconds, 1), "iterations": o.iterations,
            "tool_calls": o.tool_calls, "tokens": o.tokens, "answer": o.answer,
        }
        for o in outcomes
    ]
