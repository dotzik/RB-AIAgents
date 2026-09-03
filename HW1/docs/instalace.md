# Instalace a konfigurace

## Požadavky

| | |
|---|---|
| Python | 3.12 nebo novější |
| Správce balíčků | [uv](https://docs.astral.sh/uv/) |
| Model | lokální (Ollama / LM Studio) nebo klíč ke cloudovému API |

Vlastní projekt nemá žádné systémové závislosti nad rámec Pythonu. SQLite je
součástí standardní knihovny.

## Instalace

```bash
git clone <url-repozitáře>
cd RB-AIAgents/HW1
uv sync
```

`uv sync` vytvoří `.venv` a nainstaluje závislosti podle `uv.lock`, takže
dostaneš přesně ty verze, na kterých bylo měřeno.

Závislosti jsou tři: `litellm` (jednotné volání poskytovatelů), `python-dotenv`
(načtení `.env`) a `httpx` (import z Clockify). Vývojově navíc `pytest`.

## Konfigurace

Konfigurace je celá v `.env` v adresáři `HW1`. Zkopíruj si šablonu:

```bash
cp .env.example .env
```

### Proměnné prostředí

| Proměnná | Výchozí | K čemu |
|---|---|---|
| `TIMEAGENT_MODEL` | `ollama/qwen2.5:14b` | model ve tvaru `poskytovatel/název` |
| `TIMEAGENT_API_BASE` | — | endpoint pro lokální a self-hosted modely |
| `TIMEAGENT_DB` | `data/timeagent.sqlite` | cesta k databázi |
| `TIMEAGENT_BENCH_MONTH` | `2026-08` | měsíc, na kterém měří `timeagent bench` |
| `ANTHROPIC_API_KEY` | — | klíč pro modely `anthropic/*` |
| `ANTHROPIC_WORKSPACE_ID` | — | jen pro klíče navázané na identitu |
| `OPENAI_API_KEY` | — | klíč pro `openai/*`; u LM Studia stačí libovolná hodnota |
| `OPENROUTER_API_KEY` | — | klíč pro `openrouter/*` |
| `CLOCKIFY_API_KEY` | — | volitelný import reálných dat |
| `CLOCKIFY_WORKSPACE_ID` | výchozí workspace | volitelné upřesnění |
| `CLOCKIFY_DEFAULT_RATE` | `0` | sazba pro projekty, které ji v Clockify nemají |

Nastavení modelu a endpointu podle konkrétního backendu popisuje
[modely.md](modely.md).

### Pozor na kolize názvů

`TIMEAGENT_MODEL` a `TIMEAGENT_API_BASE` mají prefix záměrně. Obecné názvy
`MODEL` a `API_BASE` se čtou taky, ale až jako záloha — jsou natolik obecné,
že je člověk může mít nastavené globálně pro něco jiného, a pak by tiše
přebily `.env`.

### Systémové proměnné mají přednost před `.env`

`python-dotenv` nepřepisuje to, co už v prostředí je. Když máš `ANTHROPIC_API_KEY`
nastavený ve Windows (nebo v shellu), hodnota z `.env` se ignoruje. Ověřit si to
jde takhle:

```powershell
Get-ChildItem Env: | Where-Object Name -match 'TIMEAGENT|ANTHROPIC'   # PowerShell
```

```bash
env | grep -E 'TIMEAGENT|ANTHROPIC'                                    # bash
```

## Databáze

Agent nad prázdnou databází nefunguje — nástroje vrátí chybu s návodem.

### Demo data

```bash
uv run timeagent seed
```

Vygeneruje šest měsíců výkazů pro pět fiktivních projektů (Acme, Northwind,
Globex, Initech, interní). Generátor je deterministický — stejný příkaz dá vždy
stejná čísla, takže ukázky v dokumentaci i testy sedí. Volitelně
`--months` a `--rng-seed`, viz [cli.md](cli.md).

Data odpovídají úvazku kolem 150–180 hodin měsíčně. Jeden projekt (`INIT`) je
záměrně ukončený tři měsíce zpět, aby bylo na čem zkoušet dotazy typu „na čem
jsem přestal dělat".

### Reálná data z Clockify

```bash
uv run timeagent import --month 2026-08
```

Vyžaduje `CLOCKIFY_API_KEY` (Clockify → Profile settings → API → Generate).
Načte projekty a záznamy za daný měsíc do stejného schématu. Bez `--append`
nejdřív smaže existující záznamy toho měsíce, aby opakovaný import nezdvojoval.

Sazby se berou z Clockify, a kde chybí, použije se `CLOCKIFY_DEFAULT_RATE`.

> **Data zůstávají lokálně.** `*.sqlite` je v `.gitignore`. Import je jediné
> místo, kde se do repozitáře můžou dostat reálná jména klientů — proto ta
> databáze nesmí být commitnutá.

### Schéma

```sql
CREATE TABLE projects (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    client       TEXT NOT NULL,
    hourly_rate  REAL NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'CZK',
    active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE time_entries (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id),
    date        TEXT NOT NULL,          -- ISO YYYY-MM-DD
    hours       REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    billable    INTEGER NOT NULL DEFAULT 1,
    tag         TEXT
);
```

Ploché schéma je záměr: čte se z něj snadno i z jiných nástrojů (n8n, MCP server)
bez znalosti aplikační logiky.

Jedna nekonzistence, o které je dobré vědět: v demo datech drží `tag` název
štítku (`vyvoj`, `analyza`), zatímco import z Clockify tam ukládá jeho ID.
Překlad by vyžadoval další dotaz na `/tags`.

### Jinam než do výchozí cesty

```bash
uv run timeagent --db D:/data/vykazy.sqlite ask "..."
export TIMEAGENT_DB=D:/data/vykazy.sqlite     # totéž natrvalo
```

## Ověření instalace

```bash
uv run pytest -q          # 86 testů; nepotřebují API klíč ani běžící model
uv run timeagent tools    # výpis nástrojů — nepotřebuje model
uv run timeagent ask "Kolik mám projektů?"   # první skutečné volání modelu
```

Když poslední příkaz spadne, chyba obsahuje název modelu a nápovědu. Časté
příčiny řeší [modely.md](modely.md#když-to-nefunguje).
