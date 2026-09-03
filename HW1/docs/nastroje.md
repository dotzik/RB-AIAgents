# Reference nástrojů

Nástroj je obyčejná Python funkce v [`tools.py`](../src/timeagent/tools.py), která
bere typované parametry a vrací `dict`. Model funkce nevolá přímo — dostane jen
jejich JSON schémata a vybírá jméno a hodnoty. SQL nepíše ani nevidí; proč, je
v [architektura.md](architektura.md).

Všechny nástroje čtou přes read-only spojení. Datové typy odpovídají schématu
v [instalace.md](instalace.md).

## Společná pravidla

**Formáty.** Data jsou vždy `YYYY-MM-DD`, měsíce `YYYY-MM`. Měsíc se ve výstupu
normalizuje, takže vstup `2026-8` vrátí `2026-08`.

**Projekt** se hledá nejdřív podle přesného ID (bez ohledu na velikost písmen),
pak podle části názvu nebo jména klienta. `acme`, `ACME`, `Acme Corp`
i `platforma` vedou na tentýž projekt. Když vzor odpovídá víc projektům, nástroj
skončí chybou a vypíše kandidáty. Znaky `%` a `_` se berou doslova.

**Chyby se nevyhazují, ale vrací** jako `{"error": "..."}`. Model tak dostane
zpětnou vazbu ve tvaru, se kterým umí pracovat, a může si opravit argumenty.

```json
{"error": "Projekt 'Nexus' neexistuje. Dostupné: ACME (Acme Corp), NWND (Northwind Trading), GLBX (Globex), INIT (Initech), INTR (Interní)"}
```

**Narovnání argumentů.** Menší modely posílají všechno jako řetězce. Než se
nástroj zavolá, hodnoty se podle typu ve schématu srovnají: `"true"` na `True`,
`"160"` na `160.0`, `"null"` nebo prázdný řetězec na vynechaný parametr.

---

## list_projects

Seznam projektů včetně klientů a sazeb. Model ho volá, když nezná přesné jméno.

| Parametr | Typ | Povinný | Výchozí | Význam |
|---|---|---|---|---|
| `active_only` | boolean | ne | `false` | jen aktivní projekty |

```python
list_projects(active_only=True)
```

```json
{
  "count": 4,
  "projects": [
    {"id": "ACME", "name": "Acme — platforma objednávek", "client": "Acme Corp",
     "hourly_rate": 1500.0, "currency": "CZK", "active": 1},
    {"id": "GLBX", "name": "Globex — mobilní aplikace", "client": "Globex",
     "hourly_rate": 1800.0, "currency": "CZK", "active": 1}
  ]
}
```

Chybové stavy: žádné kromě chybějící databáze.

---

## query_time_entries

Součet odpracovaných hodin za období. Vrací agregát a vzorek záznamů — celý výpis
by zbytečně plnil kontext modelu.

| Parametr | Typ | Povinný | Výchozí | Význam |
|---|---|---|---|---|
| `date_from` | string | **ano** | — | první den období |
| `date_to` | string | **ano** | — | poslední den období |
| `project` | string | ne | vše | omezení na jeden projekt |
| `billable` | boolean | ne | vše | `true` jen fakturovatelné, `false` jen nefakturovatelné |
| `limit` | integer | ne | `10` | počet záznamů ve vzorku, max 50 |

```python
query_time_entries(date_from="2026-08-01", date_to="2026-08-31", project="Acme", limit=2)
```

```json
{
  "date_from": "2026-08-01",
  "date_to": "2026-08-31",
  "project": "ACME",
  "billable_filter": null,
  "total_hours": 62.0,
  "entry_count": 22,
  "days_worked": 15,
  "sample_entries": [
    {"date": "2026-08-28", "project_id": "ACME", "client": "Acme Corp", "hours": 3.0,
     "description": "refaktoring importní pipeline", "billable": 1, "tag": "vyvoj"}
  ]
}
```

Chybové stavy: špatný formát data, `date_from` pozdější než `date_to`,
neznámý nebo nejednoznačný projekt.

---

## summarize_by

Rozpad hodin podle zvolené dimenze. Používá se na porovnání a přehledy.

| Parametr | Typ | Povinný | Výchozí | Význam |
|---|---|---|---|---|
| `dimension` | string | **ano** | — | `project`, `client`, `day`, `week`, `month`, `tag` |
| `date_from` | string | **ano** | — | první den období |
| `date_to` | string | **ano** | — | poslední den období |
| `project` | string | ne | vše | omezení na jeden projekt |
| `billable` | boolean | ne | vše | filtr fakturovatelnosti |

```python
summarize_by(dimension="project", date_from="2026-08-01", date_to="2026-08-31")
```

```json
{
  "dimension": "project",
  "date_from": "2026-08-01",
  "date_to": "2026-08-31",
  "total_hours": 179.5,
  "groups": [
    {"bucket": "NWND", "hours": 68.5, "entries": 21},
    {"bucket": "ACME", "hours": 62.0, "entries": 22}
  ]
}
```

