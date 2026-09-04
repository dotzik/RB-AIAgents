# Měření

Otázku „stačí na tohle malý model?" se nedá zodpovědět dojmem, proto je součástí
projektu benchmark. Tenhle dokument popisuje, jak se měří, co z toho vyšlo a co
se přitom ukázalo o modelech, hardwaru i o návrhu samotné metriky.

Naměřeno 3.–4. září 2026.

## Metodika

```bash
uv run timeagent bench --models ollama/qwen2.5:14b,ollama/qwen2.5:32b                        --api-base http://192.168.0.24:11434 --repeat 3 --json
```

**Třináct dotazů** stoupající obtížnosti, pro všechny modely shodné. Každý se
pouští **třikrát**, protože modely blízko hranice použitelnosti mezi běhy kolísají
a jediné měření by o nich lhalo.

| Případ | Co ověřuje |
|---|---|
| `faktura` | jedno volání, přímá odpověď |
| `faktura_dph` | správná z dvojice částek — pozná model rozdíl základu a celkem? |
| `kapacita` | jedno volání, jedno číslo |
| `nefakturovatelne` | méně obvyklé pole ve výsledku nástroje |
| `pocet_projektu` | volitelný parametr (`active_only`) |
| `sazba` | dohledání údaje v seznamu |
| `klient_nejvic` | seskupení; odpověď musí obsahovat jméno i číslo |
| `tag_nejvic` | seskupení podle druhu činnosti |
| `nejvytizenejsi_den` | seskupení podle dne; datum smí být i v běžném českém tvaru |
| `ctvrtleti` | období přes tři měsíce |
| `porovnani` | dvě volání a udržet, které číslo patří ke kterému měsíci |
| `ukonceny_projekt` | průzkum — žádný nástroj neodpoví přímo |
| `retezeni` | dvě volání, druhé závisí na výsledku prvního |

**Vyhodnocení.** Kontroluje se, jestli v konečné odpovědi zazněly správné údaje —
ne jestli proběhl nástroj. Agent, který si vytáhne správná data a pak je špatně
přepíše, je k ničemu stejně jako ten, co je vůbec nenajde.

Očekávané hodnoty se čtou **z databáze při každém běhu**, ne ze zapsaných
konstant, takže měření nezestárne s přegenerovanými daty. Kontrola je záměrně
tolerantní k tomu, co na správnosti nic nemění:

- formátování čísel — `93 000`, `93000.00`, `93000 Kč`
- diakritika — v databázi je tag `vyvoj`, model napíše „vývoj"
- zápis data — `2026-08-28` i „28. srpna 2026"
- rovnocenné varianty — u faktury projde částka s DPH i bez ní

