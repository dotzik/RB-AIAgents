# 6. Provoz a governance

[← Rozcestník](README.md)

## 6.1 Role a vlastnictví

Systém provozuje jeden člověk, dodavatel. Role jsou proto sloučené, ale
rozhodnutí jsou pojmenovaná zvlášť.

| Role | Kdo | Odpovídá za |
|---|---|---|
| Vlastník systému a rizika | dodavatel | přijetí zbytkových rizik (kap. 3), nasazení, rozhodnutí při incidentu |
| Správce politiky | dodavatel | `access.toml`: přidání a odebrání klienta, tokeny služeb |
| Kontaktní osoba klienta | určí klient | hlásí ztrátu nebo převzetí svého Telegram účtu |

**Přijatá rizika** (vlastník, 2026-10-14): T7 s limitem zpráv; zbytkové T3
uvnitř dat téhož klienta; důvěra v n8n jako prostředníka (kap. 4.2).

## 6.2 Logy a jejich ochrana

| Log | Obsah | Kde | Retence | Ochrana |
|---|---|---|---|---|
| **Audit gate** | čas, služba, `chat_id`, klient, nástroj, argumenty, rozhodnutí, důvod | `TIMEAGENT_AUDIT_LOG`, JSON lines | 12 měsíců (podklad k fakturaci a sporům) | soubor mimo kontejnery n8n a LangFlow, zápis jen MCP server; denní kopie mimo hostitele |
| Historie běhů n8n | dotazy a odpovědi klientů | volume n8n | 14 dní (M7) | přístup jen přes přihlášení do n8n |
| Access log uvicorn | HTTP požadavky na `/mcp` | stdout kontejneru | rotace dockeru | — |

Audit neobsahuje výsledky nástrojů (hodiny, částky), jen co kdo chtěl a jak
gate rozhodl. Únik logu tak neprozradí data klientů. `chat_id` je ale
osobní údaj, proto omezená retence.

## 6.3 Signály pro triage

| Signál (z auditu) | Co může znamenat | Priorita |
|---|---|---|
| `deny` s `project_not_allowed` od jednoho `chat_id`, ≥ 3 za hodinu | klient zkouší cizí projekty, nebo injection (T2, T3) | vysoká |
| `unauthenticated` na `/mcp` | někdo v síti volá MCP bez tokenu (T4) | vysoká |
| `unknown_chat_id` opakovaně | cizí účet píše botovi, allowlist v n8n selhal (T1, M2) | střední |
| `policy_unavailable` | výpadek politiky, služba stojí (fail closed) | střední, provozní |
| `allow` od klienta mimo obvyklou dobu nebo v objemu > 10× průměru | převzatý účet klienta | střední |

Kontrola: denní skript nad auditem, u vysoké priority zpráva vlastníkovi.

## 6.4 Containment a návrat do provozu

| Situace | Okamžitý krok | Návrat |
|---|---|---|
| Podezření na převzatý účet klienta | odebrat `chat_id` z `access.toml`, platí hned bez restartu (ověřeno V12) | nové `chat_id` po ověření s klientem jiným kanálem |
| Únik tokenu služby | smazat hash tokenu v politice, služba dostane 401 | nový token, hash do politiky, záznam do gitu |
| Kompromitace n8n | zastavit kontejner n8n; MCP a data zůstávají chráněné tokenem | obnova workflow z gitu, nové heslo, nový bot token přes BotFather |
| Únik dat jinému klientovi | zastavit bot; z auditu zjistit, kdo co dostal | oprava, regresní test pro daný případ, informovat dotčeného klienta |

Po incidentu: případ se přidá do testu gate jako nový V-případ, aby se
nevrátil.

## 6.5 Změnové řízení

- Politika, kód gate i compose jsou v gitu. Změnu politiky (nový klient)
  dělá vlastník commitem.
- **Test gate (V0–V12) musí projít před každou změnou** nástrojů, gate nebo
  MCP serveru. Neprošlý test blokuje nasazení.
- Nový nástroj je pro klienty zakázaný, dokud se výslovně nepřidá do
  `CLIENT_TOOLS` s testem.
- Změna modelu nebo `OLLAMA_BASE_URL` se ověří proti allowlistu (M5).

## 6.6 Regulace

| Předpis | Relevance | Co z toho plyne |
|---|---|---|
| **GDPR** | ano. Osobní údaje: Telegram `chat_id` kontaktních osob, jména v popisech a v exportu docházky | Minimalizace: importer zahodí sloupec s osobou (M6). Retence: audit 12 měsíců, n8n 14 dní (M7). Model běží lokálně, bez předání třetí straně (M5). Kontaktní osoby dostanou informaci o zpracování při registraci. |
| **AI Act** | minimální riziko | Systém nespadá do zakázaných praktik ani do vysoce rizikových oblastí z přílohy III: jen odpovídá na dotazy nad výkazy, o nikom nerozhoduje. Platí povinnost transparentnosti čl. 50: bot v první zprávě řekne, že je AI asistent a že čísla počítají nástroje. |
| **NDA s klienty** | ano | Hlavní důvod priority T2. Data jednoho klienta nesmí vidět jiný klient (M1). |

## 6.7 Čerstvost důkazů

| Důkaz | Stav | Kdy obnovit |
|---|---|---|
| Test gate V0–V12 | 2026-10-14, 13/13 prošlo | při každé změně, minimálně před nasazením |
| Ruční ověření V13–V19 | zatím nezískáno | při nasazení na Proxmox |
| Revize threat modelu | 2026-10-14 | při přidání nového zdroje dat, nového kanálu nebo při publikování mimo domácí síť |
