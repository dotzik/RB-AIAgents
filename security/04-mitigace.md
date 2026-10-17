# 4. Návrh mitigací

[← Rozcestník](README.md)

## 4.1 Přehled

| ID | Opatření | Řeší | Místo vynucení | Vlastník |
|---|---|---|---|---|
| **M1** | **Autorizační gate v MCP serveru** | T2, T1, T4, omezuje T3 | MCP server, před voláním nástroje | vlastník systému |
| M2 | Allowlist a limit zpráv v n8n | T1, T7 | n8n, hned za Telegram triggerem | vlastník systému |
| M3 | Uzavření ostatních cest k datům | T4 | docker compose | vlastník systému |
| M4 | Hardening administrace a tajemství | T6 | compose, `.env`, n8n, LangFlow | vlastník systému |
| M5 | Chráněná cesta k modelu | T5 | start každého klienta, síť | vlastník systému |
| M6 | Import jako nedůvěryhodný vstup | T3 | importer CSV | vlastník systému |
| M7 | Retence konverzací | T8 | n8n | vlastník systému |
| M8 | Řízené přebírání závislostí (supply chain) | T9 | build image, start služeb, git | vlastník systému |

Vlastník je u všech stejný: systém provozuje jeden člověk (dodavatel).
Rozdělení rolí v kapitole 6.

## 4.2 M1 · Autorizační gate v MCP serveru

**Řetězec:** T2 (identita z promptu) → hranice B2 a B3 → gate v MCP serveru →
testy V0–V13 a V21–V25 (kap. 5) → zbytkové riziko níže.

**Proč v MCP serveru:** všech pět klientů volá nástroje přes něj. Kontrola
v n8n by chránila jen Telegram, kontrola v promptu nechrání nic. Gate je
deterministický kód před SQL dotazem, model ho nemůže přesvědčit.

### Důvěryhodné vstupy

| Vstup | Odkud | Proč mu věřit |
|---|---|---|
| Identita služby | hlavička `Authorization: Bearer <token>`, každý klient MCP má vlastní token | token zná jen daná služba, porovnání v konstantním čase |
| Identita uživatele | hlavička `X-Timeagent-Chat-Id`, nastaví ji n8n z `message.chat.id` Telegram updatu | hodnota pochází z Telegram API, ne z textu zprávy; model hlavičky nevidí ani nenastaví |
| Typ chatu | hlavička `X-Timeagent-Chat-Type` z `message.chat.type` | identitu gate uzná jen pro `private`; ve skupině `chat.id` neoznačuje člověka |
| Oprávnění | soubor politiky `access.toml`: služba → role, `chat_id` → klient, `owner_chat_ids` | spravuje ho jen vlastník, změna přes git; `chat_id` nesmí být vlastník i klient zároveň (politika se jinak nenačte) |
| Vazba projekt → klient | databáze (`projects.client`) | zdroj pravdy o datech |

**Nedůvěryhodné:** všechny argumenty nástrojů. Identita v argumentu
(`chat_id`, `client`) se ignoruje.

### Pravidla

| Role | Kdo | Co smí |
|---|---|---|
| `owner` | tři frameworkoví agenti a LangFlow vlastníka | vše jako dnes; po nasazení gate musí každý posílat svůj token (dnes se připojují bez něj) |
| `client-proxy` | n8n Telegram workflow | jen za ověřeného klienta podle `chat_id`, viz níže; `chat_id` z `owner_chat_ids` dostane roli `owner` |
| — | jakýkoli chat jiný než soukromý | nic, ani vlastník (`chat_not_private`) |
| bez role | neznámý nebo chybějící token | nic, HTTP 401 ještě před MCP |

Klient přes `client-proxy`:

| Nástroj | Pravidlo |
|---|---|
| `tools/list` | klient vidí jen nástroje, které smí volat (bez `capacity_check`) |
| `list_projects` | vrátí jen projekty klienta |
| `query_time_entries`, `compute_invoice`, `summarize_by` | `project` povinný; gate ho vyhodnotí **jen mezi projekty klienta**, jinak zamítne |
| `summarize_by(dimension="client")` | zamítnuto, přes klienty se neseskupuje |
| `capacity_check` | zamítnuto, vrací objem přes všechny klienty |
| poznámka o prázdném výsledku | gate nahradí rozsah dat přes všechny klienty rozsahem dat klienta |

### Chování při chybě

- **Fail closed:** chybí politika, nejde ji načíst, neznámý `chat_id`,
  chat jiný než soukromý, výjimka v gate, chybí auditní log nebo do něj
  nejde zapsat. Ve všech případech zamítnuto, nástroj se nezavolá. Bez
  záznamu v auditu se nevydá nic.
- Zamítnutí vrátí krátkou hlášku bez cizích dat („Projekt není dostupný.
  Vaše projekty: …“). **Nikdy** nevypisuje projekty jiných klientů. Tím se
  zavře i únik přes chybovou hlášku z `tools.py:78-83`.
- Každé rozhodnutí (povoleno i zamítnuto) se zapíše do auditního logu: čas,
  služba, `chat_id`, nástroj, argumenty, rozhodnutí, důvod.

