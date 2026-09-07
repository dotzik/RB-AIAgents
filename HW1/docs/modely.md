# Modely a backendy

Agent nezná poskytovatele. Veškeré volání modelu jde přes jednu funkci
(`llm.complete`) postavenou na [LiteLLM](https://docs.litellm.ai/), takže
přepnutí backendu je změna dvou řádků v `.env` — kód se nemění.

Model se zadává jako `poskytovatel/název`. Prefix určuje, jak se volání přeloží.

| Backend | `TIMEAGENT_MODEL` | `TIMEAGENT_API_BASE` | Klíč |
|---|---|---|---|
| Ollama lokálně | `ollama_chat/qwen2.5:14b` | `http://localhost:11434` | — |
| Ollama na jiném stroji | `ollama_chat/qwen3:14b` | `http://ollama.lan:11434` | — |
| LM Studio | `openai/qwen/qwen3-4b-2507` | `http://localhost:1234/v1` | libovolná hodnota |
| Anthropic | `anthropic/claude-haiku-4-5` | *nenastavovat* | `ANTHROPIC_API_KEY` |
| OpenAI | `gpt-4o-mini` | *nenastavovat* | `OPENAI_API_KEY` |
| OpenRouter | `openrouter/meta-llama/llama-3.3-70b-instruct` | *nenastavovat* | `OPENROUTER_API_KEY` |

Který model na tuhle úlohu stačí, ukazuje [mereni.md](mereni.md). Stručně:
**`qwen2.5:14b` dal plný počet**, stejně jako nejsilnější cloudové modely.
Větší ani novější modely si nevedly líp; pod zhruba 4 miliardy parametrů to
naopak nemá smysl zkoušet.

---

## Ollama na localhostu

Nejjednodušší cesta a výchozí nastavení projektu.

```bash
# instalace: https://ollama.com/download
ollama pull qwen2.5:14b
ollama list                  # ověření
```

```bash
TIMEAGENT_MODEL=ollama_chat/qwen2.5:14b
TIMEAGENT_API_BASE=http://localhost:11434
```

> **Používej prefix `ollama_chat/`, ne `ollama/`.** LiteLLM má pro Ollamu dva
> providery a liší se cestou, po které volají. Starší `ollama/` u novějších
> modelů (`qwen3`, `gpt-oss`) **tiše vrátí prázdnou odpověď** — žádná výjimka,
> žádné volání nástroje, jen prázdný obsah. V benchmarku se to projevilo jako
> 0 ze 39 u obou modelů, přestože přes nativní API Ollamy volají nástroje
> správně. Podrobněji v [mereni.md](mereni.md).

Model musí umět tool calling. U Ollamy to pozná podle značky `tools` v katalogu;
`qwen2.5`, `llama3.1` a `llama3.2` ho mají, ale menší varianty ho zvládají
nespolehlivě.

Na čem model počítá, ukáže `ollama ps`:

```
NAME          SIZE      PROCESSOR
qwen2.5:14b   9.0 GB    100% CPU
```

`100% CPU` znamená, že se GPU nepoužívá — viz [omezení podle hardwaru](#hardware).

## Ollama na jiném stroji v síti

Používá se stejný prefix, mění se jen adresa. Server musí poslouchat na síťovém
rozhraní, ne na localhostu — Ollama to ve výchozím stavu nedělá.

Na serveru (systemd):

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' \
  | sudo tee /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart ollama

ollama pull qwen2.5:32b
```

Na klientovi:

```bash
TIMEAGENT_MODEL=ollama_chat/qwen2.5:32b
TIMEAGENT_API_BASE=http://ollama.lan:11434
```

Ověření dostupnosti:

```bash
curl -s http://ollama.lan:11434/api/tags
```

Prázdná odpověď nebo timeout znamená, že server buď neběží, nebo poslouchá jen
na localhostu, nebo ho blokuje firewall.

### DGX Spark

Spark je z pohledu projektu obyčejný linuxový stroj s Ollamou — postup výše platí
beze změny. Instalace na aarch64:

```bash
curl -fsSL https://ollama.com/install.sh | sh    # vyžaduje sudo
```

Díky unifikované paměti (128 GB) na něm bez potíží běží i modely, které se na
běžný notebook nevejdou. Naměřené časy jsou v [mereni.md](mereni.md).

## LM Studio

Jediná cesta, jak na Windows využít integrovanou grafiku Intel Arc — Ollama to
neumí (viz níže). LM Studio vystavuje OpenAI-kompatibilní endpoint, proto prefix
`openai/` a ne `lmstudio/`.

```bash
lms runtime ls                              # vyber runtime s "vulkan" v názvu
lms load qwen/qwen3-4b-2507 --gpu max -y    # nahraje model na GPU
lms server start                            # endpoint na portu 1234
lms ps                                      # co je načteno
```

```bash
TIMEAGENT_MODEL=openai/qwen/qwen3-4b-2507
TIMEAGENT_API_BASE=http://localhost:1234/v1
OPENAI_API_KEY=not-needed
```

Klíč musí být neprázdný, protože ho vyžaduje OpenAI klient; LM Studio jeho
hodnotu ignoruje.

Model se po nečinnosti sám uvolní z paměti (TTL). Když `lms ps` hlásí prázdno,
načti ho znovu — jinak endpoint odpoví, ale bez modelu.

## Anthropic

```bash
TIMEAGENT_MODEL=anthropic/claude-haiku-4-5
ANTHROPIC_API_KEY=sk-ant-...
```

Klíč se generuje na [console.anthropic.com](https://console.anthropic.com)
→ Settings → API Keys. Je to samostatně placená služba — předplatné Claude.ai
ani Claude Code na ni nepřenáší kredit.

Dostupné modely a ceny za milion tokenů: Haiku 4.5 ($1/$5), Sonnet 5 ($2/$10),
Opus 5 ($5/$25). Zkrácená sada tří dotazů vyjde podle modelu na 2 až 10 centů;
plný běh (13 dotazů × 3 opakování) je zhruba čtrnáctkrát dražší — viz
[mereni.md](mereni.md#náklady).

**`TIMEAGENT_API_BASE` u cloudových poskytovatelů nenastavuj.** Kód ho pro
prefixy `anthropic/`, `gemini/`, `openrouter/`, `xai/` a `vertex_ai/` záměrně
ignoruje — jinak by zbytek po lokálním modelu poslal dotaz na localhost a chyba
by vypadala jako problém s klíčem.

### Klíče navázané na identitu

Klíč vytvořený pro *All workspaces* vyžaduje u každého požadavku hlavičku
s ID workspace. Bez ní API vrátí:

```
anthropic-workspace-id is required when authenticating with an identity-linked API key
```

Dvě řešení:

1. Vytvořit klíč pro **konkrétní workspace** místo pro všechny — pak žádná
   hlavička není potřeba.
2. Doplnit `ANTHROPIC_WORKSPACE_ID=wrkspc_...` (Settings → Workspaces). Kód ji
   pak posílá automaticky.

## OpenAI a OpenRouter

```bash
TIMEAGENT_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

```bash
TIMEAGENT_MODEL=openrouter/meta-llama/llama-3.3-70b-instruct
OPENROUTER_API_KEY=sk-or-...
```

Netestováno v rámci měření, ale žádnou zvláštní obsluhu nepotřebují — LiteLLM je
podporuje stejně jako ostatní.

---

## Hardware

Poznámky z měření na notebooku s **Intel Core Ultra 7 255H** (integrovaná grafika
Arc 140T + NPU AI Boost). Platí pro celou třídu Core Ultra.

### NPU se nepoužije

Ollama ani LM Studio NPU nevyužívají a využívat nebudou — oba stojí na
llama.cpp, který NPU backend nemá. K NPU vede cesta jen přes OpenVINO, DirectML
nebo QNN, což jsou jiné runtimy. **Nula na záložce NPU ve Správci úloh je
správný stav, ne chyba konfigurace.**

### Intel Arc pod Ollamou nefunguje

Oficiální windowsový build Ollamy akceleruje jen NVIDII (CUDA) a AMD (ROCm).
Intel v něm není, takže výpočet spadne na CPU — `ollama ps` to přizná jako
`100% CPU`.

Dvě cesty k Arcu:

- **LM Studio s Vulkan runtimem** — funguje, postup výše. Ověřeno měřením
  výkonnostních čítačů: během inference je GPU engine `compute` vytížený na 76 %.
- **`ipex-llm` build Ollamy** (Intel SYCL) — zachová ollama API, ale obsazuje
  stejný port jako běžná Ollama, takže obojí najednou neběží.

### Proč to vypadá, že se nic neděje

Správce úloh ukazuje ve výchozích grafech GPU jen 3D, Copy a Video. Výpočet
běží na engine **Compute 0**, na který se graf musí ručně přepnout. Bez toho
vypadá vytížená grafika jako nečinná.

### Kolik to stojí času

Tentýž agent a tytéž tři dotazy:

| Kde | Čas |
|---|---|
| Anthropic API | 18 s |
| DGX Spark (GB10) | 46 s |
| Arc 140T přes LM Studio | 165 s |
| CPU (Core Ultra 7 255H) | 689 s |

U inference na CPU nerozhoduje kapacita paměti, ale její propustnost — víc RAM
nepomůže, ale několik současně načtených modelů si o propustnost konkuruje.
Když měříš, nech načtený jen ten, který zrovna testuješ.

---

## Když to nefunguje

| Příznak | Příčina |
|---|---|
| `LLM Provider NOT provided` | chybí prefix v `TIMEAGENT_MODEL` (`qwen2.5:14b` místo `ollama_chat/qwen2.5:14b`) |
| Model odpovídá prázdnem, žádná chyba, žádné volání nástroje | prefix `ollama/` místo `ollama_chat/` |
| Volání jde na localhost, i když má jít do cloudu | v prostředí zbyl `MODEL` nebo `API_BASE` z jiného projektu; systémová proměnná přebíjí `.env` |
| `anthropic-workspace-id is required` | klíč navázaný na identitu, viz výše |
| Endpoint odpovídá, ale model „není" | LM Studio uvolnilo model po TTL — `lms ps`, pak `lms load` |
| Model volá nástroje, ale odpověď je nesmysl | model je pod hranicí použitelnosti, viz [mereni.md](mereni.md) |
| Dotazy trvají minuty | běží na CPU; ověř `ollama ps` |
