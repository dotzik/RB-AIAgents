# timeagent

Agent nad databází výkazů odpracovaného času. Odpovídá na dotazy typu „kolik jsem
v srpnu naúčtoval Acme" tak, že si potřebné údaje vytáhne nástroji ze SQLite
a teprve z nich sestaví odpověď.

Vzniklo jako HW1 kurzu AI Agents. Zadání: *napiš Python skript, který zavolá LLM
API, použije nástroj a vrátí odpověď zpět LLM.*

```
$ uv run timeagent ask "Kolik jsem v 2026-08 nafakturoval klientovi Acme?"

--- krok 1 ---
  nástroj: compute_invoice(project='Acme', month='2026-08')
  výsledek: {"project": "ACME", "client": "Acme Corp", "billable_hours": 47.0,
             "amount_excl_vat": 70500.0, "amount_incl_vat": 85305.0, ...}
--- krok 2 ---
  hotovo — model už nepotřebuje nástroj

========================================================================
V srpnu 2026 jsi nafakturoval klientovi Acme 47 hodin práce za celkovou
částku 85 305 CZK, z toho 70 500 CZK bez DPH a 14 805 CZK DPH.
========================================================================
```

## Rychlý start

Potřebuješ [uv](https://docs.astral.sh/uv/), Python 3.12+ a běžící model —
lokálně přes [Ollamu](https://ollama.com/) nebo klíč ke cloudovému API.

```bash
cd HW1
cp .env.example .env
uv sync

ollama pull qwen2.5:14b        # výchozí model — v měření 39/39, viz docs/mereni.md
uv run timeagent seed --months 21   # demo data: leden 2025 až dnešek
uv run timeagent ask "Kolik hodin jsem odpracoval v 2026-08?"
```

Podrobnosti v [docs/instalace.md](docs/instalace.md).

## Dokumentace

| Dokument | Obsah |
|---|---|
| [docs/instalace.md](docs/instalace.md) | instalace, konfigurace, proměnné prostředí, databáze |
| [docs/modely.md](docs/modely.md) | jak rozchodit model — Ollama, LM Studio, DGX Spark, Anthropic, OpenAI |
| [docs/cli.md](docs/cli.md) | referenční popis všech příkazů a přepínačů |
| [docs/nastroje.md](docs/nastroje.md) | reference pěti nástrojů: vstupy, výstupy, chyby; jak přidat vlastní |
| [docs/architektura.md](docs/architektura.md) | jak agent funguje uvnitř — smyčka, pojistky, vrstvy, bezpečnostní návrh |
| [docs/testy.md](docs/testy.md) | co se testuje, podvržené LLM, jak psát nové testy |
| [docs/mereni.md](docs/mereni.md) | naměřené srovnání osmi konfigurací, metodika, poznatky |

## Co agent umí

Pět nástrojů nad dvěma tabulkami (`projects`, `time_entries`):

| Nástroj | K čemu |
|---|---|
| `list_projects` | projekty, klienti, hodinové sazby |
| `query_time_entries` | součet hodin za období, volitelně jeden projekt |
| `summarize_by` | rozpad hodin podle projektu, klienta, dne, týdne, měsíce, tagu |
| `compute_invoice` | fakturační podklad — hodiny × sazba, základ, DPH, celkem |
| `capacity_check` | odpracováno vs. cíl měsíce |

Model si SQL nepíše ani ho nevidí; volí jen nástroj a typované parametry.
Zdůvodnění v [docs/architektura.md](docs/architektura.md).

## Data

Repozitář neobsahuje žádná data. `timeagent seed` vygeneruje deterministický
dataset s fiktivními klienty; kdo má Clockify, může si stejným schématem
naimportovat vlastní výkazy (`timeagent import`). Soubory `*.sqlite` a `.env`
jsou v `.gitignore`.

## Vývoj

```bash
uv run pytest -q          # 106 testů, běží bez API klíče i bez modelu
uvx ruff check src tests  # linter
```

```
src/timeagent/
  db.py                  schéma SQLite, read-only spojení pro nástroje
  seed.py                generátor demo dat
  tools.py               nástroje, JSON schémata, registr
  llm.py                 volání modelu přes LiteLLM
  agent.py               ReAct smyčka
  bench.py               srovnání modelů na pevné sadě dotazů
  cli.py                 příkazová řádka
  importers/clockify.py  volitelný import reálných dat
tests/                   106 testů, podrobnosti v docs/testy.md
```

`tools.py` a `db.py` neimportují nic z LiteLLM ani ze SDK poskytovatele — dají se
proto v navazujícím úkolu vystavit jako MCP server beze změny.