### Omezení a zbytkové riziko

- **n8n je důvěryhodný prostředník.** Kdo ovládne n8n, nastaví libovolné
  `chat_id` i typ chatu, včetně vlastníkova. Dostane tak všechna data.
  `owner_chat_ids` tím riziko nezvětšuje, protože i bez něj by prošel
  klienty jednoho po druhém. Snižuje M4, plně neřeší.
- **Oprávnění na úrovni klienta, ne osoby** (kap. 1.4). Kontaktní osoby
  téhož klienta vidí totéž.
- **Převzatý Telegram účet klienta** vidí data toho klienta. Platí pro
  každou službu s přihlášením. Řeší se rychlým odebráním `chat_id`
  z politiky (kap. 6).
- **Uvnitř dat klienta** gate injection (T3) nezastaví. Model může dát
  zavádějící text, ale jen o datech téhož klienta.
- Předpoklad: uzel MCP klienta v n8n umí nastavit hlavičku z dat triggeru.
  Ověří se při nasazení. Pokud to nejde, `chat_id` doplní malý HTTP proxy
  uzel před MCP.
- **Gate server nahrazuje původní MCP server z HW3**, nesmí běžet vedle
  něj. Původní server je bez kontroly volajícího; dokud běží, T4 zůstává
  otevřené (viz M3).

## 4.3 Ostatní opatření

| ID | Konkrétně | Chování při chybě | Zbytkové riziko |
|---|---|---|---|
| **M2** | Uzel „Allowlist“ hned za Telegram triggerem: `chat.type` musí být `private` a `chat.id` v seznamu, jinak se zpráva zahodí bez odpovědi. Seznam se generuje z `access.toml`, aby se dvě místa nerozešla. Limit 10 zpráv za minutu na `chat_id`. | neznámý odesílatel nedostane nic, ani chybovou hlášku | Je to druhá vrstva. Rozhoduje M1, kdyby někdo allowlist v n8n omylem smazal. |
| **M3** | V rozšíření neběží původní MCP server z HW3 (nahradí ho server s gate), REST API z HW2 ani .NET MCP proxy. MCP port zůstává publikovaný jen na loopback hostitele (agenti tam běží mimo docker síť) a bez tokenu vrací 401. Chat webhook n8n `public: false`. | služba, která není v compose, nemá cestu k DB | kontejner s tokenem `owner` vidí vše |
| **M4** | Heslo n8n z tajemství, ne výchozí. `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`. Bot token jen v n8n credential. LangFlow `AUTO_LOGIN=false`. Tokeny MCP po jednom na službu, rotace při podezření. | služba bez nastaveného tajemství nenastartuje | malware na hostiteli |
| **M5** | Každý klient při startu ověří `OLLAMA_BASE_URL` proti allowlistu (loopback, docker síť, privátní rozsahy). Jinak odmítne běžet. Ollama na stejném stroji nebo přes WireGuard, ne plain HTTP přes LAN. | start selže s hláškou, data neodejdou | vědomé přepsání allowlistu vlastníkem |
| **M6** | Importer bere jen očekávané sloupce, popis zkrátí na 200 znaků, zahodí sloupec s osobou (jména). V promptu jsou výsledky nástrojů označené jako data, ne pokyny. | řádek mimo schéma se přeskočí a zaloguje | Injection v popisu může zůstat. Rozhoduje M1, prompt je jen pomocná vrstva. |
| **M7** | n8n `EXECUTIONS_DATA_PRUNE=true`, maximální stáří 14 dní. Paměť konverzace jen posledních 10 zpráv. | — | data v zálohách disku |
| **M8** | Viz 4.4. | build nebo start selže, nic se nespustí | podvržený kód už v zamčené verzi; zero-day |

## 4.4 M8 · Supply chain

**Řetězec:** T9 → hranice B6 → co se z registru přijme a jak se to ověří →
V26–V37 (kap. 5) → zbytkové riziko níže.

Princip: do buildu i běhu se dostane jen to, co je **zamčené hashem nebo
digestem v gitu**. Nová verze přijde jen vědomou změnou, která projde
auditem a testem gate.

