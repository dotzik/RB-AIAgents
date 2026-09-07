# Instalace a spuštění

Předpoklady: Docker, [uv](https://docs.astral.sh/uv/), .NET 10 SDK a databáze
z HW1 (`cd HW1 && uv run timeagent seed --months 21`).

HW3 se připojuje do sítě, kterou vytváří HW2, takže **HW2 stack musí běžet**.
Bez něj `docker compose up` selže hláškou, že síť `rb-aiagents_hw2` neexistuje —
je to záměr, ne chyba.

## MCP server

```bash
cd HW2 && docker compose up -d          # síť + HTTP API z HW2
cd ../HW3
cp .env.example .env                    # zkontroluj OLLAMA_BASE_URL
docker compose up -d --build
curl http://localhost:8010/health
```

`/health` musí vrátit `"status":"ok"` a `"tools":5`. Když vrátí 503, chybí
databáze — vygeneruj ji v HW1.

Testy serveru běží bez Dockeru:

```bash
cd HW3/mcp && uv run pytest
```

## Druhý MCP server v C# (volitelně)

Proxy nad API z HW2 — cvičení na serverovou stranu SDK, ne náhrada za Python
server. Podrobně v [dva-servery.md](dva-servery.md).

```bash
cd HW3
docker compose up -d --build mcp-dotnet
curl http://localhost:8011/health          # {"status":"ok","upstream":"http://api:8000","tools":5}

cd mcp-dotnet/TimeAgent.Mcp.Tests && dotnet test
```

Testy podvrhují upstream, takže běží bez Dockeru i bez databáze. Shodu obou
serverů ověří `cd HW3/mcp && uv run python ../scripts/compare_servers.py`.

Všichni agenti na něj umí ukázat přepínačem:

```bash
uv run lgagent ask "…"  --mcp-url http://127.0.0.1:8011/mcp
uv run mcpagent ask "…" --mcp-url http://127.0.0.1:8011/mcp
dotnet run -- ask "…"   --mcp-url http://127.0.0.1:8011/mcp
```

## Agent v Pythonu

```bash
cd HW3/agents/python
uv run mcpagent tools                   # co server nabízí
uv run mcpagent ask "Kolik hodin jsem odpracoval v srpnu 2026?"
uv run mcpagent ask "…" --json          # strojový výstup
```

## Agent v LangGraphu

```bash
cd HW3/agents/langgraph
uv run lgagent tools
uv run lgagent ask "Kolik hodin jsem odpracoval v srpnu 2026?"
```

## Agent v .NET (Microsoft Agent Framework)

```bash
cd HW3
python scripts/export_system_prompt.py  # prompt z HW1 → agents/system_prompt.json
cd agents/dotnet/McpAgent
dotnet run -- tools
dotnet run -- ask "Kolik hodin jsem odpracoval v srpnu 2026?"
```

`export_system_prompt.py` stačí spustit po změně promptu v HW1;
`--check` ohlásí, jestli je soubor zastaralý.

Všichni tři klienti berou adresu modelu a serveru z `HW3/.env`; přebít je jde
přepínači `--mcp-url`, `--model`, `--ollama-url`.

## Napojení n8n a LangFlow

Viz [napojeni-nocode.md](napojeni-nocode.md).

## Měření

```bash
cd HW3
dotnet build agents/dotnet/McpAgent           # skript spouští s --no-build
python scripts/compare_clients.py --repeat 3 --json docs/mereni.json
python scripts/compare_clients.py --only langgraph --repeat 1
```

Výsledky a jejich čtení: [srovnani.md](srovnani.md).

## Řešení potíží

**`/health` vrací 503.** Databáze není na místě. Zkontroluj `TIMEAGENT_DB_FILE`
v `.env` a že soubor existuje; mountuje se read-only jako jeden soubor, takže
překlep v cestě vypadá jako chybějící databáze.

**Klient hlásí `Invalid Host header` nebo 421.** MCP SDK má zapnutou ochranu
proti DNS rebindingu a odmítá hostitele mimo výčet. Výchozí seznam je
v `mcp/src/timeagent_mcp/server.py` (`DEFAULT_ALLOWED_HOSTS`); další se přidají
přes `MCP_ALLOWED_HOSTS` v `.env`, čárkou oddělené i s portem
(`mujstroj.lan:8010`).

**Port 8010 je obsazený.** Změň `MCP_PORT` v `.env` a **zároveň** přidej nový
`localhost:<port>` do `MCP_ALLOWED_HOSTS` — jinak server spojení odmítne
z předchozího důvodu.

**.NET klient nenajde `system_prompt.json`.** Soubor se generuje a kopíruje
vedle binárky při buildu. Spusť `python scripts/export_system_prompt.py`
a `dotnet build`.

**Agent odpovídá, ale bez čísel z nástrojů.** Zkontroluj, že model umí tool
calling — menší modely v této úloze selhávají, viz `HW1/docs/mereni.md`.
