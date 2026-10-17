# 5. Plán ověření

[← Rozcestník](README.md)

Účinek se ověřuje na **stavu a datech**, ne na textu modelu. Věta „akce byla
zablokována“ od modelu není důkaz. Důkazem je odpověď serveru, obsah vrácených
dat porovnaný s databází a záznam v auditním logu.

## 5.1 M1 · Gate (automatický test, kap. 7)

Prostředí: syntetická DB ze `timeagent seed` (fiktivní klienti Acme, Northwind,
Globex, Initech, Interní). MCP server s gate běží na localhostu, test volá
nástroje **skutečným MCP klientem**. Model se nevolá, rozhoduje jen gate.

Identity v testu: klient A = `chat_id` přiřazené k Acme, klient B = Northwind.

**V0 je kontrolní případ:** původní server z HW3 bez gate na dotaz „faktura
Northwind“ data vydá. Únik tedy v datech je a zelené zamítnutí znamená, že
ho zastavil gate, ne že data chybí.

Typy: *legitimní* = klient má dostat data; *zakázaný* = odpověď nesmí
obsahovat cizí data. V11 je legitimní dotaz, ale ověřuje filtrování: bez
gate by seznam obsahoval cizí projekty.

| # | Typ | Vstup | Očekávaný výsledek | Jak se ověří |
|---|---|---|---|---|
| V1 | legitimní | klient A, `compute_invoice` za vlastní projekt | povoleno, data vrácena | hodiny = součet z DB pro ten projekt; audit `allow` |
| V2 | **zakázaný** | klient A, `compute_invoice` za projekt Northwindu | zamítnuto | v odpovědi není id, název ani hodiny projektu Northwindu; audit `deny` |
| V3 | zakázaný | klient A, `query_time_entries` bez projektu | zamítnuto | odpověď bez součtu přes klienty |
| V4 | zakázaný | klient A, `summarize_by(dimension="client")` bez projektu a `capacity_check` | zamítnuto; `capacity_check` není ani v `tools/list` | odpověď bez cizích klientů |
| V5 | zakázaný | klient A, neexistující projekt | zamítnuto | hláška nevypíše žádný cizí projekt (bez gate je vypíše, `tools.py:78-83`) |
| V6 | zakázaný | klient A, v argumentu `chat_id` klienta B | argument ignorován, vidí jen svá data | rozhodnutí podle hlavičky |
| V7 | chybový | neznámý `chat_id` / chybí `chat_id` | zamítnuto | žádná data; audit `deny` s důvodem |
| V8 | chybový | chybí token / špatný token | HTTP 401 | nástroj se nezavolá |
| V9 | chybový | soubor politiky chybí | vše zamítnuto (fail closed) | žádná data |
| V10 | legitimní | token `owner`, libovolný nástroj | povoleno jako dnes | regrese, výsledek = volání bez gate |
| V11 | legitimní | klient A, `list_projects` | jen projekty Acme | seznam = projekty Acme z DB |
| V12 | revokace | `chat_id` klienta A se za běhu odebere z politiky | další volání zamítnuto, bez restartu | žádná data po revokaci |
| V13 | zakázaný | klient A, vlastní projekt za měsíc bez dat | povoleno, nula a poznámka | poznámka uvádí rozsah dat jen z projektů Acme, ne datum záznamu Northwindu mimo něj |
| V21 | zakázaný | klient A ze skupiny, supergroup, kanálu nebo bez typu chatu | zamítnuto; ze soukromého chatu povoleno | žádná data; audit `deny`, `chat_not_private` |
| V22 | legitimní | vlastník přes Telegram (`owner_chat_ids`), `compute_invoice` cizího projektu a `capacity_check` | povoleno | výsledek = volání bez gate; audit `role: owner` s jeho `chat_id` |
| V23 | zakázaný | vlastník ze skupiny | zamítnuto | žádná data |
| V24 | chybový | auditní log není nastavený | HTTP 503 | nástroj se nezavolá ani pro `owner` |
| V25 | zakázaný | klient A, část názvu, která sedí na dva jeho projekty | zamítnuto jako nejednoznačné | hláška nabídne jen vlastní projekty |

**Proč to odpovídá hrozbě:** T2 je únik dat jiného klienta. Test proto
kontroluje obsah odpovědi proti databázi (cizí data nesmí být nikde ve
výsledku), ne jen návratový kód. Nástroje jsou read-only, takže zakázaný
„side effect“ je právě předání dat.

