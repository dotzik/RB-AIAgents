# n8n vs. LangFlow

Obě platformy dostaly **stejnou úlohu, stejných pět nástrojů, stejný systémový
prompt a stejný model** (`qwen2.5:32b` na DGX Sparku). Liší se jen platforma —
proto se nástroje vystavily jako jedno HTTP API, viz [architektura.md](architektura.md).

Že je prompt opravdu stejný, není slib. Oba generátory ho berou z jednoho
zdroje — `timeagent.agent.build_system_prompt` v HW1: n8n builder importem,
LangFlow přes `scripts/gen_langflow_flow.py`, který ho pošle do kontejneru
proměnnou prostředí. Dřív tu byly tři samostatné literály a **jedno pravidlo
se mezi n8n a LangFlow rozešlo**, takže se chvíli porovnávali agenti s různým
zadáním. Jediný záměrný rozdíl zůstal: n8n má navíc zákaz markdownu, protože
odpověď čte i Telegram.

> **Poznámka k datům.** Dataset se během práce rozšířil ze šesti měsíců na
> leden 2025 až dnešek. Naměřená tabulka níž je z aktuálních dat; **citace toho,
> co model tehdy odpověděl, se nepřepisují** — jsou to záznamy pozorování, ne
> ukázky současného stavu, a konkrétní hodiny v nich odpovídají tehdejší databázi.

## Naměřený výsledek

Osm dotazů z benchmarkové sady HW1, spouští je `scripts/compare_platforms.py`.
Očekávané hodnoty se počítají z téhož API, ne z opsaných konstant, takže měření
nezestárne s přegenerováním dat. **Tři běhy na platformu** — jeden průchod
u téhle úlohy nestačí, protože jeden z dotazů kolísá (viz níž).

| | n8n | LangFlow |
|---|---|---|
| skóre ve třech bězích | **8, 8, 8** | 7, 8, 8 |
| celkem na běh | 103,8 / 100,6 / 100,6 s | 94,6 / 87,2 / 93,6 s |
| medián na dotaz | 12,4 s | **10,3 s** |
| padlo aspoň jednou | — | `ukonceny` |

Rychlostně jsou nerozeznatelné — obě čekají na tentýž model. Ten jeden rozdíl
ve skóre je past popsaná hned níž a **není to vlastnost platformy**: v HW3 na
tentýž dotaz padají všichni tři frameworkoví klienti a to, kdo zrovna, se mezi
sadami běhů obrací (viz [HW3/docs/srovnani.md](../../HW3/docs/srovnani.md)).
Rozdíl je jinde než ve skóre.

### Past, která je v datech, ne v platformě

Sada obsahuje dotaz *„Pracoval jsem v srpnu 2026 na projektu Initech?"* Initech
je ukončený projekt a hodiny v srpnu nemá. V posledním měření na něj odpověděly
správně obě platformy, ale cestou k tomu **oba agenti aspoň jednou selhali
stejně** — a stejným způsobem:

- „Na projektu Initech (identifikátor **INTR**) jsi odpracoval 6,5 hodin."

`INIT` je Initech, `INTR` je Interní. Nástroj přitom odpovídá správně: na dotaz
`compute_invoice(project="Initech")` vrátí `INIT` a nula hodin. **Chybu dělá
model, který si vybere špatný identifikátor** a výsledek pak popíše jménem
druhého projektu.

Je to nejnebezpečnější třída chyby, jakou tu vidíme: odpověď je věrohodná,
čísla jsou skutečná — jen patří někomu jinému. Žádná z pojistek proti vymýšlení
ji nechytí, protože nástroj **byl** zavolán a data **jsou** pravá. Kdyby na tom
stála faktura, přišlo by se na to až u klienta.

Obrana patří do dat, ne do promptu: nedávat dvěma projektům identifikátory,
které se liší jediným písmenem.

## Rozdíl, který rozhoduje: jak vzniká nástroj

