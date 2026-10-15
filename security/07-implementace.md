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

**Doplněno po kontrole logiky (2026-10-15), zapsáno před úpravou gate:**
kontrola našla tři mezery v návrhu. V Telegram skupině je `chat.id` id
skupiny, takže data klienta by viděli všichni její členové. Vlastník by po
nasazení gate přes Telegram nedostal nic, protože služba `n8n-telegram` má
jen roli `client-proxy`. Bez nastaveného auditního logu gate tiše neloguje.
Čísla V21–V25 navazují na ruční ověření V14–V20 (kap. 5.2).

| # | Případ | Očekávám |
|---|---|---|
| V21 | `1001` s typem chatu `group`, `supergroup`, `channel` nebo bez typu | zamítnuto `chat_not_private`, žádná data; s `private` povoleno |
| V22 | `chat_id 7007` z `owner_chat_ids`, soukromý chat, `compute_invoice(NWND)` a `capacity_check` | povoleno, výsledek shodný s přímým voláním; audit `role: owner`, `chat_id: 7007` |
| V23 | `7007` ze skupiny | zamítnuto `chat_not_private` |
| V24 | `TIMEAGENT_AUDIT_LOG` není nastavený | HTTP 503 na každý požadavek, nástroj neběží |
| V25 | `1001`, `compute_invoice("Acme —")` (část názvu sedí na `ACME` i `ACM2`) | zamítnuto `project_ambiguous`, nabídne oba vlastní projekty, žádná cizí data |

## 7.3 Implementace

Nový server v `security/`, HW1–HW3 se nemění. Z HW3 přebírá seznam nástrojů
a health check, nástroje volá stejně jako HW3 (`tools.call_tool`).

| Soubor | Co dělá |
|---|---|
| `src/timeagent_gate/policy.py` | načte politiku (TOML), ověří token (SHA-256, `hmac.compare_digest`), odvodí identitu z hlaviček; identitu uzná jen ze soukromého chatu, `owner_chat_ids` → role `owner` |
| `src/timeagent_gate/gate.py` | rozhodnutí podle role a nástroje, projekt klienta jen mezi jeho projekty, zúžení `list_projects`, `tools/list` a poznámky o prázdném výsledku, povinný auditní log |
| `src/timeagent_gate/server.py` | ASGI vrstva před `/mcp` (401 bez tokenu, 503 bez politiky nebo bez auditu) a gate v `on_call_tool` |
| `access.example.toml` | vzor politiky; skutečný `access.toml` je v `.gitignore` |
| `tests/conftest.py` | seed DB + projekt `ACM2` + záznam Northwindu mimo rozsah Acme, politika s náhodnými tokeny, server na volném portu, přepínač `--gate-off` |
| `tests/test_gate.py` | případy V0–V13 a V21–V25 |

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

Běh 2026-10-15, Windows 11, Python 3.12.13:

```text
tests/test_gate.py::test_v0_bez_gate_cizi_data_uniknou PASSED            [  5%]
tests/test_gate.py::test_v1_klient_dostane_fakturu_za_vlastni_projekt PASSED [ 10%]
tests/test_gate.py::test_v2_cizi_projekt_je_zamitnut_bez_cizich_dat PASSED [ 15%]
tests/test_gate.py::test_v3_dotaz_bez_projektu_nesecte_vsechny_klienty PASSED [ 21%]
tests/test_gate.py::test_v4_souhrn_pres_klienty_a_kapacita_jsou_zamitnuty PASSED [ 26%]
tests/test_gate.py::test_v5_neexistujici_projekt_nevypise_cizi_projekty PASSED [ 31%]
tests/test_gate.py::test_v6_identita_v_argumentu_se_ignoruje PASSED      [ 36%]
tests/test_gate.py::test_v7_neznamy_nebo_chybejici_chat_id PASSED        [ 42%]
tests/test_gate.py::test_v8_bez_tokenu_a_se_spatnym_tokenem_401 PASSED   [ 47%]
tests/test_gate.py::test_v9_bez_politiky_vse_zamitnuto PASSED            [ 52%]
tests/test_gate.py::test_v10_vlastnik_vidi_vse_jako_bez_gate PASSED      [ 57%]
tests/test_gate.py::test_v11_seznam_projektu_jen_vlastni PASSED          [ 63%]
tests/test_gate.py::test_v12_revokace_plati_hned PASSED                  [ 68%]
tests/test_gate.py::test_v13_prazdny_vysledek_neprozradi_rozsah_cizich_dat PASSED [ 73%]
tests/test_gate.py::test_v21_identitu_uzna_jen_soukromy_chat PASSED      [ 78%]
tests/test_gate.py::test_v22_vlastnik_pres_telegram_vidi_vse PASSED      [ 84%]
tests/test_gate.py::test_v23_vlastnik_ve_skupine_je_zamitnut PASSED      [ 89%]
tests/test_gate.py::test_v24_bez_auditu_nic_nevyda PASSED                [ 94%]
tests/test_gate.py::test_v25_nejednoznacny_nazev_jen_mezi_vlastnimi PASSED [100%]

============================= 19 passed in 1.41s ==============================
```

