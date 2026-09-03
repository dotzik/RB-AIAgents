# Testy

```bash
uv run pytest -q             # 86 testů, běží do vteřiny
uv run pytest -v             # s názvy
uv run pytest tests/test_agent.py -k rescue
uvx ruff check src tests     # linter
```

**Celá suita běží bez API klíče a bez běžícího modelu.** To je záměr, ne
kompromis: kdokoli si projekt naklonuje, spustí testy hned a nemusí nic
konfigurovat. Testuje se mechanika agenta, ne kvalita odpovědí modelu —
ta se měří jinak, viz [mereni.md](mereni.md).

| Soubor | Testů | Co ověřuje |
|---|---|---|
| `test_tools.py` | 31 | nástroje proti přímým SQL dotazům, chybové stavy, narovnání argumentů |
| `test_agent.py` | 20 | ReAct smyčku proti podvrženému LLM, pojistky |
| `test_bench.py` | 13 | vyhodnocování benchmarku |
| `test_clockify.py` | 13 | čisté funkce importu — parsování trvání, sazeb, hranic měsíce |
| `test_llm.py` | 9 | volbu poskytovatele a endpointu |

## Fixture `demo_db`

Většina testů potřebuje databázi. Fixture v `conftest.py` vytvoří dočasnou,
naplní ji deterministickými daty a přesměruje na ni `TIMEAGENT_DB`:

```python
@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    path = tmp_path / "test.sqlite"
    conn = db.connect_rw(path)
    seed.seed_database(conn, anchor=ANCHOR, months=4, rng_seed=42)
    conn.close()
    monkeypatch.setenv("TIMEAGENT_DB", str(path))
    return path
```

Dvě věci stojí za pozornost.

**Pevná kotva.** `ANCHOR = date(2026, 8, 31)` — data se generují vůči tomuhle dni,
ne vůči dnešku. Bez toho by testy s natvrdo zapsanými měsíci začaly padat, jakmile
se přehoupne kalendář.

**Přes proměnnou prostředí, ne parametrem.** Nástroje si spojení otevírají samy
a cestu berou z `TIMEAGENT_DB`. `monkeypatch` ji nastaví jen pro daný test a pak
uklidí, takže testy nemůžou sáhnout na ostrou databázi ani se navzájem ovlivnit.

## Testování nástrojů

Očekávané hodnoty se **nezapisují jako konstanty**, ale počítají přímo z databáze.
Test tak nezestárne, když se změní generátor dat:

```python
def test_query_time_entries_matches_sql(demo_db):
    out = tools.query_time_entries(date_from="2026-08-01", date_to="2026-08-31")
    expected = _sql(
        demo_db,
        "SELECT ROUND(COALESCE(SUM(hours), 0), 2) FROM time_entries "
        "WHERE date BETWEEN ? AND ?",
        ("2026-08-01", "2026-08-31"),
    )
    assert out["total_hours"] == expected
```

Kde se dá, testují se **invarianty** místo konkrétních čísel — ty platí bez ohledu
na data:

```python
def test_billable_filter_splits_total(demo_db):
    total = tools.query_time_entries("2026-08-01", "2026-08-31")
    billable = tools.query_time_entries("2026-08-01", "2026-08-31", billable=True)
    non = tools.query_time_entries("2026-08-01", "2026-08-31", billable=False)
    assert round(billable["total_hours"] + non["total_hours"], 2) == total["total_hours"]
```

Součet po projektech musí dát celek, červenec plus srpen musí dát obojí dohromady,
skupiny musí být seřazené. Takový test odhalí chybu, na kterou by konkrétní číslo
nestačilo.

Zvlášť se testují **chybové cesty**, protože chyba je tady součástí rozhraní —
model ji dostane jako data a má se podle ní zařídit:

```python
def test_unknown_project_lists_options(demo_db):
    out = tools.call_tool("compute_invoice", {"project": "Nexus", "month": "2026-08"})
    assert "error" in out
    assert "ACME" in out["error"]      # chyba musí nabídnout, co existuje
```

A jedna pojistka na návrh: `test_database_is_read_only` ověřuje, že přes
dotazovací spojení `DELETE` neprojde.

## Testování smyčky: podvržené LLM

Agent přijímá volací funkci jako parametr (`complete_fn`), takže se dá nahradit.
`FakeLLM` přehraje připravenou sekvenci odpovědí a zapamatuje si, co dostal:

```python
class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def __call__(self, messages, tools=None, **kwargs):
        self.calls.append([dict(m) for m in messages])
        if not self.responses:
            return _response(content="už nemám co říct")
        return self.responses.pop(0)
```

