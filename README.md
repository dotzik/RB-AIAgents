# RB-AIAgents — domácí úkoly ke kurzu AI Agents

Tři úkoly, **jedna doména**: analýza výkazů odpracovaného času a fakturační podklady.
Záměrně stejné zadání pro všechny tři — tím je vidět, čím se jednotlivé přístupy
liší, a ne jen tři nesouvisející ukázky.

| Úkol | Zadání | Řešení | Stav |
|---|---|---|---|
| [HW1](HW1/) | Skript, který zavolá LLM API, použije nástroj a vrátí výsledek zpět modelu | Vlastní ReAct smyčka v Pythonu, 5 nástrojů nad SQLite, multiprovider přes LiteLLM | hotovo |
| [HW2](HW2/) | Agent v no-code platformě, který pracuje s databází | **n8n i LangFlow** nad týmiž nástroji z HW1, vystavenými jako HTTP API; součástí je Telegram bot a naměřené srovnání obou platforem | hotovo |
| [HW3](HW3/) | Agent postavený na frameworku, s nástroji, ideálně přes MCP | Nástroje z HW1 jako **MCP server** a nad ním **dva agenti** — Pydantic AI a Microsoft.Extensions.AI; na týž server se připojily i obě platformy z HW2, takže nad ním běží čtyři klienti | hotovo |

## Data a soukromí

Repozitář neobsahuje žádná reálná data ani jména klientů. Databáze se generuje
lokálně (`timeagent seed`) s fiktivními klienty; kdo chce, může si stejným
schématem naimportovat vlastní výkazy z Clockify — soubory `*.sqlite` a `.env`
jsou v `.gitignore` a nikdy se necommitují.

## Rychlý start

```bash
cd HW1
cp .env.example .env
uv sync
uv run timeagent seed
uv run timeagent ask "kolik hodin jsem odpracoval minulý měsíc?"
```

Podrobnosti v [HW1/README.md](HW1/README.md).