Auditní záznamy z V2 (klient Acme žádá fakturu Northwindu id i názvem):

```json
{"ts": "2026-10-15T16:37:23.261+00:00", "service": "n8n-telegram", "role": "client-proxy", "chat_id": "1001", "client": "Acme Corp", "chat_type": "private", "tool": "compute_invoice", "arguments": {"project": "NWND", "month": "2026-08"}, "decision": "deny", "reason": "project_not_allowed"}
{"ts": "2026-10-15T16:37:23.291+00:00", "service": "n8n-telegram", "role": "client-proxy", "chat_id": "1001", "client": "Acme Corp", "chat_type": "private", "tool": "compute_invoice", "arguments": {"project": "Northwind", "month": "2026-08"}, "decision": "deny", "reason": "project_not_allowed"}
```

Z V21 (týž klient ze skupiny, potom ze soukromého chatu) a V22 (vlastník
přes Telegram):

```json
{"ts": "2026-10-15T16:37:23.353+00:00", "service": "n8n-telegram", "role": "client-proxy", "chat_id": "1001", "client": null, "chat_type": "group", "tool": "compute_invoice", "arguments": {"project": "ACME", "month": "2026-08"}, "decision": "deny", "reason": "chat_not_private"}
{"ts": "2026-10-15T16:37:23.493+00:00", "service": "n8n-telegram", "role": "client-proxy", "chat_id": "1001", "client": "Acme Corp", "chat_type": "private", "tool": "compute_invoice", "arguments": {"project": "ACME", "month": "2026-08"}, "decision": "allow", "reason": "client_scoped"}
{"ts": "2026-10-15T16:37:23.591+00:00", "service": "n8n-telegram", "role": "owner", "chat_id": "7007", "client": null, "chat_type": "private", "tool": "capacity_check", "arguments": {"month": "2026-08"}, "decision": "allow", "reason": "owner"}
```

**Shoda s očekáváním (7.2):** všech osmnáct případů V1–V13 a V21–V25
dopadlo tak, jak bylo zapsáno předem. U V25 se očekávání opravilo ještě
před spuštěním: `"Acme"` se shoduje s id `ACME` (bez ohledu na velikost
písmen), nejednoznačný je až `"Acme —"`.

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

   Výsledek: `12 failed, 7 passed`. Padly všechny případy, kde má gate
   zastavit data (V2–V7, V11–V13, V21, V23, V25), s daty přímo ve výstupu:

   ```text
   FAILED test_v2 … {'project': 'NWND', … 'client': 'Northwind Trading', …}
   FAILED test_v4 … {'dimension': 'client', 'date_from': '2026-05-01', 'date_to': '2026-08-31', 'total_hours': 619.0, …}
   FAILED test_v5 … 'Projekt 'XYZ' neexistuje. Dostupné: ACME (Acme Corp), NWND (Northwind Trading), GLBX (Globex), INIT (Initech), …'
   FAILED test_v11 … Extra items in the left set: 'INIT', …
   FAILED test_v13 … 'Data jsou k dispozici od 2026-05-01 do 2026-09-30. …'
   FAILED test_v21 … group … {'project': 'ACME', … 'client': 'Acme Corp', 'month': '2026-08', …}
   FAILED test_v23 … {'project': 'NWND', … 'client': 'Northwind Trading', …}
   ```

   V4 bez gate vrátí souhrn hodin přes všechny klienty, V21 vydá fakturu
   Acme do skupiny. V25 bez gate padá na chybějícím zamítnutí, ne na úniku:
   hláška knihovny o nejednoznačnosti tu náhodou vypíše jen projekty Acme.
   Prošly legitimní případy V0, V1, V10, V22 a případy V8, V9 a V24, které
   hlídá samostatná vrstva před `/mcp`, ne gate.

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
- uzná identitu **jen ze soukromého chatu** (V21, V23), protože ve skupině
  `chat.id` neoznačuje člověka;
- ověřuje **fail closed** (V9, V24: bez politiky nebo bez auditu se nevydá
  nic) a **revokaci bez restartu** (V12).

## 7.7 Co tento důkaz nepokrývá

- **n8n:** že workflow skutečně posílá `chat.id` a `chat.type` v hlavičkách
  a že MCP uzel hlavičky z dat triggeru umí nastavit. Ověří se při nasazení
  (kap. 4.2, V14).
- **Oprávnění jednotlivých osob:** gate rozlišuje klienty, ne lidi uvnitř
  klienta (kap. 1.4).
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
  proti přepsání. Test ověřuje, že bez logu se nic nevydá (V24), ne že log
  nejde zpětně upravit.
