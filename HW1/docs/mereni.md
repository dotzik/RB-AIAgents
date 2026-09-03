# Měření

Otázku „stačí na tohle malý model?" se nedá zodpovědět dojmem, proto je součástí
projektu benchmark. Tenhle dokument popisuje, jak se měří, co z toho vyšlo a co
se přitom ukázalo o modelech, hardwaru i o návrhu samotné metriky.

Naměřeno 3.–4. září 2026.

## Metodika

```bash
uv run timeagent bench --models ollama/qwen2.5:14b,ollama/qwen2.5:32b \
                       --api-base http://192.168.0.24:11434 --json
```

Tři dotazy stoupající obtížnosti, pro všechny modely shodné:

| Případ | Dotaz | Co ověřuje |
|---|---|---|
| `faktura` | „Kolik jsem v 2026-08 nafakturoval klientovi Acme?" | jedno volání nástroje, přímá odpověď |
| `kapacita` | „Kolik hodin jsem odpracoval v 2026-08 a chybělo mi něco do 160 hodin?" | jedno volání, dvě čísla v jedné větě |
| `porovnani` | „Porovnej 2026-07 a 2026-08 podle projektů." | dvě volání a udržet, které číslo patří ke kterému měsíci |

**Vyhodnocení.** Kontroluje se, jestli v konečné odpovědi zazněla správná čísla —
ne jestli proběhl nástroj. Agent, který si vytáhne správná data a pak je špatně
přepíše, je k ničemu stejně jako ten, co je vůbec nenajde.

Očekávané hodnoty se čtou **z databáze při každém běhu**, ne ze zapsaných
konstant, takže měření nezestárne s přegenerovanými daty. Kontrola je tolerantní
k formátování (`93 000`, `93000.00`, `93000 Kč`) a připouští rovnocenné varianty:
u faktury projde částka s DPH i bez ní, u porovnání stačí hodiny libovolného
projektu z každého měsíce.

**Data.** `timeagent seed` s výchozím seedem, měsíc `2026-08`
(`TIMEAGENT_BENCH_MONTH`). Srpen má v datech 179,5 hodiny, z toho 166 fakturovatelných;
ACME 62 hodin, tedy 93 000 Kč bez DPH.

**Rozsah.** Tři dotazy, jeden běh na model. To je tenký důkaz — tabulka říká, co
který model zvládl tady a teď, ne co zvládne obecně. Rozšířit sadu znamená přidat
záznam do `cases()` v [`bench.py`](../src/timeagent/bench.py).

## Výsledky

| Backend | Model | faktura | kapacita | porovnání | čas | tokeny |
|---|---|---|---|---|---|---|
| Anthropic API | `claude-haiku-4-5` | ✅ | ✅ | ✅ | **18 s** | 15 222 |
| Anthropic API | `claude-sonnet-5` | ✅ | ✅ | ✅ | 19 s | 16 905 |
| Anthropic API | `claude-opus-5` | ✅ | ✅ | ✅ | 21 s | 16 379 |
| DGX Spark (GB10) | `qwen2.5:14b` | ✅ | ✅ | ✅ | 46 s | 23 482 |
| DGX Spark (GB10) | `qwen2.5:32b` | ✅ | ✅ | ✅ | 72 s | **14 310** |
| Arc 140T (LM Studio) | `qwen3-4b-2507` | ✅ | ✅ | ✅ | 165 s | 17 157 |
| CPU (Core Ultra 7 255H) | `qwen2.5:7b` | ✅ | ❌ | ✅ | 689 s | 27 312 |
| CPU (Core Ultra 7 255H) | `llama3.2:3b` | ❌ | ❌ | ❌ | 321 s | 21 267 |

### Co z toho plyne

**Hranice použitelnosti leží kolem 4 miliard parametrů a je to zlom, ne svah.**
Od `qwen3-4b` výš prošlo všechno; `llama3.2:3b` nedal ani jeden dotaz. Mezi tím
není plynulý přechod.

**Nad tou hranicí velikost skoro nerozhoduje.** 4B, 14B, 32B i Opus dávají shodně
3/3. Liší se rychlostí a spotřebou, ne správností. Rozhoduje spíš to, jak pečlivě
je model natrénovaný na tool calling, než kolik má parametrů.

**Tokeny prozrazují víc než skóre.** `qwen2.5:32b` došel k cíli na 14 310 tokenů,
`14b` potřeboval 23 482 — víc kroků, víc oprav, menší rezerva. Obojí je ✅, ale ne
stejně pohodlně. U modelu, který má zvládat i otázky mimo tuhle trojici, je ta
rezerva to podstatné.

**Rychlost je věc hardwaru, správnost věc modelu.** Tentýž agent: 18 s přes API,
46 s na Sparku, 165 s na integrované grafice, 689 s na CPU — a Spark má přitom
stejné skóre jako 4B model na iGPU.

**Malé modely kolísají.** `llama3.2:3b` dal v jednom kole 1/3, v druhém 0/3. Jedno
měření u modelu na hraně nestačí.

**Časy na CPU jsou horní odhad.** Měřeno, když byl v paměti současně model
v LM Studiu. Pořadí se tím nemění, absolutní čísla ano.

## Pozorované způsoby selhání

Tohle bylo při měření největší překvapení: **slabým místem není volání nástrojů,
ale poslední krok.** Modely si nástroj vyberou správně a správná data dostanou —
zakopnou až při formulaci odpovědi.

