# HW3 — agent postavený na frameworku

Zadání: navrhni a vytvoř agenta pomocí frameworku, který pracuje s nástroji
a odpovídá na dotazy přes LLM. Doporučeno zvážit MCP místo framework-specific toolů.

## Co je hotové

Nástroje z [HW1](../HW1/) vystavené jako **MCP server** a nad ním **tři agenti
ve třech frameworcích**. Na týž server se připojily i **obě no-code platformy
z [HW2](../HW2/)**, takže nad jedním serverem běží pět různých klientů.

| agent | framework | ze seznamu v zadání |
|---|---|---|
| `agents/dotnet` | **Microsoft Agent Framework** (`Microsoft.Agents.AI`) | ano |
| `agents/langgraph` | **LangGraph** (`create_react_agent`) | ano |
| `agents/python` | Pydantic AI | ne — přidán pro srovnání |

Typ agenta je u všech tří **ReAct**: model zavolá nástroj, dostane výsledek
a pokračuje, dokud nemá odpověď.

Server nemá **žádnou doménovou logiku**: importuje `timeagent.tools` a jen ho
obaluje protokolem. Stejně jako HTTP API v HW2 — proto jsou všechna tři zadání
pořád srovnatelná.

## Rychlý start

```bash
cd HW2 && docker compose up -d          # HW3 se připojuje do jeho sítě
cd ../HW3
cp .env.example .env
docker compose up -d --build
curl http://localhost:8010/health

cd agents/python && uv run mcpagent ask "Kolik hodin jsem odpracoval v srpnu 2026?"
```

Podrobnosti v [docs/instalace.md](docs/instalace.md).

## Výsledek

Osm dotazů z benchmarkové sady HW1, model `qwen2.5:32b` na DGX Sparku:

| | Python (Pydantic AI) | .NET (Microsoft.Extensions.AI) |
|---|---|---|
| správně | **8/8** | **8/8** |
| medián na dotaz | 13,7 s | 12,6 s |

Framework se na rychlosti neprojeví — devět z deseti sekund běhu je inference.
Rozdíl je v tom, kolik kódu je potřeba napsat, a ten je popsaný
v [docs/srovnani.md](docs/srovnani.md).

## Dvě rozhodnutí, která stojí za přečtení

**Server je v Pythonu, přestože plán byl C#.** Ne z pohodlnosti: C# by musel
znovu napsat celou doménu z HW1 — pět nástrojů, hledání projektu podle názvu
i klienta, `coerce_arguments`, větu o rozsahu dat u prázdného výsledku — a s ní
i 106 testů. Druhá implementace by navíc zabila tvrzení, na kterém stojí HW2:
že všechny platformy volají bit po bitu tentýž kód. .NET z úkolu nezmizel, je
v něm druhý agent; ten žádnou doménovou logiku nemá, takže duplicitu nezpůsobí.

**Chyba se přes MCP posílá jako data, ne jako `isError`.** `call_tool` v HW1
výjimky chytá schválně, aby si model přečetl, co udělal špatně, a opravil se.
Kdyby se to přeložilo na protokolovou chybu, klient by běh utnul a model by tu
zpětnou vazbu nikdy neviděl. Totéž platí pro pole `note` u prázdného výsledku.
Obojí hlídají testy v `mcp/tests/` a je to vidět i na odpovědích agentů.

Celé odůvodnění včetně toho, proč se sáhlo po nízkoúrovňovém API místo dekorátorů:
[docs/architektura.md](docs/architektura.md).

## Struktura

```
mcp/          MCP server v Pythonu (159 řádků, nula doménové logiky) + testy + Dockerfile
mcp-dotnet/   druhý MCP server v C# — proxy nad API z HW2, cvičení na serverovou
              stranu SDK; ostrá varianta je ta Python (docs/dva-servery.md)
agents/
  dotnet/     agent na Microsoft Agent Framework
  langgraph/  ReAct agent na LangGraphu
  python/     agent na Pydantic AI
  system_prompt.json   generovaný z HW1, aby měli všichni týž prompt
flows/        vygenerovaná workflow pro n8n a LangFlow
scripts/      generátory flow, importéry, měření, export promptu
docs/         architektura, srovnání, instalace, napojení no-code
```

## Dokumentace

- [architektura.md](docs/architektura.md) — proč Python server, proč low-level API, v čem je MCP lepší než REST z HW2
- [srovnani.md](docs/srovnani.md) — **hlavní výstup**: LangGraph vs. Microsoft Agent Framework vs. Pydantic AI
- [instalace.md](docs/instalace.md) — spuštění a řešení potíží
- [napojeni-nocode.md](docs/napojeni-nocode.md) — n8n a LangFlow přes MCP, včetně pastí
- [dva-servery.md](docs/dva-servery.md) — proč vedle Python serveru stojí ještě C#, a co se z něj dá naučit
