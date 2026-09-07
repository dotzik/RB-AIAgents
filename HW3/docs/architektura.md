# Architektura HW3

## Co se staví

Nástroje z HW1 vystavené jako **MCP server** a nad ním **tři agenti ve třech
frameworcích** (Microsoft Agent Framework, LangGraph, Pydantic AI), plus
napojení obou no-code platforem z HW2.

```
                    ┌──────────────────────────────┐
                    │  HW1: timeagent.tools        │
                    │  5 nástrojů, SQLite ro       │
                    │  žádné LLM SDK               │
                    └───────────┬──────────────────┘
                                │ import (ne kopie)
            ┌───────────────────┴────────────────────┐
            │                                        │
   ┌────────▼─────────┐                   ┌──────────▼──────────┐
   │ HW2: HTTP API    │                   │ HW3: MCP server     │
   │ hw2-api :8000    │                   │ hw3-mcp :8010 /mcp  │
   └────────┬─────────┘                   └──────────┬──────────┘
            │                                        │
   ┌────────┴────────┐              ┌────────────────┼───────────────┐
   │                 │              │            │       │           │
  n8n            LangFlow      3 agenti      n8n         LangFlow
 (HTTP tool)   (5 komponent)  (MAF, LangGraph,  (MCP node)  (MCP Tools)
                               Pydantic AI)
```

Databáze je jedna a obě služby ji mají připojenou **read-only, po jednom souboru**.
Nikdo z pěti klientů HW3 nesahá na SQLite přímo.

## Proč je server v Pythonu, když měl být v .NET

Původní plán byl napsat MCP server v C# (`ModelContextProtocol`). Rozhodnutí se
otočilo po přečtení HW1 — ne z pohodlnosti, ale kvůli tomu, co by C# musel
zduplikovat:

| Co je v HW1 | Kolik | Šlo by to v C# obejít? |
|---|---|---|
| 5 nástrojů s parametrizovaným SQL | ~350 řádků | ne, jsou to dotazy |
| `_resolve_project` — hledání podle id/názvu/klienta, escapování `%` a `_` ve vzoru, hlášky pro nejednoznačnost | ~40 řádků | ne |
| `_empty_note` — věta o rozsahu dat u prázdného výsledku | ~25 řádků | ne |
| `coerce_arguments` — narovnání `"true"`, `"160"`, `"null"` podle schématu | ~35 řádků | ne |
| `TOOL_SCHEMAS` — popisy laděné pro model | ~150 řádků | ne |
| testy | 106 | musely by se napsat znovu |

Druhá implementace by navíc zabila tvrzení, na kterém stojí srovnání v HW2:
že všechny platformy volají **bit po bitu tentýž kód**. Kdyby C# server počítal
fakturu vlastním kódem, přestalo by měření porovnávat platformy a začalo by
porovnávat dvě implementace faktury.

Python server má proti tomu **159 řádků včetně komentářů a nula řádků doménové logiky**.

.NET z úkolu nezmizel — je v něm jeden z agentů. Tam duplicitu nezpůsobí, protože
agent žádnou doménovou logiku nemá.

## Proč nízkoúrovňový `Server` a ne dekorátory

MCP SDK nabízí pohodlné `MCPServer` s dekorátorem `@mcp.tool()`, který odvodí
schéma nástroje ze signatury a docstringu funkce. Tady by to škodilo.

Popisy v `TOOL_SCHEMAS` jsou psané **pro model**, ne pro programátora:

```
"Vypíše projekty: identifikátor, název, jméno klienta, hodinovou sazbu a měnu.
 Zavolej jako první, když neznáš přesný název projektu nebo potřebuješ sazbu.
 Sazby jinde nezjistíš."
```

Ze signatury `list_projects(active_only: bool = False)` se tohle odvodit nedá.
Stejně tak `enum` u `dimension` nebo věta „na jeden měsíc je vhodnější
capacity_check". V měření HW1 zvedlo doladění popisů úspěšnost víc než výměna
modelu za větší — zahodit je by byla ta nejdražší úspora v celém úkolu.