| Vrstva | Opatření | Při chybě | Stav |
|---|---|---|---|
| Python v image | `requirements.in` → `uv pip compile --generate-hashes` → `pip install --require-hashes --no-deps`. Server s gate má v procesu jen `mcp` a `uvicorn`. Spodní hranice `mcp>=2.2.0` (CVE-2026-59951). | nesedí hash nebo balíček mimo zámek → build selže | **zavedeno** (`HW3/mcp`, `HW2/api`) |
| Python projekty | `uv.lock` s hashi, `[tool.uv] exclude-newer = "7 days"` v každém `pyproject.toml`. Karanténa je v konfiguraci, ne na příkazové řádce: `--exclude-newer` z CLI se uloží do zámku a další `uv run` bez něj zámek potichu přeřeší. | novější verze se nevybere | **zavedeno** |
| Base image, n8n, LangFlow | Tag + digest (`python:3.12-slim@sha256:…`, `n8nio/n8n:2.38.3@sha256:…`). Aktualizace = nový digest v commitu. | jiný obsah pod tagem se nestáhne | **zavedeno** |
| n8n | Jen vestavěné uzly, `N8N_COMMUNITY_PACKAGES_ENABLED=false`. | community node nejde nainstalovat | **zavedeno** |
| NuGet | `nuget.config` vedle projektů: `<clear/>`, jen nuget.org, `packageSourceMapping` `*`. `RestorePackagesWithLockFile`, `restore --locked-mode`, v image `RestoreLockedMode=true`. | cizí zdroj se nepoužije; změna grafu → restore selže | **zavedeno** |
| Model | `OLLAMA_MODEL_DIGEST` v konfiguraci, `security/check_model.py` porovná s `/api/tags`. | jiný digest, chybějící digest nebo nedostupný server → kód 1, klient nemá startovat | **skript hotový**, napojení do startu pěti klientů při nasazení |
| Známé zranitelnosti | CI `supply-chain.yml` při každém push a každé pondělí: `pip-audit` nad zámky image i všemi `uv.lock`, `dotnet list package --vulnerable`, Trivy nad image z compose. Dependabot s cooldownem 7 dní pro uv, pip, NuGet, Docker, compose a GitHub Actions. | nález v Python/NuGet → CI červené; Trivy jen report, rozhoduje vlastník | **zavedeno** |
| Výjimky | Nález, který se netýká použité části balíčku, jde přijmout jen záznamem v `supply-chain-exceptions.toml`: adresář, balíček, verze, id, důvod, oprava, vlastník, expirace. CI ho předá jako `--ignore-vuln`. | vypršelá výjimka nebo jiná verze balíčku → test V37 selže | **zavedeno**, 1 výjimka (`litellm`, viz níže) |
| CI samo | Akce připnuté SHA commitu, Trivy digestem, `permissions: contents: read`. | — | **zavedeno** |
| Aktualizace | Jako každá změna (kap. 6.5): commit zámku nebo digestu, audit, test gate a test supply chain. | neprošlý test → nenasadí se | pravidlo |

**Proč to pro tenhle systém stačí:** nejhorší cestu (kód v procesu gate)
zavírají zamčené hashe a minimum závislostí v tom procesu. Model s
backdoorem je jen další forma T3. Gate je deterministický kód, takže ani
zlomyslný model nedostane víc než data klienta, za kterého se ptá.

**Přijatá výjimka `litellm` 1.83.0 v agentovi Pydantic AI** (do 2027-01-16):
14 nálezů, všechny v LiteLLM Proxy serveru (endpointy `/prompts/test`,
`/mcp-rest`, autentizace proxy). Agent proxy nespouští, `litellm` se načte
jen přes HW1 kvůli `build_system_prompt`. Novější `litellm` chce `openai<3`,
čímž stáhne `pydantic-ai-slim` zpět na verzi se zranitelnostmi v kódu, který
agent skutečně volá. Oprava: oddělit `build_system_prompt` v HW1 od `llm`.

**Otevřené: n8n a LangFlow.** Trivy (2026-10-16) hlásí v n8n 2.38.3 32
kritických nálezů s opravou (OpenSSH, `vm2`, `handlebars`, `shell-quote`),
v LangFlow 1.12.0 3 kritické (`PyJWT`, `chromadb` bez opravy). Novější n8n
(2.43.7, 2.44.3) vyšlo v den skenu, tedy uvnitř vlastní karantény. Před
spuštěním rozšíření: n8n na verzi starší 7 dní bez kritických nálezů,
znovu ověřit workflow (V14). LangFlow v rozšíření klientům nic
nevystavuje, jen vlastníkovi na loopbacku.

**Zbytkové riziko:**
- Lockfile zamkne i verzi, která už podvržená byla. Hash dokazuje
  totožnost, ne nevinnost. Snižuje to karanténa 7 dní a audit.
- Zero-day v zamčené verzi, dokud se neobjeví v databázi zranitelností.
- Digest modelu ověří, že jde o stejné váhy, ne že jsou čisté. Dopad
  omezuje M1.
- Vlastní kód nástrojů (`HW1/`) a gate (`security/`) chrání jen git
  a review. Podepsané commity se nevyžadují, autor je jeden.

## 4.5 Pokrytí hrozeb

| Hrozba | Hlavní opatření | Doplňkové | Zbytek po opatřeních |
|---|---|---|---|
| T2 | M1 | — | převzatý účet klienta |
| T1 | M1 | M2 | převzatý účet klienta |
| T4 | M1 | M3 | kompromitace n8n nebo tokenu `owner` |
| T3 | M1 (omezí dopad) | M6 | zavádějící text v datech téhož klienta |
| T5 | M5 | — | vědomá změna konfigurace |
| T6 | M4 | M3 | malware na hostiteli |
| T7 | M2 | — | zahlcení z povoleného účtu (limit na `chat_id`) |
| T8 | M7 | — | zálohy |
| T9 | M8 | M1 (omezí dopad modelu) | podvržená verze před karanténou, zero-day |