Tohle je jádro srovnání a nedá se obejít.

### n8n: nepovinný parametr neexistuje

Nástroj je `toolHttpRequest` s placeholdery v těle. **Každý placeholder je
v schématu povinný** a nepovinný parametr se vyjádřit nedá. Když ho model
vynechá — a vynechá ho, pokud ho nepotřebuje — běh skončí na
`Received tool input did not match expected schema: Required → at project`.

Vyzkoušené a neúspěšné cesty:

| Pokus | Výsledek |
|---|---|
| `specifyBody: "model"` (tělo skládá model) | `ToolInputParsingException` |
| placeholder s typem `not specified` | n8n si typ odvodí z těla, `null` neprojde |
| instrukce „pošli null" | `Expected string, received null` |
| instrukce „nech prázdný řetězec" | model pole stejně vynechá |

Řešení je konvence: do těla jdou povinné parametry **plus ty nepovinné, které
mění odpověď** (`project`, `billable`), popsané jako „vyplň vždy, prázdný řetězec
znamená bez omezení". Slovo „nepovinné" se v popisu záměrně neobjeví.

**A stálo to za to.** Před touhle úpravou `project` v schématu nebyl a agent na
dotaz o Initechu zavolal součet přes všechny projekty a **179,5 h přiřkl projektu,
který má nulu**. Chybějící parametr se tedy neprojevil jako chybějící schopnost,
ale jako sebejistě špatná odpověď.

### LangFlow: API Request je past

Komponenta API Request v tool mode vystaví modelu **jediný nástroj** pojmenovaný
podle své metody — `make_api_request` — s jedním volným parametrem `url_input`.
Pět takových komponent nedá pět nástrojů, ale pětkrát totéž. Přejmenovat je přes
`tools_metadata` nejde, LangFlow si je při buildu přepočítá.

Model pak nemá podle čeho vybírat a **adresu si vymyslí**. Doslovně z logu:

```
make_api_request  {"url_input": "https://api.timesheet.com/records?start_date=2026-08-01&…"}
make_api_request  {"url_input": "https://api.worklog.com/v1/timesheet?month=2026-08&user=<user-id>"}
```

Neexistující služby. V jednom běhu si model k tomu domyslel i výsledek (168 h
místo 179,5). Zachránila to jen ochrana LangFlow proti SSRF, která volání
zablokovala.

Je to učebnicová ukázka toho, proti čemu argumentuje `docs/architektura.md`
v HW1: nástroj typu „zavolej libovolné URL" je totéž jako „spusť libovolné SQL".

**Řešení: vlastní Python komponenta.** Jméno nástroje je jméno metody a typované
vstupy s `tool_mode=True` jsou jeho parametry. Teprve tím vznikne pět
rozlišitelných nástrojů se jmény jako v HW1 — a nepovinné parametry v nich
fungují bez potíží, na rozdíl od n8n.

### Shrnutí toho rozdílu

|  | n8n | LangFlow |
|---|---|---|
| nástroj z HTTP endpointu | ano, bez kódu | jen jako jeden generický „zavolej URL" |
| pojmenované nástroje | ano | až s vlastní komponentou |
| nepovinné parametry | **nejdou** | jdou |
| co bylo nutné napsat | konvence v popisech | **Python komponentu** |

Paradox stojí za vyslovení: **LangFlow je „no-code" platforma, která pro rozumný
výsledek potřebovala kód** — zato v ní ten kód napsat jde. n8n kód nepotřeboval,
ale narazil na strop svého modelu nástrojů.

## Druhý rozdíl: co platforma umí kolem agenta

Nejkonkrétnější odpověď na otázku „čím se ty platformy liší" nedal ani jeden
benchmark, ale požadavek na Telegram.

- **n8n:** Telegram, cron, webhooky, sto dalších integrací. Bot je hotový za
  odpoledne a je to *totéž* workflow — dva vstupy do jednoho agenta.
