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

Vlastník je u všech stejný: systém provozuje jeden člověk (dodavatel).
Rozdělení rolí v kapitole 6.

## 4.2 M1 · Autorizační gate v MCP serveru

**Řetězec:** T2 (identita z promptu) → hranice B2 a B3 → gate v MCP serveru →
testy V1–V12 (kap. 5) → zbytkové riziko níže.

**Proč v MCP serveru:** všech pět klientů volá nástroje přes něj. Kontrola
v n8n by chránila jen Telegram, kontrola v promptu nechrání nic. Gate je
deterministický kód před SQL dotazem, model ho nemůže přesvědčit.

### Důvěryhodné vstupy

| Vstup | Odkud | Proč mu věřit |
|---|---|---|
| Identita služby | hlavička `Authorization: Bearer <token>`, každý klient MCP má vlastní token | token zná jen daná služba, porovnání v konstantním čase |
| Identita uživatele | hlavička `X-Timeagent-Chat-Id`, nastaví ji n8n z `message.chat.id` Telegram updatu | hodnota pochází z Telegram API, ne z textu zprávy; model hlavičky nevidí ani nenastaví |
| Oprávnění | soubor politiky `access.toml`: služba → role, `chat_id` → klient | spravuje ho jen vlastník, změna přes git |
| Vazba projekt → klient | databáze (`projects.client`) | zdroj pravdy o datech |

**Nedůvěryhodné:** všechny argumenty nástrojů. Identita v argumentu
(`chat_id`, `client`) se ignoruje.

### Pravidla

| Role | Kdo | Co smí |
|---|---|---|
| `owner` | CLI agenti vlastníka, LangFlow vlastníka | vše jako dnes |
| `client-proxy` | n8n Telegram workflow | jen za ověřeného klienta podle `chat_id`, viz níže |
| bez role | neznámý nebo chybějící token | nic, HTTP 401 ještě před MCP |

Klient přes `client-proxy`:

| Nástroj | Pravidlo |
|---|---|
| `list_projects` | vrátí jen projekty klienta |
| `query_time_entries`, `compute_invoice`, `summarize_by` | `project` povinný; gate ho vyhodnotí **jen mezi projekty klienta**, jinak zamítne |
| `summarize_by(dimension="client")` | zamítnuto, přes klienty se neseskupuje |
| `capacity_check` | zamítnuto, vrací objem přes všechny klienty |

### Chování při chybě

- **Fail closed:** chybí politika, nejde ji načíst, neznámý `chat_id`,
  výjimka v gate. Ve všech případech zamítnuto, nástroj se nezavolá.
- Zamítnutí vrátí krátkou hlášku bez cizích dat („Projekt není dostupný.
  Vaše projekty: …“). **Nikdy** nevypisuje projekty jiných klientů. Tím se
  zavře i únik přes chybovou hlášku z `tools.py:78-83`.
- Každé rozhodnutí (povoleno i zamítnuto) se zapíše do auditního logu: čas,
  služba, `chat_id`, nástroj, argumenty, rozhodnutí, důvod.

### Omezení a zbytkové riziko

- **n8n je důvěryhodný prostředník.** Kdo ovládne n8n, nastaví libovolné
  `chat_id`. Snižuje M4, plně neřeší.
- **Převzatý Telegram účet klienta** vidí data toho klienta. Platí pro
  každou službu s přihlášením. Řeší se rychlým odebráním `chat_id`
  z politiky (kap. 6).
- **Uvnitř dat klienta** gate injection (T3) nezastaví. Model může dát
  zavádějící text, ale jen o datech téhož klienta.
- Předpoklad: uzel MCP klienta v n8n umí nastavit hlavičku z dat triggeru.
  Ověří se při nasazení. Pokud to nejde, `chat_id` doplní malý HTTP proxy
  uzel před MCP.

## 4.3 Ostatní opatření

| ID | Konkrétně | Chování při chybě | Zbytkové riziko |
|---|---|---|---|
| **M2** | Uzel „Allowlist“ hned za Telegram triggerem: `chat.id` musí být v seznamu, jinak se zpráva zahodí bez odpovědi. Limit 10 zpráv za minutu na `chat_id`. | neznámý odesílatel nedostane nic, ani chybovou hlášku | Je to druhá vrstva. Rozhoduje M1, kdyby někdo allowlist v n8n omylem smazal. |
| **M3** | V rozšíření neběží REST API z HW2 ani .NET MCP proxy. MCP port se nepublikuje na hostitele, klienti na hostiteli jdou přes token. Chat webhook n8n `public: false`. | služba, která není v compose, nemá cestu k DB | kontejner s tokenem `owner` vidí vše |
| **M4** | Heslo n8n z tajemství, ne výchozí. `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`. Bot token jen v n8n credential. LangFlow `AUTO_LOGIN=false`. Tokeny MCP po jednom na službu, rotace při podezření. | služba bez nastaveného tajemství nenastartuje | malware na hostiteli |
| **M5** | Každý klient při startu ověří `OLLAMA_BASE_URL` proti allowlistu (loopback, docker síť, privátní rozsahy). Jinak odmítne běžet. Ollama na stejném stroji nebo přes WireGuard, ne plain HTTP přes LAN. | start selže s hláškou, data neodejdou | vědomé přepsání allowlistu vlastníkem |
| **M6** | Importer bere jen očekávané sloupce, popis zkrátí na 200 znaků, zahodí sloupec s osobou (jména). V promptu jsou výsledky nástrojů označené jako data, ne pokyny. | řádek mimo schéma se přeskočí a zaloguje | Injection v popisu může zůstat. Rozhoduje M1, prompt je jen pomocná vrstva. |
| **M7** | n8n `EXECUTIONS_DATA_PRUNE=true`, maximální stáří 14 dní. Paměť konverzace jen posledních 10 zpráv. | — | data v zálohách disku |

## 4.4 Pokrytí hrozeb

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
