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

| | LangGraph | Pydantic AI | Microsoft Agent Framework |
|---|---|---|---|
| správně | 7/8 | **8/8** | **8/8** |
| celkem | 109,8 s | 120,3 s | 112,4 s |
| medián na dotaz | 13,0 s | 14,3 s | 15,2 s |
| volání nástrojů | 9 | 9 | 10 |

Časy jsou v rámci šumu — všichni čekají na tentýž model a devět z deseti sekund
běhu je inference. **Framework se na rychlosti neprojeví.** Pro srovnání s HW2
(n8n 8/8, medián 12,7 s; LangFlow 8/8, medián 15,4 s): MCP vrstva nic nezpomalila.

## Jediný rozdíl ve výsledku: co se stane po chybě nástroje

Za celým rozdílem stojí jeden dotaz — *„Pracoval jsem v srpnu 2026 na projektu
Initech?"*. Model si u něj napsal jméno projektu s překlepem a nástroj vrátil
chybu jako data:

```json
{"error": "Projekt 'Initect' neexistuje. Dostupné: ACME (Acme Corp), …"}
```

Tím je splněná záruka ze serveru: model má hlášku k dispozici a **může** se
opravit. Jestli to udělá, rozhoduje smyčka frameworku.

**LangGraph** skončil po jednom kole a hlášku opsal do odpovědi jako výsledek —
navíc s obrácenou odpovědí („Pracoval jsi…", správně je nepracoval):

> „Pracoval jsi v srpnu 2026 na projektu Initech (záznamy jsou dostupné pro
> projekty: ACME, NWND, GLBX, INIT, INTR). Zkontroluj jméno projektu a zkus to
> znovu."

Systémový prompt přitom obsahuje pravidlo „Chybovou hlášku z nástroje nikdy
nepiš do odpovědi jako výsledek". Chování je při temperature 0 reprodukovatelné.

**Microsoft Agent Framework** narazil na týž překlep, ale udělal **druhé volání**
a opravil se:

> „V srpnu 2026 jsi na projektu Initech žádné hodiny neodpracoval.
> Data jsou k dispozici od 2025-01-01 do 2026-09-04."

**Pydantic AI** trefil jméno napoprvé a odpověděl správně na jedno volání.

Druhá věta u MAF nepochází z modelu — je to `note` z `_empty_note` v HW1.
Prošlo celou cestou přes MCP a klient ho modelu předal.

Je to jedno pozorování na framework, ne statistika. Ukazuje ale, že „chyba jako
data" je **nutná, ne dostatečná** podmínka: server dá modelu šanci se opravit,
ale využít ji musí agentní smyčka. Prebuilt `create_react_agent` v LangGraphu tu
šanci u tohohle modelu nevyužil.

Připomínka z HW2: tenhle dotaz je past, protože `INIT` je Initech a `INTR` je
Interní. Tam na ni oba agenti aspoň jednou sedli jinak — popsali nulu jménem
druhého projektu.

## Kolik kódu je potřeba

Všichni tři jsou kratší než ReAct smyčka z HW1 (374 řádků `agent.py`), protože
krokování, záchranu pokažených tool callů i pojistky proti zacyklení dělá
framework:

| | řádků | co obsluhuje sám |
|---|---|---|
| HW1 — vlastní smyčka | 374 | vše |
| LangGraph | 143 | CLI a výpis |
| Pydantic AI | 135 | CLI a výpis |
| Microsoft Agent Framework | 190 | CLI, výpis, čtení `.env`, dosazení data do promptu |

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

- **LangGraph** je jediný, kde je agent explicitně **graf**. `create_react_agent`
  je hotová dvojice uzlů (model ⇄ nástroje); jakmile by bylo potřeba do smyčky
  zasáhnout — vlastní podmínka ukončení, krok navíc po chybě — sáhne se pod něj
  a graf se poskládá ručně. Tady by to zrovna pomohlo.
- **Pydantic AI** má MCP zabudované jako *toolset*: `MCPToolset(url)` je celé
  napojení včetně životního cyklu spojení přes `async with agent`.
- **Microsoft Agent Framework** staví na `IChatClient` z Microsoft.Extensions.AI.
  `ChatClientAgent` drží instrukce, nástroje i smyčku, takže odpadá ruční
  `UseFunctionInvocation()` i skládání seznamu zpráv. Nabízí navíc sezení
  (`AgentSession`) pro víckolové konverzace, které tenhle úkol nepotřebuje.

### Ergonomie

.NET vyžadoval dvě věci navíc, které Python dostal zadarmo: čtení `.env`
(dvacet řádků vlastního čtenáře místo `python-dotenv`) a export systémového
promptu do JSONu, protože na balíček z HW1 nedosáhne. Obojí je daň za to, že
doména je v Pythonu — ne za framework.

## Poznámka k datům

Naměřená tabulka je z aktuálních dat (leden 2025 až dnešek, 1238 záznamů).
**Citace odpovědí se nepřepisují** — jsou to záznamy pozorování.

Surová data měření: [`mereni.json`](mereni.json).