Pomocné funkce `_response()` a `_tool_call()` sestaví objekty ve tvaru, v jakém
je vrací LiteLLM. Test pak vypadá takhle:

```python
def test_single_tool_call(demo_db):
    fake = FakeLLM([
        _response(tool_calls=[
            _tool_call("c1", "capacity_check", {"month": "2026-08", "target_hours": 100})
        ]),
        _response(content="V srpnu jsi odpracoval dost."),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("Kolik mi chybí do 100 h?")

    assert result.answer == "V srpnu jsi odpracoval dost."
    assert [s.tool for s in result.steps] == ["capacity_check"]
```

`fake.calls` je ta zajímavější polovina — umožňuje ověřit, co agent modelu poslal,
tedy že se výsledek nástroje opravdu vrátil do konverzace:

```python
def test_tool_result_is_fed_back_to_model(demo_db):
    ...
    second_call = fake.calls[1]
    tool_messages = [m for m in second_call if m["role"] == "tool"]
    assert tool_messages[0]["tool_call_id"] == "c1"
    assert "ACME" in tool_messages[0]["content"]
```

Nástroje se přitom spouštějí **doopravdy** proti dočasné databázi. Podvržený je
jen model, ne datová vrstva.

### Co je pokryté

Kromě šťastné cesty hlavně pojistky, protože ty vznikly z reálných selhání:

| Test | Ověřuje |
|---|---|
| `test_multiple_tool_calls_in_one_step` | v jednom kroku se spustí všechna volání, ne jen první |
| `test_sequential_reasoning` | řetězení — nejdřív zjistit projekt, pak spočítat |
| `test_tool_error_is_returned_to_model_not_raised` | chyba nástroje smyčku neshodí a model se opraví |
| `test_malformed_arguments_do_not_crash` | nevalidní JSON v argumentech |
| `test_repeated_call_is_served_from_cache` | opakované volání se nespouští znovu |
| `test_looping_model_is_stopped_and_forced_to_answer` | zacyklený model dostane závěr bez nástrojů |
| `test_max_iterations_guard` | strop počtu kroků drží |
| `test_textual_call_is_executed_and_fed_back` | volání napsané jako text se rozpozná a spustí |
| `test_normal_answer_is_not_mistaken_for_a_call` | běžná odpověď se za volání nepovažuje |
| `test_history_is_reused` | druhá otázka navazuje na první |
| `test_token_accounting` | součet tokenů přes všechna volání |

## Regresní testy

Několik testů existuje proto, že daná chyba už jednou nastala. Jejich docstring
říká jakou — bez toho by je někdo mohl při refaktoru bez rozmyslu smazat:

```python
def test_compare_covers_whole_month_not_first_28_days(demo_db, monkeypatch):
    """Očekávané hodnoty musí sedět s tím, co nástroj vrátí modelu.

    Regrese: dřív se rozsah počítal jako 1.–28., takže věcně správné odpovědi
    za celý měsíc padaly jako chybné.
    """
```

Obě chyby v benchmarku popisuje [mereni.md](mereni.md).

## Jak přidat testy k novému nástroji

Postup přidání nástroje je v [nastroje.md](nastroje.md); testy k němu patří tři.

**1. Shoda s databází nebo invariant.**

```python
def test_top_clients(demo_db):
    out = tools.top_clients("2026-08-01", "2026-08-31")
    assert out["clients"] == sorted(out["clients"], key=lambda c: -c["hours"])
```

**2. Chybová cesta** — vždy přes `call_tool`, protože právě tam se výjimka mění
na data pro model:

```python
def test_top_clients_bad_date(demo_db):
    out = tools.call_tool("top_clients", {"date_from": "1.8.2026", "date_to": "2026-08-31"})
    assert "YYYY-MM-DD" in out["error"]
```

**3. Soulad registru a schémat** už hlídá `test_every_schema_has_implementation` —
když nástroj zapíšeš jen na jedno ze dvou míst, testy spadnou samy.

Když nový nástroj mění chování smyčky, přidej test s `FakeLLM` podle vzorů výše.

## Co testy nepokrývají

- **Kvalitu odpovědí modelu.** Na to je `timeagent bench`, který ale potřebuje
  běžící model — proto není součástí suity. Viz [mereni.md](mereni.md).
- **Síťovou část importu z Clockify.** Vyžadovala by API klíč nebo podvržený
  HTTP server. Otestované jsou jen čisté funkce — parsování trvání, sazeb
  a hranic měsíce.
- **Skutečné volání LiteLLM.** Testuje se výběr modelu a endpointu
  (`test_llm.py`), samotné odeslání požadavku ne.
