# Bezpečnostní návrh: timeagent pro klienty přes Telegram

Závěrečný projekt kurzu *Security for AI* (seai-rdcz-1). Systém je timeagent
ve finálním stavu HW3: MCP server nad nástroji a pět klientů nad ním
(tři frameworkoví agenti, n8n s Telegram botem a LangFlow). Návrh řeší
plánované rozšíření: klient se přes Telegram bota zeptá na své odpracované
hodiny a podklad k faktuře.

HW1 jako aplikace (CLI, vlastní ReAct smyčka, LiteLLM) je mimo rozsah.
Z HW1 se používá jen knihovna nástrojů a databáze (`HW1/src/timeagent/tools.py`
a `db.py`), kterou MCP server importuje. Odkazy do `HW1/` míří na ni.


## Shrnutí

- **Systém:** agent nad výkazy odpracovaného času. Pět read-only nástrojů nad
  SQLite, vystavených přes MCP server. Ten používá pět klientů: n8n
  s Telegram botem, LangFlow a tři frameworkoví agenti. Model je lokální
  Ollama.
- **Rozšíření:** botu dnes píše jen vlastník. Nově ho mají používat
  i klienti, každý jen pro svá data.
- **Největší riziko:** nástroje identitu neznají. Projekt vybírá model podle
  textu zprávy, takže klient A se dostane k hodinám, sazbám a popisům
  práce klienta B. Stačí, když se zeptá.
- **Klíčová mitigace (implementovaná v kap. 7):** autorizační gate v MCP
  serveru. Identitu odvodí z ověřeného Telegram `chat_id`, nikdy z promptu ani
  z argumentu nástroje, a každý nástroj omezí na projekty dané identity.
- **Důkaz:** test přes skutečný MCP protokol nad syntetickými daty, 14/14
  prošlo. S vypnutým gate (`--gate-off`) padá všech 9 případů, kde má gate
  zastavit cizí data, a cizí data jsou přímo ve výstupu.

```bash
cd security && uv sync && uv run pytest -v
```

## Kde co najdete

Členění odpovídá hodnoticí tabulce zadání, jedna oblast = jeden soubor.

| # | Oblast hodnocení | Soubor | Stav |
|---|---|---|---|
| 1 | Kontext a architektura | [01-architektura.md](01-architektura.md) | hotovo |
| 2 | Threat model | [02-threat-model.md](02-threat-model.md) | hotovo |
| 3 | Prioritizace rizik | [03-prioritizace.md](03-prioritizace.md) | hotovo |
| 4 | Návrh mitigací | [04-mitigace.md](04-mitigace.md) | hotovo |
| 5 | Plán ověření | [05-overeni.md](05-overeni.md) | hotovo |
| 6 | Provoz a governance | [06-provoz-governance.md](06-provoz-governance.md) | hotovo |
| 7 | Implementovaná mitigace s testem | [07-implementace.md](07-implementace.md) | hotovo, test prošel |
