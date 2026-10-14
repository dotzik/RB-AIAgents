# 7. Implementovaná mitigace s testem

[← Rozcestník](README.md)

## 7.1 Vazba na hrozbu

Implementováno je **M1 · autorizační gate v MCP serveru** (kap. 4.2). Řeší
prioritu 1 a 2 (T2 identita z promptu, T1 bot pro kohokoli) a zároveň T4
(přímé volání MCP), protože kontrola stojí v serveru, přes který jdou všichni
klienti.

## 7.2 Očekávaný výsledek (zapsáno před implementací a spuštěním)

Zapsáno 2026-10-14, než vznikl kód gate i testu.

**Syntetické prostředí:** databáze ze `seed.seed_database` (kotva 2026-08-31,
4 měsíce, `rng_seed=42`, fiktivní klienti) a jeden přidaný projekt `ACM2`
pro klienta Acme Corp. Klient tak má dva projekty a test filtrování seznamu
má smysl. Politika: `chat_id 1001 → Acme Corp`, `chat_id 2002 → Northwind
Trading`, služba `n8n-telegram` s rolí `client-proxy`, služba `owner-cli`
s rolí `owner`. Server běží na localhostu (uvicorn), test volá skutečným
MCP klientem přes HTTP. Model se nevolá.

| # | Případ | Očekávám |
|---|---|---|
| V1 | `1001`, `compute_invoice(ACME, 2026-08)` | povoleno; `billable_hours` = součet z DB pro `ACME`, fakturovatelné, srpen 2026; `client` = Acme Corp; audit `allow` |
| V2 | `1001`, `compute_invoice(NWND)` a `compute_invoice("Northwind")` | zamítnuto; odpověď neobsahuje `NWND`, `Northwind` ani sazbu `1350`; audit `deny` |
| V3 | `1001`, `query_time_entries` bez projektu | zamítnuto, žádný součet |
| V4 | `1001`, `summarize_by(dimension="client")` bez projektu; `capacity_check` | obojí zamítnuto |
| V5 | `1001`, projekt `XYZ` | zamítnuto; v odpovědi není žádné cizí id ani klient (`NWND`, `GLBX`, `INIT`, `INTR`, Northwind, Globex, Initech) |
| V6 | hlavička `1001`, argument `chat_id: "2002"` | argument se ignoruje: `ACME` povoleno, `NWND` zamítnuto |
| V7 | neznámé `chat_id 9999`; chybějící `chat_id` | zamítnuto |
| V8 | bez tokenu; špatný token | HTTP 401, nástroj neběží |
| V9 | soubor politiky chybí | HTTP 503 na každý požadavek (fail closed) |
| V10 | token `owner-cli`, `compute_invoice(NWND)` | povoleno; výsledek shodný s přímým voláním nástroje |
| V11 | `1001`, `list_projects` | přesně `{ACME, ACM2}` |
| V12 | `1001` se odebere z politiky za běhu serveru | další volání zamítnuto, bez restartu |

**Doplněno po kontrole (2026-10-14), zapsáno před opravou gate:** kontrola
našla další cestu úniku a dvě nepřesnosti v testu.

| # | Případ | Očekávám |
|---|---|---|
| V13 | `1001`, `compute_invoice(ACME, 2026-09)`; v DB je záznam Northwindu z 2026-09-30, Acme má data jen do srpna | povoleno, 0 hodin; `note` uvádí rozsah dat Acme, ne `2026-09-30` |
| V4 | navíc `tools/list` pro `1001` | `capacity_check` v seznamu není |

## 7.3 Implementace

Nový server v `security/`, HW1–HW3 se nemění. Z HW3 přebírá seznam nástrojů
a health check, nástroje volá stejně jako HW3 (`tools.call_tool`).