| Selhání | Kde pozorováno | Reakce agenta |
|---|---|---|
| Zacyklení na stejném volání | `llama3.2:3b` | výsledek z paměti, pak vynucený závěr |
| Záměna veličin — „nafakturoval jsi 62,00 Kč", kde 62 jsou hodiny | `llama3.2:3b` | žádná, projeví se jako špatná odpověď |
| Syrový JSON místo věty — `{"total_hours": 179.5, "difference": 19.5}` | `qwen2.5:7b`, `14b` | žádná, pokyn v systémovém promptu |
| Volání nástroje napsané jako text | `qwen2.5:14b` i `32b` | rozpozná se a spustí za model |
| `"true"` a `"null"` jako řetězce | `llama3.2:3b` | narovnání podle typu ve schématu |

Poslední dvě položky za zmínku stojí zvlášť. **Před přidáním pojistky proti
textovému volání nedal 3/3 ani jeden lokální model**; po jejím přidání ji dávají
všechny nad hranicí použitelnosti. Nezlepšily se modely, zlepšil se agent —
rozdíl mezi „lokální model na tohle nestačí" a „zvládne to" nebyl v modelu, ale
v tom, jestli smyčka ustojí porušení protokolu.

Jak jednotlivé pojistky fungují, popisuje [architektura.md](architektura.md).

## Chyby v benchmarku a co z nich plyne

První kolo měření vypadalo drtivě: *porovnání dvou měsíců* neprošlo **žádnému**
modelu, od 3B až po Opus. Takový výsledek je podezřelý sám o sobě — a taky byl.
Chyba byla dvakrát na straně měření, ne modelů.

### Useknutý měsíc

Očekávané hodnoty se počítaly za období `YYYY-MM-01` až `YYYY-MM-28`. Modely
správně hlásily celý měsíc, scorer je porovnával s useknutým obdobím a označoval
za chybné. Po opravě dává Haiku 4.5 plný počet.

### Dvojznačné zadání

Otázka zněla „porovnej **předchozí měsíc** a 2026-08", jenže měřeno bylo v září —
takže „předchozí měsíc" *byl* srpen a dotaz si protiřečil. Claude Sonnet 5 to jako
jediný poznal a místo hádání odpověděl:

> Upozorním: „předchozí měsíc" vzhledem k dnešnímu datu (2026-09-04) je právě
> **srpen 2026**, tedy stejné období jako zadané **2026-08** – jde tedy
> o identický měsíc, ne o dvě různá období k porovnání.

Byl za to ohodnocen jako chybující. Ostatní modely rozpor ignorovaly, něco
spočítaly a dostaly ✅.

**Model, který si všiml vady v zadání, byl potrestán víc než modely, které ji
ignorovaly.** Špatně navržená metrika si tenhle druh poctivosti systematicky
vypěstuje pryč — a protože se hodnotí podle metriky, nikdo si toho nemusí
všimnout. Poučení není o Sonnetu, ale o tom, že metrika potřebuje revizi stejně
jako kód, který měří.

Obě chyby hlídají regresní testy `test_compare_covers_whole_month_not_first_28_days`
a `test_comparison_question_names_both_months`.

### Příliš přísné vyhodnocení

Třetí, mírnější případ: u faktury se původně vyžadovalo, aby v odpovědi zazněly
hodiny *i* částka. Otázka se ale ptá jen na částku, takže odpověď „112 530 Kč"
byla věcně správná a přesto padala. Vyhodnocení dnes připouští rovnocenné
varianty.

## Hardware

Měřeno na notebooku s **Intel Core Ultra 7 255H** (iGPU Arc 140T + NPU AI Boost,
64 GB RAM) a na **DGX Spark** (GB10, 128 GB unifikované paměti, aarch64).

Zjištění, o kterých se moc nepíše, a jejich praktické důsledky shrnuje
[modely.md](modely.md). Ve zkratce:

- **NPU se nepoužije a ani nemůže** — Ollama i LM Studio stojí na llama.cpp, který
  NPU backend nemá.
- **Intel Arc pod Ollamou nefunguje** — oficiální build akceleruje jen CUDA
  a ROCm, takže výpočet spadne na CPU (`ollama ps` hlásí `100% CPU`).
- **Přes LM Studio s Vulkan runtimem Arc funguje** — ověřeno měřením výkonnostních
  čítačů, GPU engine `compute` vytížený na 76 %.
- Ve Správci úloh je výpočet schovaný pod engine **Compute 0**, ve výchozích
  grafech není vidět.

## Náklady

Jeden běh benchmarku přes Anthropic API, tři dotazy:

| Model | Tokeny | Přibližná cena |
|---|---|---|
| Haiku 4.5 | 15 222 | ~2 centy |
| Sonnet 5 | 16 905 | ~4 centy |
| Opus 5 | 16 379 | ~9 centů |

Lokální běhy stojí jen čas.

## Závěr pro tenhle projekt

Pro agenta nad výkazy je **`qwen2.5:14b` dostatečný** — dá 3/3 a běží lokálně,
takže se s reálnými výkazy nemusí nic posílat ven. To je u dat s jmény klientů
argument, který cenu ani rychlost nepřebijí.

Kdo má Spark k dispozici stejně, `32b` nabízí větší rezervu za cenu vyšší latence.
Pro rychlou odezvu bez ohledu na to, kde data jsou, je nejlevnější cloudová
varianta (Haiku 4.5) zároveň nejrychlejší — mezi ní a Opusem není v téhle úloze
rozdíl ve výsledku, jen v ceně.
