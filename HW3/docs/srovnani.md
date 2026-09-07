# Tři frameworky nad jedním MCP serverem

Všichni tři klienti dostali **stejný server, stejných pět nástrojů, stejný
systémový prompt a stejný model** (`qwen2.5:32b` na DGX Sparku, temperature 0).
Liší se jen framework — nástroje si všichni tahají z téhož `tools/list`.

| agent | framework | ze seznamu v zadání |
|---|---|---|
| `agents/dotnet` | Microsoft Agent Framework (`Microsoft.Agents.AI`) | ano |
| `agents/langgraph` | LangGraph (`create_react_agent`) | ano |
| `agents/python` | Pydantic AI | ne — přidán pro srovnání |

Že je prompt opravdu stejný, není slib: Python klienti si ho importují z
`timeagent.agent.build_system_prompt`, .NET ho čte z `agents/system_prompt.json`,
který z téhož zdroje generuje `scripts/export_system_prompt.py`
(`--check` ohlásí, kdyby se rozešly).

## Naměřený výsledek

Osm dotazů z benchmarkové sady HW1 — táž sada jako v HW2, importovaná přímo
z `HW2/scripts/compare_platforms.py`. Spouští je `scripts/compare_clients.py`;
očekávané hodnoty se počítají z nástrojů, ne z opsaných konstant.
**Tři běhy na klienta**, protože jeden průchod u téhle úlohy nestačí — proč,
je celá další sekce.

| | LangGraph | Pydantic AI | Microsoft Agent Framework |
|---|---|---|---|
| skóre ve třech bězích | 7, 7, 7 | **8, 8, 8** | 8, 7, 8 |
| medián na dotaz | 13,2 s | 15,6 s | **12,5 s** |
| padlo aspoň jednou | `ukonceny` | — | `ukonceny` |

Časy jsou v rámci šumu — všichni čekají na tentýž model a devět z deseti sekund
běhu je inference. **Framework se na rychlosti neprojeví.** Pro srovnání s HW2
(n8n i LangFlow 8/8): MCP vrstva nic nezpomalila.

Rozdíl ve skóre má **jedinou** příčinu: dotaz `ukonceny`. Na ostatních sedmi
dotazech dali všichni tři klienti ve všech devíti bězích správnou odpověď.

## Ten jeden dotaz — a proč se z něj nedá dělat závěr o frameworku

Dotaz zní *„Pracoval jsem v srpnu 2026 na projektu Initech?"*. Selhání má
pokaždé stejný tvar, doložený uloženou trasou volání v [`mereni.json`](mereni.json):