| Soubor | Co dělá |
|---|---|
| `src/timeagent_gate/policy.py` | načte politiku (TOML), ověří token (SHA-256, `hmac.compare_digest`), odvodí identitu z hlaviček |
| `src/timeagent_gate/gate.py` | rozhodnutí podle role a nástroje, projekt klienta jen mezi jeho projekty, zúžení `list_projects`, `tools/list` a poznámky o prázdném výsledku, auditní log |
| `src/timeagent_gate/server.py` | ASGI vrstva před `/mcp` (401 bez tokenu, 503 bez politiky) a gate v `on_call_tool` |
| `access.example.toml` | vzor politiky; skutečný `access.toml` je v `.gitignore` |
| `tests/conftest.py` | seed DB + projekt `ACM2` + záznam Northwindu mimo rozsah Acme, politika s náhodnými tokeny, server na volném portu, přepínač `--gate-off` |
| `tests/test_gate.py` | případy V0–V13 |

Gate klientovi předá nástroji už rozpoznané `id` projektu. Částečná shoda
názvu v `tools._resolve_project` tak nemůže trefit cizí projekt a chybová
hláška knihovny se k cizím projektům vůbec nedostane.

Knihovna při prázdném výsledku přidá poznámku s rozsahem dat přes celou
databázi (`tools.py:99-118`) a systémový prompt modelu velí ji zopakovat.
Klient by tak zjistil, do kdy se pracovalo pro jiné. Gate proto poznámku
pro klienta nahradí rozsahem jeho vlastních dat.

## 7.4 Spuštění

```bash
cd security
uv sync
uv run pytest -v
```

První `uv sync` stahuje i `litellm`, závislost knihovny nástrojů, a trvá
několik minut. Test nepotřebuje model, Docker ani síť mimo localhost.

## 7.5 Skutečný výstup

Běh 2026-10-14, Windows 11, Python 3.12.13:

```text
tests/test_gate.py::test_v0_bez_gate_cizi_data_uniknou PASSED            [  7%]
tests/test_gate.py::test_v1_klient_dostane_fakturu_za_vlastni_projekt PASSED [ 14%]
tests/test_gate.py::test_v2_cizi_projekt_je_zamitnut_bez_cizich_dat PASSED [ 21%]
tests/test_gate.py::test_v3_dotaz_bez_projektu_nesecte_vsechny_klienty PASSED [ 28%]
tests/test_gate.py::test_v4_souhrn_pres_klienty_a_kapacita_jsou_zamitnuty PASSED [ 35%]
tests/test_gate.py::test_v5_neexistujici_projekt_nevypise_cizi_projekty PASSED [ 42%]
tests/test_gate.py::test_v6_identita_v_argumentu_se_ignoruje PASSED      [ 50%]
tests/test_gate.py::test_v7_neznamy_nebo_chybejici_chat_id PASSED        [ 57%]
tests/test_gate.py::test_v8_bez_tokenu_a_se_spatnym_tokenem_401 PASSED   [ 64%]
tests/test_gate.py::test_v9_bez_politiky_vse_zamitnuto PASSED            [ 71%]
tests/test_gate.py::test_v10_vlastnik_vidi_vse_jako_bez_gate PASSED      [ 78%]
tests/test_gate.py::test_v11_seznam_projektu_jen_vlastni PASSED          [ 85%]
tests/test_gate.py::test_v12_revokace_plati_hned PASSED                  [ 92%]
tests/test_gate.py::test_v13_prazdny_vysledek_neprozradi_rozsah_cizich_dat PASSED [100%]

============================= 14 passed in 1.62s ==============================
```

Auditní záznamy z V2 (klient Acme žádá fakturu Northwindu id i názvem):

```json
{"ts": "2026-10-14T15:37:21.495+00:00", "service": "n8n-telegram", "role": "client-proxy", "chat_id": "1001", "client": "Acme Corp", "tool": "compute_invoice", "arguments": {"project": "NWND", "month": "2026-08"}, "decision": "deny", "reason": "project_not_allowed"}
{"ts": "2026-10-14T15:37:21.509+00:00", "service": "n8n-telegram", "role": "client-proxy", "chat_id": "1001", "client": "Acme Corp", "tool": "compute_invoice", "arguments": {"project": "Northwind", "month": "2026-08"}, "decision": "deny", "reason": "project_not_allowed"}
```

**Shoda s očekáváním (7.2):** všech třináct případů V1–V13 dopadlo tak, jak
bylo zapsáno předem.

