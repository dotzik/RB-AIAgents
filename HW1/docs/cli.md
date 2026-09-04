# Příkazová řádka

```
timeagent [--db CESTA] {seed,tools,ask,chat,bench,import} ...
```

Globální přepínač `--db` přebije `TIMEAGENT_DB` pro jedno spuštění.

| Příkaz | K čemu | Potřebuje model |
|---|---|---|
| [`seed`](#seed) | vygeneruje demo databázi | ne |
| [`tools`](#tools) | vypíše nástroje a jejich schémata | ne |
| [`ask`](#ask) | jeden dotaz | ano |
| [`chat`](#chat) | konverzace s pamětí | ano |
| [`bench`](#bench) | srovná modely na stejné sadě dotazů | ano |
| [`import`](#import) | načte reálná data z Clockify | ne |

---

## seed

Vygeneruje deterministický demo dataset. Existující data smaže.

```bash
uv run timeagent seed
uv run timeagent seed --months 12 --rng-seed 7
```

| Přepínač | Výchozí | Význam |
|---|---|---|
| `--months` | `6` | kolik měsíců zpět od dneška se generuje |
| `--rng-seed` | `42` | seed generátoru; stejný seed = stejná data |

```
Databáze: D:\...\HW1\data\timeagent.sqlite
Vloženo: 5 projektů, 307 záznamů za posledních 6 měsíců.
Data jsou vygenerovaná a anonymní — žádný reálný klient.
```

## tools

Vypíše nástroje, které má model k dispozici. Užitečné pro kontrolu, co agent umí,
bez spuštění modelu.

```bash
uv run timeagent tools
uv run timeagent tools --json     # surová schémata pro model
```

| Přepínač | Význam |
|---|---|
| `--json` | vypíše JSON schémata tak, jak se posílají modelu |

## ask

Jeden dotaz, jeden běh agenta.

```bash
uv run timeagent ask "Kolik jsem v 2026-08 nafakturoval klientovi Acme?"
uv run timeagent ask --quiet --model anthropic/claude-haiku-4-5 "Kolik mám projektů?"
```

| Přepínač | Výchozí | Význam |
|---|---|---|
| `--model` | z `.env` | přebije `TIMEAGENT_MODEL` |
| `--quiet` | vypnuto | potlačí výpis kroků, vypíše jen odpověď |
| `--max-iterations` | `8` | strop počtu kol smyčky |

Bez `--quiet` se vypisuje průběh: každý krok, volané nástroje s argumenty
a zkrácený výsledek. Na konci souhrn `model | kroků | volání nástrojů | tokeny`.

Návratový kód je `1`, když volání modelu selhalo.

## chat

Totéž co `ask`, ale v cyklu a s pamětí — druhá otázka může navazovat na první
(„a co červenec?"). Konec prázdným řádkem nebo Ctrl+C. Přepínače shodné s `ask`.

```bash
uv run timeagent chat
```

## bench

Pustí pevnou sadu tří dotazů proti zadaným modelům, změří čas a tokeny a ověří,
jestli v odpovědi zazněla správná čísla. Podrobnosti o metodice v
[mereni.md](mereni.md).

```bash
uv run timeagent bench --models ollama_chat/qwen2.5:14b
uv run timeagent bench --models ollama_chat/qwen2.5:14b,ollama_chat/qwen2.5:32b \
                       --api-base http://192.168.0.24:11434 --json
```

| Přepínač | Výchozí | Význam |
|---|---|---|
| `--models` | povinné | modely oddělené čárkou |
| `--api-base` | z `.env` | endpoint pro všechny modely v běhu |
| `--max-iterations` | `8` | strop počtu kol smyčky |
| `--trace` | vypnuto | vypisovat i jednotlivé kroky |
| `--json` | vypnuto | přidat surová data včetně celých odpovědí |

Výstupem je markdownová tabulka. Měsíc, na kterém se měří, určuje
`TIMEAGENT_BENCH_MONTH` (výchozí `2026-08`).

## import

Načte reálné výkazy z Clockify do stejného schématu. Vyžaduje `CLOCKIFY_API_KEY`.

```bash
uv run timeagent import --month 2026-08
uv run timeagent import --month 2026-08 --append
```

| Přepínač | Výchozí | Význam |
|---|---|---|
| `--month` | aktuální měsíc | období ve tvaru `YYYY-MM` |
| `--append` | vypnuto | nemazat existující záznamy daného měsíce |

Bez `--append` se záznamy daného měsíce nejdřív smažou, takže opakovaný import
nevytváří duplicity. Přeskočí běžící záznamy (nemají trvání) a záznamy bez
projektu; jejich počet vypíše.

Návratový kód je `1`, když chybí konfigurace nebo API vrátí chybu.
