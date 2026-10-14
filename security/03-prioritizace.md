# 3. Prioritizace rizik

[← Rozcestník](README.md)

Hodnoceno pro **rozšířený scénář** (klienti v Telegramu), ne pro dnešní
lokální stav. Škála: nízká, střední, vysoká.

| Pořadí | ID | Pravděpodobnost | Dopad | Odůvodnění |
|---|---|---|---|---|
| 1 | **T2** | vysoká | vysoký | Nepotřebuje útočníka. Stačí běžná otázka bez projektu („kolik jsme celkem odpracovali“) a nástroj sečte všechny klienty. Únik mezi klienty přímo porušuje NDA. Je to jádro rozšíření: bez řešení T2 nejde scénář vůbec spustit. |
| 2 | **T1** | vysoká | vysoký | Telegram boti jsou dohledatelní podle jména. Bez allowlistu je T1 ještě horší než T2, protože útočník nemusí být klient. Řeší ho tatáž kontrola identity jako T2. |
| 3 | **T4** | střední (dnes nízká) | vysoký | Dnes je vše jen na loopbacku notebooku. Na Proxmoxu ale stačí jedna chyba v publikování portu nebo kompromitovaný kontejner. Rozhoduje to, **kde** se kontrola vynucuje: kontrola jen v n8n by T4 nechala otevřené. |
| 4 | **T3** | střední | střední | Popisy píše dodavatel sám, ale export je soubor mimo kontrolu systému. Po vyřešení T2 v nástrojích je dopad omezený na data téhož klienta. Injection pak nemá kam eskalovat. |
| 5 | **T5** | nízká | vysoký | Odposlech vyžaduje útočníka v domácí LAN, únik k cizímu poskytovateli vědomou změnu konfigurace. Dopad je ale nevratný. Řeší se šifrovaným spojením a kontrolou adresy modelu při startu, ne gate. |
| 6 | **T6** | nízká (dnes), střední (Proxmox) | vysoký | Platí hlavně po přesunu mimo notebook. Než se rozšíření spustí, jde o povinné kroky hardeningu. |
| 7 | **T7** | střední | nízký | Po vyřešení T1 píšou botu jen známí klienti. Lokální model nestojí nic navíc. Akceptovatelné s jednoduchým limitem. |
| 8 | **T8** | nízká | střední | Řeší se nastavením retence, levná oprava. |

**Co řešit první:** T2 a T1 jednou kontrolou identity a autorizace. Kontrolu
je nutné vynutit v MCP serveru, ne v n8n ani v promptu, aby současně
zavřela T4 a omezila dopad T3. Proto je to klíčová mitigace implementovaná
v kapitole 7.

**Co lze přijmout:** T7 s limitem v n8n. Zbytkové T3 uvnitř dat téhož
klienta: klient může dostat zavádějící text, ale jen o svých datech, a čísla
počítají nástroje.

**Předpoklady, které by pořadí změnily:**
- Bot zůstane jen pro vlastníka. T1 a T2 klesnou na nízkou a nejvýš se dostane T4.
- Klienti dostanou přístup i do LangFlow nebo k MCP napřímo. T4 se stane prioritou 1.
- Export bude obsahovat jména zaměstnanců klienta nebo jiné osobní údaje.
  Dopad T5 a T8 se zvýší kvůli GDPR.
- Na Proxmoxu bude služba publikovaná mimo domácí síť. T6 se stane
  prioritou 2.