- **LangFlow:** Telegram nemá a mít nebude. Flow se dá zavolat přes
  `POST /api/v1/run/{id}`, takže se dá obalit zvenčí, ale sám o sobě neposlouchá.

**n8n je integrační nástroj, kterému přibyla AI. LangFlow je agent bez rukou.**
Pro úlohu „agent nad databází" jsou vyrovnané; pro úlohu „agent, kterému napíšu
z mobilu" je to jednostranné.

Mimochodem ani v n8n se nepoužil vestavěný Telegram Trigger — je čistě
webhookový a `n8n start --tunnel` z n8n zmizel. Řeší to polling, viz
[instalace.md](instalace.md).

## Třetí rozdíl: jak se v tom hledá chyba

Obojí se dá skládat generátorem přes REST, ale ladí se jinak.

- **n8n** má execution log s daty každého uzlu. Je uložený „zploštěně" (pole
  s odkazy na indexy), takže se v něm bez skriptu čte mizerně — zato je v něm
  všechno, včetně přesného těla požadavku a odpovědi nástroje.
- **LangFlow** vrací kroky agenta přímo v odpovědi `/api/v1/run` jako
  `content_blocks` s `tool_use`. Čitelnější na první pohled, ale mělčí.

Konkrétní pasti obou platforem (HTTP 431, SSRF, mizející databáze, `parse_mode`)
jsou v [instalace.md](instalace.md).

## Co se ukázalo o modelu, ne o platformách

Tři poznatky platí pro obě a jsou přenositelné i mimo tenhle úkol.

**1. Prázdný výsledek si model vyloží jako pozvánku k odhadu.** Na dotaz za
listopad, který v datech není, vrátil rozpad po projektech — vymyšlený.
Za měsíce, které v datech jsou, přitom nástroj poctivě volal: jeho čísla za
červen (62,5 + 60,5 + 25,5 + 17,5 = 166 h) i červenec (150 h) seděla na desetinu.
Vymýšlel si **jen tam, kde data nejsou**. Řeší to pole `note` ve výsledku
nástroje, které nulu pojmenuje včetně rozsahu dostupných dat.

**2. Vymyšlená odpověď v paměti konverzace otráví i správné dotazy.** Ta smyšlená
listopadová čísla model pak opakoval i na dotazy o srpnu, kde reálná data má.
Promptem se to opravit nedá — paměť se musí zahodit.

**3. Zda model zavolá nástroj, je jeho rozhodnutí.** Žádné pravidlo v promptu to
nezaručí; při jednom měření odpověděl na červen `167,5 h` (pravda je 166,0), aniž
by se API dotkl. Proto je za agentem uzel **Ověř zdroj**, který se dívá na běh,
ne na text: když odpověď tvrdí čísla a žádný tool uzel neproběhl, odpověď se
neodešle. Doložené odpovědi dostanou `[zdroj: capacity_check]`.

Ten poslední bod je zároveň odpovědí na otázku „odkud to ten agent má".
**Sám model na ni odpovídá dojmem** — jednou řekne pravdu, jindy totéž řekne
o odpovědi, kterou si vymyslel. Důvěryhodný je jen záznam běhu.

## Cena za větší model

Přechod z `qwen2.5:14b` na `32b` zlepšil poslušnost v tool callingu, ale zpomalil
odpovědi zhruba **z 4 s na 12–22 s**. U chatu je to znát; u Telegramu ne.

## Co bych udělal jinak

- **Pro produkci** by tenhle agent nestačil. Chtěl bych plánovač a vykonavatel:
  první volání modelu vrátí strukturovaný záměr, deterministický uzel zavolá API
  **vždy**, druhé volání složí větu. Model pak nemá jak volání vynechat.
- **Pro srovnání platforem** byl agentní návrh správný — právě proto, že jeho
  slabiny vyplavaly.
