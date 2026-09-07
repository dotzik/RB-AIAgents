# Instalace

## Co potřebuješ

- **Docker** s Compose v2 (vyvíjeno na 29.0.1)
- **běžící Ollamu** s modelem, který umí tool calling — výchozí je
  `qwen2.5:32b`. Nemusí být na stejném stroji; stačí, aby na ni kontejnery
  dosáhly po síti.
- **databázi z HW1** — vygeneruje ji `uv run timeagent seed --months 21`

Repozitář neobsahuje žádná data ani tajemství. `*.sqlite` a `.env` jsou
v `.gitignore`.

## Rychlý start

```bash
cd HW1 && uv run timeagent seed --months 21   # demo data: leden 2025 až dnešek
cd ../HW2
cp .env.example .env                   # a uprav adresu Ollamy
docker compose up -d
./scripts/init-accounts.ps1            # vlastník v n8n (Linux: .sh)
```

Za pár desítek vteřin běží tři služby:

| | adresa | |
|---|---|---|
| API s nástroji | http://localhost:8000/health | |
| n8n | http://localhost:5678 | přihlášení podle `.env` |
| LangFlow | http://localhost:7860 | bez přihlášení (auto-login) |

Ověření, že API vidí data:

```bash
curl -s localhost:8000/health
curl -s "localhost:8000/run/capacity_check?month=2026-08"
```

## Nahrání agentů

Workflow i flow se **generují**, ne klikají — popisy nástrojů se berou
z `GET /tools`, takže se nemůžou rozejít s API.

```bash
# n8n — potřebuje id credentialu na Ollamu (a volitelně na Telegram)
python scripts/build_n8n_workflow.py --credential-id <ollama-id> \
                                     --telegram-credential-id <telegram-id>

# LangFlow — generuje se uvnitř kontejneru, používá jeho vlastní builder
docker compose exec -T langflow python - < scripts/build_langflow_flow.py \
    > flows/langflow/vykazy-agent.json
python scripts/import_langflow_flow.py --ask "Kolik hodin jsem odpracoval v srpnu 2026?"
```

Credentialy se zakládají v UI (n8n → Credentials → Ollama / Telegram) nebo přes
REST. `import_langflow_flow.py` flow **aktualizuje na místě**; kdybys posílal
`POST /api/v1/flows/` ručně, LangFlow pokaždé založí kopii „… (1)", „… (2)".

**Adresa Ollamy v odevzdávaném flow.** LangFlow ukládá `base_url` přímo do
komponenty, takže by se interní adresa dostala do repozitáře. V souboru je proto
zástupný text `http://OLLAMA-HOST:11434` a skutečnou hodnotu dosazuje
`import_langflow_flow.py` z `.env` až při nahrávání. Kdo flow importuje ručně
přes UI, musí adresu v komponentě Ollama přepsat sám. n8n tenhle problém nemá —
tam je adresa v credentialu, mimo export.

Workflow v n8n se aktivuje `POST /rest/workflows/{id}/activate` s `versionId`
v těle — `PATCH` s `{"active": true}` tiše neudělá nic.

## Telegram (volitelné)

1. U [@BotFather](https://t.me/BotFather) `/newbot`, token do `.env` jako
   `TELEGRAM_BOT_TOKEN`.
2. `docker compose up -d n8n` a přegenerovat workflow s `--telegram-credential-id`.

Bot **nepoužívá Telegram Trigger**. Ten je čistě webhookový a Telegram by musel
na n8n dosáhnout zvenčí; `n8n start --tunnel`, který to dřív řešil, byl z n8n
odstraněn (2.38 zná už jen `--open`). Místo toho se každých 5 s volá `getUpdates`
— všechna spojení jsou **odchozí**, takže se nic nevystavuje ven a porty
zůstávají na loopbacku. Funguje to stejně na notebooku i na serveru.

**NDA:** s demo daty je bot neškodný. U reálných výkazů by odpovědi o klientské
práci tekly přes servery Telegramu — produkční varianta by posílala jen agregáty,
nebo by šla jiným kanálem.

## Pasti, na které jsme narazili

Každá z nich stála čas; jsou tu, aby nestály znovu.

**n8n vrací prázdnou bílou stránku (HTTP 431).** Node má strop hlaviček 16 kB
a prohlížeč sdílí cookies mezi všemi službami na `localhost` bez ohledu na port.
Na stroji s dalšími dev službami se strop překročí a UI přestane jít právě přes
`localhost`, zatímco přes `127.0.0.1` jede. Řeší `NODE_OPTIONS:
--max-http-header-size=65536` v compose.

**`localhost` nefunguje, `127.0.0.1` ano.** Na Windows se `localhost` překládá
na `::1`, ale porty se publikují na IPv4. Compose proto publikuje v obou
rodinách (dlouhá syntaxe `host_ip`).

**LangFlow nedosáhne na model ani na API.** Má ochranu proti SSRF, která blokuje
privátní adresy — a Spark i vlastní `api` privátní adresy mají. Řeší
`LANGFLOW_SSRF_ALLOWED_HOSTS`.

**LangFlow zapomíná flow.** Ve výchozím stavu si ukládá databázi do vlastních
`site-packages`, tedy dovnitř image. Řeší `LANGFLOW_CONFIG_DIR`
a `LANGFLOW_DATABASE_URL` mířící do volume.

**`/api/v1/run` vrací 403 i při zapnutém auto-loginu.** Od LangFlow 1.5 chce
API klíč; založí ho `POST /api/v1/api_key/`.

**Bot mlčí, ačkoli agent odpověděl.** n8n posílá do Telegramu v Markdown režimu
a nepárové `_` zprávu shodí — což nastane vždycky, když agent zmíní jméno
nástroje (`capacity_check`). Řeší `parse_mode: HTML` plus escapování `& < >`.

**Čeština v shellu.** Payload s diakritikou poslaný přes `-d` se cestou rozbije;
posílat souborem (`--data-binary @soubor`).
