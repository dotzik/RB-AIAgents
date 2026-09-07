# Napojení n8n a LangFlow na MCP server

Obě platformy z HW2 umí být MCP klientem. Zapojily se na **týž server**, který
používají všichni tři frameworkoví agenti — takže nad jedním MCP serverem
běží pět různých klientů.

**HW2 stack se přitom nemění.** Je to referenční srovnání a musí zůstat přesně
takový, jaký se odevzdával; `git status HW2/` po celém HW3 nesmí nic ukázat.
Jediný zásah je compose překryv popsaný níž, který žije v `HW3/`.

## LangFlow

```bash
# z kořene repozitáře — jednorázově, kvůli SSRF (viz níž)
docker compose -f HW2/docker-compose.yml -f HW3/langflow-mcp.override.yml \
               --env-file HW2/.env --project-directory HW2 up -d langflow

# vygenerovat flow (wrapper předá prompt z HW1 do kontejneru)
cd HW3 && python scripts/gen_langflow_flow.py

# nahrát a rovnou vyzkoušet
python scripts/import_langflow_flow.py \
    --ask "Kolik hodin jsem odpracoval v srpnu 2026?"
```

Flow má **pět uzlů**: ChatInput → Agent ← Ollama, plus jedna komponenta
MCP Tools. V HW2 jich bylo devět, protože každý nástroj potřeboval vlastní
vygenerovanou Python komponentu.

### Past 1: ochrana proti SSRF

LangFlow blokuje spojení na privátní adresy a povolený výčet má v HW2 nastavený
na `${OLLAMA_HOST_ONLY},api,localhost,127.0.0.1`. Služba `mcp` v něm není, takže
by se komponenta nepřipojila — a chyba by vypadala jako problém serveru, ne jako
blokace na straně klienta.

Řeší to `HW3/langflow-mcp.override.yml`: compose překryv, který přidá `mcp`
do `LANGFLOW_SSRF_ALLOWED_HOSTS` a nic jiného. Soubory HW2 zůstávají nedotčené.
Po spuštění samotného HW2 compose se LangFlow vrátí k původnímu výčtu.

Ověření:

```bash
docker exec hw2-langflow sh -c 'echo $LANGFLOW_SSRF_ALLOWED_HOSTS'
# …,api,mcp,localhost,127.0.0.1
```

### Past 2: MCP servery jsou mimo flow

LangFlow drží MCP servery jako **sdílený seznam** (`/api/v2/mcp/servers`),
komponenta se na ně odkazuje jen jménem. Samotný import flow proto nestačí —
na čerstvé instanci by se komponenta otevřela s prázdným rozbalovátkem.
Registraci dělá generátor i importér (`ensure_mcp_server`), takže se na to
nedá zapomenout.

### Past 3: `tool_mode` není parametr

`tool_mode` u komponenty MCP Tools **není položka šablony**, ale příznak uzlu.
Plátno ho nastaví samo při zapojení do `tools`; low-level builder ne, a bez něj
komponenta vrátí jeden výsledek do plátna místo toho, aby se agentovi ukázala
jako sada nástrojů. Generátor ho proto nastavuje ručně na `data.node.tool_mode`.

## n8n

```bash
cd HW3
# id credentialu na Ollamu je vidět v URL po jeho otevření v n8n
python scripts/build_n8n_workflow.py     # bez ID: zástupná hodnota
python scripts/build_n8n_workflow.py --credential-id <id>   # pro lokální běh
python scripts/import_n8n_workflow.py --ask "Kolik hodin jsem odpracoval v srpnu 2026?"
```

Workflow má **pět uzlů** (Chat → Agent ← Ollama + paměť + MCP Client Tool).
V HW2 jich bylo dvacet, z toho pět `toolHttpRequest`. Část toho rozdílu jde
za Telegramem, který HW3 nemá; samotných tool uzlů je ale 5 → 1.

### Past 1: rozbalovátko transportu

n8n má ohlášenou vadu, kdy se výběr „HTTP Streamable" v UI neuloží a uzel jede
po zastaralém SSE, které tenhle server nenabízí. Projeví se to jako opakované
selhání spojení, ne jako chyba konfigurace.

Vygenerovaný flow to obchází tím, že hodnotu nese **explicitně v JSONu**:

```json
"serverTransport": "httpStreamable"
```

Kdo uzel klika ručně a narazí na to, přepne pole do režimu Expression a napíše
`httpStreamable` jako řetězec.

### Past 2: `Secure` cookie na prostém HTTP

Importní skript se přihlašuje přes `/rest/login`. n8n vrací autentizační cookie
označenou `Secure`, takže ji `http.cookiejar` přes prosté `http://` nikdy
neodešle a každé další volání skončí na 401. Skript proto cookie čte
z hlavičky a posílá ručně. Do tokenu je navíc zapečený `browser-id`, který musí
být u přihlášení i u všech dalších volání stejný.

## Ověřený stav

Všech pět klientů odpovědělo na kontrolní dotaz *„Kolik hodin jsem
odpracoval v srpnu 2026?"* správně (142 hodin):

| klient | jak se připojuje |
|---|---|
| agent LangGraph | `MultiServerMCPClient`, transport `streamable_http` |
| agent Pydantic AI | `MCPToolset("http://127.0.0.1:8010/mcp")` |
| agent .NET (Microsoft Agent Framework) | `HttpClientTransport`, `StreamableHttp` |
| n8n | uzel MCP Client Tool → `http://mcp:8000/mcp` |
| LangFlow | komponenta MCP Tools → registrovaný server `timeagent` |

Systematické měření frameworkových klientů je v [srovnani.md](srovnani.md);
u no-code platforem se ověřovalo jen spojení a jeden dotaz, protože jejich
srovnání je předmětem HW2.