1. model zavolá `query_time_entries` s **překlepem** `project: "Initect"`,
2. nástroj vrátí `{"error": "Projekt 'Initect' neexistuje. Dostupné: …"}`,
3. model **neudělá druhé volání** a napíše odpověď, která tvrdí opak pravdy
   („Pracoval jsi…") a navíc do ní opíše seznam projektů z chybové hlášky.

Systémový prompt přitom obsahuje pravidlo „Chybovou hlášku z nástroje nikdy
nepiš do odpovědi jako výsledek". Nepomohlo.

**Kdo na to sedne, se ale mezi sadami běhů úplně obrací.** Nezávislá prověrka
pustila tentýž skript třikrát na tomtéž stroji a dostala jiné rozdělení:

| | LangGraph | Pydantic AI | Microsoft AF |
|---|---|---|---|
| tři běhy zde | **3× padlo** | 0× | 1× |
| tři běhy v nezávislé prověrce | 0× | 2× | 1× |

Šest běhů na klienta a pořadí se převrátí. Závěr je proto **negativní a je to
jediný závěr, který data unesou**:

> Chování po chybě nástroje **není v tomhle měření vlastnost frameworku**.
> Všichni tři klienti mají tentýž způsob selhání a liší se jen tím, jak často
> ho model zrovna trefí. Rozhoduje, jestli model napíše překlep — a to je
> vlastnost dekódování, ne smyčky.

Temperature 0 tady determinismus nezaručuje: u dávkované inference na GPU se
pořadí redukcí mezi běhy liší a u odpovědi, která visí na hraně, to stačí.

**Dřívější verze tohohle dokumentu tvrdila opak** — že LangGraph po chybě
neudělá druhé kolo, zatímco MAF ano, a že je to při temperature 0
reprodukovatelné. Stálo to na jednom běhu a jednom ručním zopakování. Nebyla to
pravda; byl to šum vysvětlený jako mechanismus. Opraveno přidáním `--repeat`,
což je přesně to, co si HW1 v `docs/mereni.md` sám předepsal a co se sem
nepřeneslo.

### Co by tenhle dotaz opravdu spravilo

Ne jiný framework. Buď **nástroj, který na otázku umí odpovědět** —
`project_activity(project)` s prvním a posledním záznamem — nebo **tolerance
k překlepu** v `_resolve_project` (fuzzy shoda, když přesná selže). Dnes se měří
hlavně to, že žádný nástroj přesně na tuhle otázku nesedí.

Připomínka z HW2: dotaz je past i jinak, protože `INIT` je Initech a `INTR`
Interní. Tam na ni obě platformy aspoň jednou sedly — popsaly nulu jménem
druhého projektu.

## Kolik kódu je potřeba

Všichni tři jsou kratší než ReAct smyčka z HW1 (374 řádků `agent.py`), protože
krokování, záchranu pokažených tool callů i pojistky proti zacyklení dělá
framework:

| | řádků | co obsluhuje sám |
|---|---|---|
| HW1 — vlastní smyčka | 374 | vše |
| LangGraph | 156 | CLI, výpis, ošetření výpadků |
| Pydantic AI | 148 | CLI, výpis, ošetření výpadků |
| Microsoft Agent Framework | 214 | totéž + čtení `.env`, dosazení data do promptu |

Jádro každého z nich jsou tři až pět řádků:

```python
# LangGraph
tools = await MultiServerMCPClient({"timeagent": {...}}).get_tools()
agent = create_react_agent(ChatOllama(...), tools)
result = await agent.ainvoke({"messages": [SystemMessage(...), HumanMessage(q)]})
```

```python
# Pydantic AI
agent = Agent(OllamaModel(model, provider=provider),
              system_prompt=build_system_prompt(),
              toolsets=[MCPToolset(mcp_url)])
result = await agent.run(question)
```

```csharp
// Microsoft Agent Framework
var tools = await mcpClient.ListToolsAsync();
AIAgent agent = new ChatClientAgent(chat, instructions: BuildSystemPrompt(),
                                    name: "vykazy", tools: [.. tools]);
var response = await agent.RunAsync(question);
```

Ve všech třech případech se **nástroje nedeklarují ani nepopisují** — přijdou
ze serveru. V C# navíc není mezi MCP a agentem žádný adaptér: `McpClientTool`
dědí z `AIFunction`, takže jde do `ChatClientAgent` rovnou.

## Co který framework dělá jinak

Když se ukázalo, že na úspěšnosti si jsou rovné, zbývá to zajímavější — v čem
se liší práce s nimi:

- **LangGraph** je jediný, kde je agent explicitně **graf**. `create_react_agent`
  je hotová dvojice uzlů (model ⇄ nástroje). Jakmile je potřeba do smyčky
  zasáhnout — vynutit krok navíc po chybě, vlastní podmínka ukončení — sáhne se
  pod něj a graf se poskládá ručně. Z těch tří je to jediný, kde je ten zásah
  přirozený, ne obcházení.
- **Pydantic AI** má MCP zabudované jako *toolset*: `MCPToolset(url)` je celé
  napojení včetně životního cyklu spojení přes `async with agent`. Nejmíň kódu
  na nejmíň práce.
- **Microsoft Agent Framework** staví na `IChatClient` z Microsoft.Extensions.AI.
  `ChatClientAgent` drží instrukce, nástroje i smyčku, takže odpadá ruční
  `UseFunctionInvocation()` i skládání seznamu zpráv. Nabízí navíc sezení
  (`AgentSession`) pro víckolové konverzace, které tenhle úkol nepotřebuje.

### Ergonomie

.NET vyžadoval dvě věci navíc, které Python dostal zadarmo: čtení `.env`
(dvacet řádků vlastního čtenáře místo `python-dotenv`) a export systémového
promptu do JSONu, protože na balíček z HW1 nedosáhne. Obojí je daň za to, že
doména je v Pythonu — ne za framework.

Všichni tři hlásí výpadek závislosti stejně: jedna věta s nápovědou a nenulový
návratový kód, ať už nejede MCP server nebo model.

## Poznámka k datům

Naměřená tabulka je z aktuálních dat (leden 2025 až dnešek, 1238 záznamů).
**Citace odpovědí se nepřepisují** — jsou to záznamy pozorování.

Surová data včetně trasy volání u každého dotazu: [`mereni.json`](mereni.json).
