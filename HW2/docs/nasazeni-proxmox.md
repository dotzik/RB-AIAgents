# Nasazení mimo notebook

> **Stav: připraveno, nenasazeno.** Tenhle dokument popisuje směr a postup, ne
> provedený krok. Compose je od začátku psaný tak, aby se přenos obešel bez změn
> v něm — mění se jediný řádek v `.env`.

## Proč vůbec

Notebook je vývojové prostředí. Agent, který má být k něčemu, musí být zapnutý
i tehdy, když je notebook zavřený — jinak je Telegram bot polovičatý zážitek
a o pravidelném importu dat nemá smysl uvažovat.

## Cíl: VM 101 `playground-dev`

Na Proxmoxu MERY, VLAN 30. Naklonovat ze šablony VM 9000
(`ubuntu-2404-template`), doporučeně 12 GB RAM a 4 vCPU — LangFlow je z těch
tří obrazů zdaleka nejtěžší.

**Proč ne VM 100 `playground-stable`.** Má 8 GB a drží monitoring stack
(Prometheus, Grafana, Loki, čtyři exportéry). Shodit si monitoring domácím úkolem
je špatný obchod; oddělení, které compose už má (vlastní jmenný prostor, vlastní
síť, stropy paměti), riziko snižuje, ale neodstraňuje.

## Co se při přenosu mění

Jediná věc: **cesta k databázi**.

```bash
git clone <repo> && cd HW2
cp .env.vm.example .env          # TIMEAGENT_DB_FILE=/opt/timeagent/data/timeagent.sqlite
docker compose up -d
./scripts/init-accounts.sh
```

Adresa Ollamy zůstává, protože Spark je na LAN dostupný
z notebooku i z VM stejně. Ověření je totéž jako lokálně:

```bash
curl -s localhost:8000/health
curl -s "localhost:8000/run/capacity_check?month=2026-08"
```

Přenositelnost se dá otestovat **bez VM**: přepiš `TIMEAGENT_DB_FILE` na jinou
absolutní cestu a spusť `docker compose config` a `up`. Když to naběhne, je
nasazení jen otázka toho, kde compose spustíš.

## Co je potřeba rozhodnout před nasazením

**Porty.** Lokálně se publikují jen na loopback. Na VM to znamená, že se na UI
dostaneš jen přes SSH tunel — což je bezpečná výchozí volba. Otevřít je do LAN
je jednořádková změna `host_ip` v compose, ale je to rozhodnutí, ne detail:
n8n má v credentialech token bota a přístup k API s výkazy.

**Přihlášení do LangFlow.** Lokálně běží s `LANGFLOW_AUTO_LOGIN=true`, tedy bez
hesla. Na VM to přepnout na `false` a odkomentovat superuživatele
v `.env.vm.example`.

**Telegram.** Polling funguje beze změny a nic nevystavuje ven — to je jeho
hlavní přednost a na VM platí stejně. Vestavěný Telegram Trigger by pořád
vyžadoval veřejně dostupnou URL; **samotný přesun na Proxmox to nevyřeší**,
protože VM je za MikroTikem na privátní síti. Znamenalo by to port forward a TLS,
případně Cloudflare tunnel — a to je bezpečnostní rozhodnutí.

**Josefova ruka.** `sudo` na MERY i na Sparku jde jen přes Josefa, takže zřízení
VM, případné otevření portů a systemd jednotky jsou ruční krok.

## Kam to míří dál

VM 101 je tentýž stroj, na kterém by stál pravidelný import výkazů podle
zaparkovaného záměru
`projects/meta/hub/memory/decisions/004-jednotna-evidence-vykazu.md` v Dotzik.AI.Hub
— jednotná evidence času napříč Jirou, Redminem, ClickUpem, Clockify a Excelem.

To je vlastně jediný důvod, proč se HW2 vyplatí nasadit a nenechat jako cvičení:
infrastruktura pro domácí úkol a pro tu evidenci je táž. Platí ale, co je v tom
záměru napsané — **hodnota nevzniká ze schématu, ale z pravidelného toku dat.**
Bez cronu, který poběží sám, je to prázdná databáze s hezkým schématem.
