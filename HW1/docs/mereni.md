# Měření

Otázku „stačí na tohle malý model?" se nedá zodpovědět dojmem, proto je součástí
projektu benchmark. Tenhle dokument popisuje, jak se měří, co z toho vyšlo a co
se přitom ukázalo o modelech, hardwaru i o návrhu samotné metriky.

Naměřeno 3.–4. září 2026.


> **Poznámka k datům.** Měření proběhlo nad tehdejším demo datasetem
> (šest měsíců zpět). Dataset se od té doby rozšířil na leden 2025 až dnešek,
> takže konkrétní hodiny a částky v ukázkách odpovědí už neodpovídají aktuální
> databázi. Přepisovat je by znamenalo falšovat záznam měření; úspěšnosti
> a poznatky platí dál, protože bench očekávané hodnoty počítá z databáze
> za běhu.

## Metodika

```bash
uv run timeagent bench \
    --models ollama_chat/qwen2.5:14b,ollama_chat/qwen2.5:32b \
    --api-base http://ollama.lan:11434 --repeat 3 --json
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
průchod trvá hodiny — tam proběhl jen jeden běh.

> **Výhrada k řádkům za CPU.** Vznikly za dvou nepříznivých okolností a jejich
> čísla proto podhodnocují, co ty modely umí:
>
> 1. **Kontext 4096 tokenů.** Lokální Ollama běžela s výchozím nastavením,
>    zatímco jeden dotaz potřebuje 5–21 tisíc tokenů. Konverzace se ořezávala
>    a model přicházel o výsledky nástrojů, které si sám vyžádal. Není to mez
>    modelu, ale konfigurace — dá se změnit parametrem `num_ctx`.
> 2. **Starší popisy nástrojů.** Běh odstartoval dřív, než se opravil popis
>    parametru `dimension` (viz [níže](#a-jedna-vada-která-nebyla-ani-v-modelu-ani-v-metrice)).
>
> Přeměření za srovnatelných podmínek je odložené kvůli času: samotné CPU
> zabere přes čtyři hodiny.

## Výsledky

Tabulka je rozdělená podle toho, za jakých podmínek řádky vznikly — smíchat je
bez rozlišení by bylo zavádějící, protože opravy popsané níže výsledky prokazatelně
posouvají.

### Lokální modely na DGX Sparku

Všechny čtyři za shodných podmínek, na finální verzi kódu:

| Model | Skóre | Čas | Tokeny | Padá na |
|---|---|---|---|---|
| **`qwen2.5:14b`** | **39/39 (100 %)** | **222 s** | 163 089 | — |
| `qwen2.5:32b` | 37/39 (95 %) | 767 s | 176 902 | `ukonceny_projekt` |
| `qwen3:14b` | 37/39 (95 %) | 1 863 s | 208 888 | `ukonceny_projekt`, `retezeni` |
| `gpt-oss:20b` | 32/39 (82 %) | 400 s | 176 316 | `nejvytizenejsi_den`, `klient_nejvic`, `ukonceny_projekt` |

### Anthropic API

| Model | Skóre | Čas | Tokeny |
|---|---|---|---|
| `claude-haiku-4-5` | 39/39 (100 %) | **135 s** | 215 898 |
| `claude-sonnet-5` | 39/39 (100 %) | 217 s | 225 761 |
| `claude-opus-5` | 39/39 (100 %) | 292 s | 243 292 |

Měřeno před opravou popisů nástrojů. Protože všechny tři daly plný počet, oprava
jim neměla co zlepšit; přeměření by výsledek změnit nemohlo.

### Slabší hardware

| Backend | Model | Skóre | Čas | Poznámka |
|---|---|---|---|---|
| Arc 140T (LM Studio) | `qwen3-4b-2507` | 30/39 (77 %) | 865 s | před opravou popisů nástrojů |
| CPU (Core Ultra 7 255H) | `qwen2.5:7b` | 9/13 (69 %) | 3 060 s | jeden běh, kontext 4096 |
| CPU (Core Ultra 7 255H) | `llama3.2:3b` | 2/13 (15 %) | 1 472 s | jeden běh, kontext 4096 |

Řádky za CPU vznikly za nepříznivých podmínek popsaných v [metodice](#metodika)
a podhodnocují, co ty modely umí.

### Co z toho plyne

**Vyhrál nejmenší a nejstarší model.** `qwen2.5:14b` dal plný počet, je třikrát
rychlejší než dvakrát větší `32b` a osmkrát rychlejší než stejně velký `qwen3:14b`.
Ani větší velikost, ani novější generace nepomohly — v obou případech to dopadlo
hůř. Rozhoduje, jak je model natrénovaný na tool calling, ne kolik má parametrů
a z jakého je roku.

**Reasoning se tady nevyplácí.** `qwen3:14b` stráví „přemýšlením" před odpovědí
tolik času, že je proti stejně velkému `qwen2.5:14b` osmkrát pomalejší — a skončí
o dva body níž. Na úloze, kde jsou fakta v databázi a stačí je správně vytáhnout,
nemá o čem přemýšlet.

**Cloud a dobře nastavený lokální model jsou na téhle úloze nerozeznatelné.**
`qwen2.5:14b` na Sparku i Haiku 4.5 přes API dávají 39/39. Zbývá rozdíl v latenci
(222 s proti 135 s) a v tom, že u lokálního modelu data neopustí síť.

**Nejtěžší dotaz je ten, na který neodpovídá žádný nástroj.** `ukonceny_projekt`
(„na kterém projektu jsem přestal pracovat") selhal u tří modelů ze čtyř. Model
musí sám vymyslet, že se má podívat na několik období a porovnat je — žádný nástroj
tuhle otázku nezodpoví přímo. To je skutečný strop plánování, ne vada měření.

**Skóre se dá zlepšit i bez výměny modelu.** Tentýž `qwen2.5:14b` prošel během
jednoho dne třemi hodnotami, aniž by se model změnil:

| Skóre | Co se mezitím změnilo |
|---|---|
| 33/39 | výchozí stav |
| 36/39 | lepší popisy nástrojů, kratší výstupy |
| **39/39** | prefix `ollama_chat/` místo `ollama/` |

Zlepšovalo se výhradně okolí modelu. To je pro stavbu agenta hlavní poznatek
celého měření: **než sáhneš po větším modelu, projdi si popisy nástrojů, velikost
výstupů a to, jak se model vůbec volá.**

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
| Seskupení podle projektu místo podle druhu činnosti | všechny lokální | opraveno popisem parametru |
| Odpověď bez hodnoty, jen s názvem skupiny | `gpt-oss:20b`, `qwen2.5:32b` | žádná, projeví se jako neúplná odpověď |

Pojistka proti textovému volání za zmínku stojí zvlášť: **než vznikla, nedal
plný počet ani jeden lokální model.** Nezlepšily se modely, zlepšil se agent —
rozdíl mezi „lokální model na tohle nestačí" a „zvládne to" nebyl v modelu, ale
v tom, jestli smyčka ustojí porušení protokolu.

Jediné selhání, které se opravit nepodařilo, je `ukonceny_projekt`: otázka, na
kterou žádný nástroj neodpovídá přímo a model musí sám vymyslet postup. Padá
u tří modelů ze čtyř a je to skutečný strop plánování.

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

### Tiché selhání překladu mezi LiteLLM a Ollamou

Do měření se přidaly dva novější lokální modely, `qwen3:14b` a `gpt-oss:20b`.
Oba dopadly **0 z 39** — a při 0,7 sekundy na dotaz, což je samo o sobě
nemožné. Odpověď byla prázdná: žádná výjimka, žádné volání nástroje, jen `{}`
nebo prázdný řetězec.

Kontrola přes nativní API Ollamy ukázala, že modely jsou v pořádku:

```json
"tool_calls": [{"function": {"name": "list_projects", "arguments": {"active_only": true}}}]
```

Příčina byla v prefixu. LiteLLM má pro Ollamu dva providery — `ollama/` používá
starší cestu, `ollama_chat/` volá `/api/chat`. Se starším prefixem novější
modely vrací prázdno **bez jakéhokoli varování**. `qwen2.5` fungoval i s ním,
takže se ta vada projevila až s přidáním nových modelů.

Poučení je stejné jako u ostatních vad, jen o patro níž: **nula napříč všemi
případy není výsledek, ale symptom.** Model, který v jedné sadě selže úplně
všude a přitom odpovídá v řádu desetin sekundy, nedostal šanci odpovědět.

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

**`qwen2.5:14b` na Sparku je nejlepší volba** — 39/39, tedy stejně jako
nejsilnější cloudové modely, a přitom data neopustí síť. To je u výkazů se jmény
klientů argument, který cenu ani latenci nepřebijí.

Zbylé varianty a kdy dávají smysl:

| Varianta | Kdy |
|---|---|
| `qwen2.5:14b` (Spark) | výchozí volba — plný počet, lokálně, 222 s |
| Haiku 4.5 (API) | když nevadí posílat data ven a záleží na odezvě (135 s) |
| `qwen3-4b` (Arc) | když Spark není po ruce; na notebooku to jde, jen pomaleji |
| CPU | jen na vyzkoušení; jeden dotaz trvá minuty |

Co se **nevyplatilo**: sáhnout po větším modelu (`32b` je pomalejší a horší),
sáhnout po novějším (`qwen3:14b` totéž), ani sáhnout po dražším cloudovém modelu
(Opus se od Haiku neliší ničím než cenou a latencí).

Co se **vyplatilo**: opravit popisy nástrojů, zkrátit jejich výstupy a volat model
správnou cestou. Tytéž tři změny posunuly `qwen2.5:14b` z 33/39 na 39/39 — víc,
než by přinesla jakákoli výměna modelu.
