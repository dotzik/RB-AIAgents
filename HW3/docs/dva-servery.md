# Dva MCP servery: Python a C#

V HW3 jsou nad týmiž nástroji **dva MCP servery**. Není to omyl ani nerozhodnost.

| | `mcp/` (Python) | `mcp-dotnet/` (C#) |
|---|---|---|
| role | **ostrá varianta**, používá se | cvičení na serverovou stranu C# SDK |
| port | 8010 | 8011 |
| odkud bere nástroje | `import timeagent.tools` | `GET /tools` z API v HW2 |
| vidí databázi | ano (read-only) | **ne** |
| potřebuje HW1 v image | ano | **ne** |
| skoků k datům | 1 | 2 |
| řádků | 129 | 187 (+ 6 testů) |

Cesta k datům:

```
klient ──MCP──> mcp (Python) ──> timeagent.tools ──> SQLite
klient ──MCP──> mcp-dotnet (C#) ──HTTP──> hw2 api ──> timeagent.tools ──> SQLite
```

## Proč C# verze vznikla

Agent v `agents/dotnet/` je **klient**, a psaní klienta je v C# SDK skoro
zadarmo: `McpClientTool` dědí z `AIFunction`, takže nástroje jdou do
`ChatOptions.Tools` bez adaptéru a hotovo. O tom, jak se staví `Tool`, jak se
skládá `CallToolResult` nebo jak se hostuje transport, se z toho nedozvíš nic.

Tenhle server tu díru zavírá — a schválně tak, aby **nezduplikoval doménu**.

## Proč proxy a ne vlastní implementace

Napsat nástroje v C# znovu by znamenalo zkopírovat pět dotazů, `_resolve_project`
včetně escapování `%` a `_` ve vzoru, `coerce_arguments`, `_empty_note`
a s tím i 106 testů z HW1. A hlavně by to rozbilo tvrzení, na kterém stojí
srovnání v HW2: že všechny platformy volají bit po bitu tentýž kód.

Proxy tenhle problém nemá — a že ho nemá, je **ověřené, ne slíbené**.
Kontrolu spouští `scripts/compare_servers.py`: porovná `tools/list` a osm volání
včetně hraničních (prázdné období s `note`, neexistující projekt, neznámý
nástroj, narovnání argumentu `"160"` na číslo) a při první odchylce vrátí
nenulový kód.

```bash
cd HW3/mcp && uv run python ../scripts/compare_servers.py
```

```
OK    tools/list — 5 nástrojů shodných
OK    capacity_check({"month": "2026-08"})
…
OK    capacity_check({"month": "2026-08", "target_hours": "160"})

Shodné do posledního bajtu: 8 volání + tools/list.
```

Dřív tu byl místo skriptu úryvek kódu k ručnímu spuštění. Kód v dokumentaci,
který nikdo nespustí, zestárne tiše — a tenhle se s vypsaným výstupem už
rozcházel.

## Co se na tom dá naučit

Serverová strana C# SDK vypadá takhle — a je to skoro doslovný protějšek
nízkoúrovňového `Server` v Pythonu:

```csharp
builder.Services.AddMcpServer(options => { options.ServerInfo = …; })
    .WithHttpTransport()
    .WithListToolsHandler(async (context, ct) =>
        new ListToolsResult { Tools = await catalog.GetToolsAsync(ct) })
    .WithCallToolHandler(async (context, ct) =>
        await catalog.CallAsync(context.Params!.Name, context.Params.Arguments, ct));

app.MapMcp("/mcp");
```

Použily se **nízkoúrovňové handlery, ne atributy `[McpServerTool]`**, a to ze
stejného důvodu, proč Python sáhl po `Server` místo dekorátorů: nástroje nejsou
známé při překladu. Jejich schémata přijdou za běhu z HW1. Atributový model by
vyžadoval napsat pět metod s typovanými parametry — tedy přesně tu duplicitu,
které se celé řešení vyhýbá.

Rozdíly proti Pythonu, které stojí za zapamatování:

- **Handlery jdou přes DI builder** (`.WithListToolsHandler(…)`), ne jako
  argumenty konstruktoru. `RequestContext` má `Services`, takže se k závislostem
  jde dostat, ale ne přes primary constructor injection.
- **`Tool.InputSchema` je `JsonElement`.** Schéma se dá vzít z cizího JSONu
  doslova (`fn.GetProperty("parameters").Clone()`) — což je přesně to, co tady
  bylo potřeba. Nutné je to `Clone()`, jinak schéma zmizí s dokumentem.
- **`CallToolRequestParams.Arguments` je `IDictionary<string, JsonElement>`**,
  ne read-only. Drobnost, kterou najde až kompilátor.
- **Hostování je obyčejná ASP.NET aplikace.** `MapMcp("/mcp")` je jediný řádek
  navíc a `/health` se přidá jako běžný minimal API endpoint.

## Obě záruky platí i tady

`ToolCatalog.CallAsync` **nikdy nenastavuje `IsError`**, ani když upstream vrátí
`{"error": …}`. Ze stejného důvodu jako v Pythonu: model si má hlášku přečíst
a opravit se, ne dostat utnutý běh.

Navíc má proxy jednu situaci, kterou Python server nemá — **výpadek upstreamu**.
I ten jde modelu jako data (`"Nástroj … nedosáhl na API HW2 (HTTP 502)"`), ne
jako protokolová chyba, aby uměl uživateli říct, co se stalo.

Že to není jen teorie, ukázal .NET agent při ověřování proxy. Model si spletl
název projektu, dostal zpátky `{"error": …}` — a v téže odpovědi se opravil:

> „Pracoval jsi v srpnu 2026 na projektu Initech (INIT), ne na neexistujícím
> projektu **Initect**. Zkontroluji to pro tebe.
>
> V srpnu 2026 jsi na projektu Initech žádné hodiny neodpracoval. Data jsou
> k dispozici od 2025-01-01 do 2026-09-04."

Obě záruky v jedné odpovědi: chyba došla jako data (jinak by se běh utnul
a druhý odstavec by nevznikl) a `note` dodalo rozsah dat. Přes dva skoky
a překlad HTTP → MCP.

Testy v `TimeAgent.Mcp.Tests` to hlídají (6 testů, `dotnet test`). Upstream je
v nich podvržený, takže nepotřebují běžící Docker a umí vynutit i stavy, které
se na živých datech vyrábějí těžko: prázdný měsíc a spadlé API.

## Kdy který použít

Pro provoz **Python server**. Proxy je o skok navíc, závisí na běžícím API z HW2
a nepřidává nic, co by Python neuměl.

C# server dává smysl, když je zbytek systému v .NET a nechceš do něj tahat
Python runtime — ale pak by správně neměl být proxy nad Pythonem, nýbrž
nad .NET doménou. Tady tu roli nemá; je to učební kus a v `docker-compose.yml`
je právě proto vedený zvlášť.