## 5.2 Ostatní opatření (ruční ověření při nasazení)

| # | Opatření | Zakázaný případ | Legitimní případ | Očekávaný výsledek |
|---|---|---|---|---|
| V14 | M2 | zpráva z účtu mimo allowlist; zpráva ze skupiny, kde je povolený účet | zpráva z povoleného účtu v soukromém chatu | cizí i skupina bez odpovědi, v n8n běh končí v uzlu Allowlist; povolený dostane odpověď; n8n posílá na MCP `chat.id` i `chat.type` |
| V15 | M2 | 15 zpráv za minutu | 3 zprávy | od 11. zprávy zahozeno |
| V16 | M3 | `curl` na MCP z hostitele bez tokenu; port REST API; port původního MCP serveru HW3 | volání přes n8n | 401 / spojení odmítnuto; n8n funguje |
| V17 | M4 | přihlášení do n8n výchozím heslem; LangFlow bez přihlášení; Code node čte `$env` | přihlášení správným heslem | odmítnuto ve všech třech |
| V18 | M5 | `OLLAMA_BASE_URL` na veřejnou adresu | adresa v docker síti | klient nenastartuje / nastartuje |
| V19 | M6 | CSV s popisem 5 000 znaků a s instrukcí | běžný export | popis zkrácen; přes M1 se instrukce neprojeví mimo data klienta |
| V20 | M7 | běh starší 14 dní | běh dnes | starý smazán |
| V26 | M8 | instalace ze zámku, kde jsou u `mcp` změněné **všechny** hashe (pip bere libovolný z uvedených) | nezměněný zámek | **získáno**: `THESE PACKAGES DO NOT MATCH THE HASHES`, exit 1 / všechny tři image se postaví a Python servery vrátí `/health` 200 |
| V27 | M8 | `mcp==2.1.1` v závislostech | aktuální zámky | **získáno**: `pip-audit` hlásí CVE-2026-59951 / po opravě všech 7 zámků bez nálezu (1 přijatá výjimka) |
| V28 | M8 | `OLLAMA_MODEL_DIGEST` jiného modelu; chybí digest; server nedostupný | správný digest | **získáno**: `STOP`, exit 1 ve všech třech / `OK`, exit 0 (proti Sparku) |
| V29 | M8 | `restore --locked-mode` po změně verze v `.csproj` | beze změny | **získáno**: `NU1004 … lock file is inconsistent` / restore jen z nuget.org, 6/6 testů .NET |
| V30 | M8 | sken image n8n a LangFlow | — | **získáno, nesplněno**: n8n 32 kritických, LangFlow 3 (kap. 4.4) |
| V31–V37 | M8 | automatický test `tests/test_supply_chain.py`: každý `FROM` a `image:` s digestem, každý řádek zámku image s hashem a `--require-hashes` v Dockerfile, `mcp` všude ≥ opravené verze, NuGet lockfile a jen nuget.org, n8n bez community uzlů, výjimky platné a navázané na verzi | — | **získáno**: 10/10, v CI při každém push |

## 5.3 Evidence: plánovaná vs. získaná

| Opatření | Stav evidence |
|---|---|
| M1 | **získáno v kap. 7**: výstup testu V0–V13 a V21–V25 a běh s vypnutým gate |
| M8 (V26–V29, V31–V37) | **získáno 2026-10-16**, viz tabulka výše; test supply chain v CI. Výchozí audit: `pip-audit` nad `security/uv.lock` (84 balíčků, s hashi) bez nálezu, `mcp` 2.3.0. Nad `HW3/mcp/requirements.txt` nález CVE-2026-59951 v `mcp==2.1.1`; gate má proto spodní hranici `mcp>=2.2.0`. `dotnet list package --vulnerable --include-transitive` nad oběma .NET projekty bez nálezu. Sken image (V30) získán, nesplněno |
| M2–M7 | plánovaná, ověří se při nasazení na Proxmox podle V14–V20 |
| M8, zbytek | napojení `check_model.py` do startu klientů a upgrade n8n, ověří se při nasazení |

Regresní pravidlo: test M1 a test supply chain musí projít před každou změnou nástrojů, politiky
nebo MCP serveru. Neprošlý test blokuje nasazení.