Skupiny jsou seřazené sestupně podle hodin. Chybové stavy: neznámá dimenze
(chyba vypíše povolené hodnoty), špatný formát data, neznámý projekt.

---

## compute_invoice

Fakturační podklad za projekt a měsíc. Počítá jen fakturovatelné záznamy.

| Parametr | Typ | Povinný | Výchozí | Význam |
|---|---|---|---|---|
| `project` | string | **ano** | — | projekt |
| `month` | string | **ano** | — | měsíc `YYYY-MM` |
| `vat_rate` | number | ne | `0.21` | sazba DPH jako desetinné číslo |

```python
compute_invoice(project="Acme", month="2026-08")
```

```json
{
  "project": "ACME",
  "project_name": "Acme — platforma objednávek",
  "client": "Acme Corp",
  "month": "2026-08",
  "billable_hours": 62.0,
  "entry_count": 22,
  "hourly_rate": 1500.0,
  "currency": "CZK",
  "amount_excl_vat": 93000.0,
  "vat_rate": 0.21,
  "vat_amount": 19530.0,
  "amount_incl_vat": 112530.0
}
```

Chybové stavy: neznámý projekt, špatný formát měsíce, `vat_rate` mimo rozsah
`<0, 1)` — sazba se zadává jako `0.21`, ne `21`.

---

## capacity_check

Porovná odpracované hodiny za měsíc proti cíli. Počítá přes všechny projekty.

| Parametr | Typ | Povinný | Výchozí | Význam |
|---|---|---|---|---|
| `month` | string | **ano** | — | měsíc `YYYY-MM` |
| `target_hours` | number | ne | `160` | cílový počet hodin |

```python
capacity_check(month="2026-08", target_hours=160)
```

```json
{
  "month": "2026-08",
  "total_hours": 179.5,
  "billable_hours": 166.0,
  "non_billable_hours": 13.5,
  "days_worked": 21,
  "target_hours": 160.0,
  "difference": 19.5,
  "fulfilment_pct": 112.2,
  "status": "splněno"
}
```

`difference` je záporná, když cíl není splněn. Chybové stavy: špatný formát
měsíce, nekladné `target_hours`.

---

# Jak přidat vlastní nástroj

Nástroj se přidává na třech místech v [`tools.py`](../src/timeagent/tools.py).
Vezměme jako příklad `top_clients` — nejvytíženější klienti za období.

## 1. Funkce

Typované parametry, návratový `dict`, chyby přes `ToolError`.

```python
def top_clients(date_from: str, date_to: str, limit: int = 5) -> dict[str, Any]:
    """Klienti podle odpracovaných hodin, sestupně."""
    date_from = _parse_date(date_from, "date_from")
    date_to = _parse_date(date_to, "date_to")
    limit = max(1, min(int(limit), 50))

    with closing(db.connect_ro()) as conn:
        rows = conn.execute(
            """SELECT p.client, ROUND(SUM(e.hours), 2) AS hours
               FROM time_entries e JOIN projects p ON p.id = e.project_id
               WHERE e.date BETWEEN ? AND ?
               GROUP BY p.client ORDER BY hours DESC LIMIT ?""",
            (date_from, date_to, limit),
        ).fetchall()

    return {"date_from": date_from, "date_to": date_to,
            "clients": db.rows_to_dicts(rows)}
```

Pravidla, která platí pro všechny nástroje:

- **Hodnoty vždy přes `?` placeholdery**, nikdy vlepené do řetězce dotazu.
- Když do dotazu musí vstoupit *struktura* (jméno sloupce, směr řazení),
  vybírej ji z uzavřeného whitelistu jako `_DIMENSIONS`, ne z parametru.
- Čti přes `closing(db.connect_ro())`, ne přes zapisovatelné spojení.
- Vracej jen to, co model potřebuje. Stovky řádků mu zaplní kontext.

## 2. Registr

```python
REGISTRY = {
    ...
    "top_clients": top_clients,
}
```

## 3. Schéma

Popisy čte model, takže na nich záleží víc než na jménech parametrů. Piš, kdy
nástroj použít, ne jen co dělá.

```python
{
    "type": "function",
    "function": {
        "name": "top_clients",
        "description": (
            "Klienti seřazení podle odpracovaných hodin za období. "
            "Použij na otázky typu 'na kom jsem dělal nejvíc'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_from": _DATE_PROP,
                "date_to": _DATE_PROP,
                "limit": {"type": "integer", "description": "Kolik klientů, výchozí 5"},
            },
            "required": ["date_from", "date_to"],
        },
    },
}
```

## 4. Test

Soulad registru a schémat hlídá `test_every_schema_has_implementation` — bez
zápisu na obou místech testy spadnou. Samotnou funkci testuj proti přímému SQL
dotazu, ne proti zapsané konstantě, ať test přežije přegenerování dat:

```python
def test_top_clients(demo_db):
    out = tools.top_clients("2026-08-01", "2026-08-31")
    assert out["clients"][0]["hours"] >= out["clients"][1]["hours"]
```

Ověření, že model nástroj vidí:

```bash
uv run timeagent tools
```