Naopak **netoleruje** vynechání toho, na co se otázka ptá: u seskupení musí zaznít
jméno skupiny i hodnota. Jak se hledala hranice mezi „tolerantní" a „děravá",
popisuje [oddíl o chybách v benchmarku](#chyby-v-benchmarku-a-co-z-nich-plyne).

**Data.** `timeagent seed` s výchozím seedem, měsíc `2026-08`
(`TIMEAGENT_BENCH_MONTH`).

**Rozsah.** 13 dotazů × 3 běhy = 39 měření na model. Výjimkou je CPU, kde jeden
průchod trvá hodiny — tam proběhl jen jeden běh a čísla jsou proto orientační.

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

Během měření se ukázalo pět vad — a **čtyři z nich byly v měření, ne v modelech**.
Stojí za to je vypsat, protože mají společný vzorec a dají se jím předcházet.

### Useknutý měsíc

Očekávané hodnoty se počítaly za období `YYYY-MM-01` až `YYYY-MM-28`. Modely
správně hlásily celý měsíc, scorer je porovnával s useknutým obdobím a označoval
za chybné. Projevilo se to tím, že *porovnání dvou měsíců* neprošlo **žádnému**
modelu, od 3B až po Opus — což je samo o sobě podezřelý výsledek.

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
všimnout.

### Příliš přísné vyhodnocení, dvakrát

U faktury se vyžadovalo, aby v odpovědi zazněly hodiny *i* částka. Otázka se ale
ptá jen na částku, takže odpověď „112 530 Kč" byla věcně správná a přesto padala.

Totéž u dotazu „který den jsem odpracoval nejvíc hodin" — vyžadoval jsem datum
i počet hodin, přestože otázka chce jen ten den.

### Kontrola měřila databázový zápis, ne odpověď

Nejzajímavější případ. Očekávané hodnoty se braly z databáze tak, jak tam jsou:

| Očekávalo se | Model odpověděl | Kdo měl pravdu |
|---|---|---|
| `vyvoj` | „vývoj" | model |
| `2026-08-28` | „28. srpna 2026" | model |

Tagy jsou v databázi bez diakritiky, protože jsou to identifikátory. Datum je
v ISO tvaru, protože se s ním tak pracuje. Ale **model neodpovídá databázovým
zápisem, odpovídá česky** — a měřit se má odpověď, ne interní reprezentace.

### Společný vzorec a jak mu předcházet

Všech pět má stejnou příčinu: **očekávaná odpověď se odvozovala z datové cesty,
ne z toho, jak vypadá správná odpověď pro člověka.**

Z toho plyne pět praktik, které jsou dnes v projektu zabudované:

**1. Vzorovou odpověď napiš dřív než kontrolu.** Každý případ v
[`bench.py`](../src/timeagent/bench.py) nese ručně napsanou správnou odpověď
(`sample`) a věrohodně vypadající špatnou (`counter_sample`). Test
`test_kazdy_pripad_ma_konzistentni_vzory` ověří, že kontrola první přijme
a druhou odmítne. Kdyby očekávaná hodnota byla `vyvoj`, vzorová odpověď „vývoj"
neprojde a je to vidět hned — ne až v tabulce, kde to vypadá jako chyba modelu.

Ta pojistka zabrala hned při psaní: vzorovou odpověď jsem měl s tagem natvrdo
a v testovací databázi vede jiná činnost.

**2. Selhání referenčního modelu ber jako podezření na metriku.** Když nejsilnější
dostupný model spadne na dotazu, který zjevně umí, je pravděpodobnější, že měříš
špatně. Dvě z pěti vad se našly takhle.

**3. Negativní kontrola ke každé kontrole.** Bez ověření, že metrika **odmítne**
špatnou odpověď, můžeš mít metriku propouštějící cokoli — a to je horší než
přísná, protože si toho nikdo nevšimne.

**4. Odděl, co čím testuješ.** U nástrojů je správné odvozovat očekávanou hodnotu
ze SQL — testuje se nástroj proti databázi. U benchmarku ne — tam se testuje
odpověď pro člověka. Splácnutí obojího dohromady je zdroj téhle chyby.

**5. Uchovávej odpovědi a umožni přehodnocení.** `--json` ukládá celé odpovědi,
`--rescore` je oboduje znovu aktuální kontrolou:

```bash
uv run timeagent bench --models ... --json > vysledky.json
uv run timeagent bench --rescore vysledky.json
```

Oprava metriky pak stojí vteřiny místo hodin. Konkrétně: uvolnění kontroly
u dotazu na den posunulo `qwen3-4b` z 27/39 na 30/39 **bez jediného nového volání
modelu**. Než tahle možnost existovala, každá oprava vyhodnocení znamenala pustit
celé měření znovu — za jeden den čtyřikrát.

Obě první vady navíc hlídají regresní testy
(`test_compare_covers_whole_month_not_first_28_days`,
`test_comparison_question_names_both_months`).

### A jedna vada, která nebyla ani v modelu, ani v metrice

`tag_nejvic` selhal 0/3 u **všech** lokálních modelů. Když stejný případ padá
napříč modely, je podezřelý případ. Příčina byla ve schématu nástroje:

```json
"dimension": {
  "enum": ["project", "client", "day", "week", "month", "tag"],
  "description": "Podle čeho seskupit"
}
```

Model nemá jak vědět, co `tag` obsahuje. Že jsou v něm druhy činnosti, neplyne
ani z názvu, ani z popisu — modely proto sáhly po `project`, jediné dimenzi,
které z toho výčtu rozumí. Není to chyba modelu; **je to vada dokumentace
nástroje**, kterou by stejně tak neuhodl člověk.

Popis dnes vyjmenovává, co která dimenze znamená. Poučení: **popisy v JSON
schématu jsou rozhraní pro model a patří jim stejná péče jako dokumentaci pro
lidi.** Enum s holými hodnotami je pro model asi tak užitečný jako pro nového
kolegu.

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