### Kontrola, že test opravdu testuje gate

Zelený test sám nedokazuje, že kontrolu vykonává gate. Data by mohla chybět
z jiného důvodu. Proto dvě kontroly navíc, doplněné po prvním běhu:

1. **V0, kontrolní případ bez gate:** původní server z HW3 na stejný dotaz
   („faktura Northwind“) vydá data Northwindu bez jakékoli identity. Únik
   z T2 tedy v datech skutečně je.
2. **Běh s vypnutým gate:** přepínač `--gate-off` (v `tests/conftest.py`)
   nahradí rozhodnutí gate funkcí, která vše povolí, a vypne filtrování
   výstupu. Spuštění:

   ```bash
   uv run pytest --gate-off
   ```

   Výsledek: `9 failed, 5 passed`. Padly všechny případy, kde má gate
   zastavit cizí data (V2–V7, V11–V13), s cizími daty přímo ve výstupu:

   ```text
   FAILED test_v2 … {'project': 'NWND', … 'client': 'Northwind Trading', …}
   FAILED test_v4 … {'dimension': 'client', 'date_from': '2026-05-01', 'date_to': '2026-08-31', 'total_hours': 619.0, …}
   FAILED test_v5 … 'Projekt 'XYZ' neexistuje. Dostupné: ACME (Acme Corp), NWND (Northwind Trading), GLBX (Globex), INIT (Initech), …'
   FAILED test_v11 … Extra items in the left set: 'INIT', …
   FAILED test_v13 … 'Data jsou k dispozici od 2026-05-01 do 2026-09-30. …'
   ```

   V4 bez gate vrátí souhrn hodin přes všechny klienty. Prošly legitimní
   případy V0, V1, V10 a případy V8 a V9, které hlídá samostatná vrstva
   před `/mcp`, ne gate.

## 7.6 Proč důkaz odpovídá hrozbě

T2 je únik dat jiného klienta, ke kterému dojde, protože identitu určuje
text zprávy. Test proto:

- bere identitu jen z hlaviček, které v provozu nastaví n8n z Telegram
  updatu. Identitu podvrženou v argumentu (V6) ignoruje;
- nekontroluje text hlášky, ale **obsah odpovědi proti databázi**. Povolená
  faktura má hodiny shodné s nezávislým SQL dotazem (V1) a zamítnutá
  odpověď nesmí obsahovat žádné id, jméno ani sazbu cizího klienta (V2–V5);
- ověřuje i **auditní stopu**, tedy že rozhodnutí vzniklo v gate a s jakým
  důvodem;
- jde přes **skutečný MCP protokol přes HTTP**, stejnou cestou jako n8n
  a ostatní klienti. Proto pokrývá i T4: bez tokenu se k nástroji nedostane
  nikdo (V8);
- ověřuje **fail closed** (V9) a **revokaci bez restartu** (V12).

## 7.7 Co tento důkaz nepokrývá

- **n8n:** že workflow skutečně posílá `chat.id` v hlavičce a že MCP uzel
  hlavičku z dat triggeru umí nastavit. Ověří se při nasazení (kap. 4.2).
- **Telegram:** pravost `chat.id` stojí na důvěře v Telegram API a v bot token.
- **Model:** chování modelu se netestuje vůbec. Injection (T3) uvnitř dat
  téhož klienta zůstává.
- **Kompromitace n8n nebo tokenu `owner`:** gate jim věří.
- **Ostatní mitigace M2–M7:** jen plán ověření V14–V20.
- **Souběh s původním serverem:** gate chrání jen tehdy, když server z HW3
  bez gate neběží (M3, ověří V16).
- **Tokeny agentů a LangFlow:** dnes se k MCP připojují bez tokenu. Po
  nasazení gate musí každý posílat svůj token s rolí `owner`, jinak dostane
  401. Konfiguraci klientů test neověřuje.
- **REST API z HW2 a .NET proxy:** gate je nechrání, v rozšíření nemají běžet (M3).
- **Integrita auditního logu:** zápis je jen append do souboru, bez ochrany
  proti přepsání.