Nízkoúrovňový server proto schéma **přebírá doslova**:

```python
TOOLS = [
    types.Tool(name=fn["name"], description=fn["description"],
               input_schema=fn["parameters"])
    for fn in (s["function"] for s in tools.TOOL_SCHEMAS)
]
```

Že to platí, hlídá test `test_seznam_nastroju_je_shodny_s_hw1` — porovnává
seznam z MCP proti `TOOL_SCHEMAS` včetně popisů a enumů.

## Dvě věci, které přechod na protokol snadno rozbije

Obojí je zvenčí neviditelné a obojí je zaplacené pozorováním z HW1 a HW2.

### Chyba je data, ne selhání volání

`tools.call_tool` výjimky **chytá** a vrací `{"error": "…"}`, aby si model
přečetl, co udělal špatně, a opravil se. MCP protokol má na chybu vlastní
příznak `isError` — a je svůdné ho použít. Server ho **nikdy nenastavuje**:

```python
return types.CallToolResult(
    content=[types.TextContent(type="text", text=json.dumps(result, …))],
    structured_content=result,
)   # is_error se nenastavuje ani pro {"error": …}
```

S `is_error=True` by klient volání vyhodnotil jako selhání, běh utnul a model by
zpětnou vazbu nikdy neviděl. Je to táž zásada jako „Neopravovat na 500"
v `HW2/api/main.py`.

### `note` u prázdného výsledku

Když dotaz nic nenajde, `_empty_note` přidá větu s rozsahem dostupných dat.
Nula sama o sobě je pro model dvojznačná — neví, jestli se nepracovalo, nebo
jestli tam databáze nesahá. Bez té věty si dopočítá „pokračování trendu".

Prošlo to i přes protokol, a je to vidět na odpovědích v [srovnani.md](srovnani.md):
oba klienti u dotazu na ukončený projekt sami uvedli „Data jsou k dispozici
od 2025-01-01 do 2026-09-04".

## V čem je MCP lepší než HTTP API z HW2

Nejde o rychlost — ta je stejná, obojí čeká na tentýž model. Rozdíl je v tom,
co se **nemuselo napsat**.

| | HW2 (HTTP) | HW3 (MCP) |
|---|---|---|
| uzlů v n8n workflow | 20 (z toho 5 tool nodů) | **5** (z toho 1) |
| uzlů v LangFlow flow | 9 (z toho 5 komponent) | **5** (z toho 1) |
| generátor LangFlow komponent | 290 řádků, šablona třídy | **207 řádků, bez šablony** |
| schéma parametrů | dopsané ručně do textu popisu | **posílá protokol** |
| dvě cesty ke stejnému nástroji | `POST /tools/{n}` i `GET /run/{n}` | **jedna** |

Ty tři řádky uprostřed jsou to podstatné:

- **n8n** nemá uzel, který by z jednoho HTTP API udělal pět nástrojů. HW2 proto
  má pět uzlů `toolHttpRequest`, do jejichž popisu se musel **ručně dopsat soupis
  parametrů** („Parametry (vyplň všechny): …"), protože ten uzel modelu žádné
  schéma nepředává. MCP posílá `inputSchema`, takže berlička odpadá.
- **LangFlow** má komponentu API Request, ale v tool mode vystaví modelu jediný
  nástroj `make_api_request` s volným parametrem `url_input` — pět jejích kopií
  nedá pět nástrojů, ale pětkrát totéž. HW2 proto **generoval pět Python
  komponent**. MCP je jedna komponenta.
- **`GET /run/{name}`** v HW2 existuje jen proto, že LangFlow uměl modelu vystavit
  jen URL a tělo požadavku sestavit neuměl. MCP tohle omezení nemá.

Tohle je odpověď na „proč MCP místo framework-specific toolů": ne že by to bez
něj nešlo, ale každá platforma si vymýšlela vlastní obcházku téhož a schéma
parametrů se cestou ztrácelo.
