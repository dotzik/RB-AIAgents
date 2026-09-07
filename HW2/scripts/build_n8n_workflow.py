"""Generátor n8n workflow pro agenta nad výkazy.

Jedno workflow, **dva vstupy** do téhož agenta:

    Chat (webhook)  ─┐
                     ├→ Sjednoť vstup → Agent → z Telegramu? ──┬→ ano: odpověz do Telegramu
    Schedule → getUpdates → Rozbal ─┘                          └→ ne: konec (odpoví chat)

Proč generátor a ne klikání: nástrojů je pět a popis každého z nich je rozhraním
pro model — v měření HW1 zvedlo přepsání popisů úspěšnost víc než výměna modelu
za větší. Opisovat je myší do UI znamená, že se s API rozejdou při první změně.
Tady se berou z `GET /tools`, tedy z téhož zdroje, ze kterého je viděl agent v HW1.

Výstupem je JSON, který se odevzdává a který si n8n naimportuje.

    python scripts/build_n8n_workflow.py --credential-id <ollama> --telegram-credential-id <tg>
    python scripts/build_n8n_workflow.py --no-telegram     # jen chat
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT.parent / "HW1" / "src"))

from timeagent.agent import build_system_prompt

OUT = ROOT / "flows" / "n8n" / "vykazy-agent.json"

# Z hostitele se testuje přes localhost, uvnitř sítě projektu se služby vidí
# pod jmény z compose.
API_FROM_HOST = os.environ.get("API_FROM_HOST", "http://127.0.0.1:8000")
API_IN_NETWORK = os.environ.get("TOOLS_BASE_URL", "http://api:8000")

# Jak často se ptát Telegramu na nové zprávy. Kratší interval = svižnější bot
# a víc prázdných běhů v historii; 5 s je v chatu ještě přirozené.
POLL_SECONDS = 5

# Zvyš, když je potřeba zahodit historii konverzací (viz uzel Paměť konverzace).
MEMORY_EPOCH = "v2"

READ_OFFSET = """\
// Odkud číst. Telegram posílá tytéž zprávy dokola, dokud nepotvrdíme přečtení
// tím, že příště pošleme vyšší offset. Drží se ve statických datech workflow,
// takže přežije mezi běhy.
const store = $getWorkflowStaticData('global');
return [{ json: { offset: store.offset ?? 0 } }];
"""

COMPUTE_OFFSET = """\
// Spočítá, kam se posunout, a vrátí JEDNU položku — potvrzení přečtení se pak
// zavolá jen jednou, ne pro každou zprávu zvlášť.
//
// Offset se posouvá i u aktualizací, které nezpracujeme (editace, fotky) —
// jinak by se polling na takové zprávě zasekl a četl ji donekonečna.
const store = $getWorkflowStaticData('global');
const updates = $input.first().json.result ?? [];

let maxId = store.offset ? store.offset - 1 : 0;
for (const u of updates) {
  if (u.update_id > maxId) maxId = u.update_id;
}

const newOffset = maxId + 1;
store.offset = newOffset;      // jen záloha pro případ restartu n8n
return [{ json: { newOffset, updates } }];
"""

UNPACK_UPDATES = """\
// Teprve teď, po potvrzení přečtení, se z aktualizací udělá jedna položka
// na zprávu. Data se berou z uzlu před potvrzením — odpověď potvrzovacího
// volání nás nezajímá.
const updates = $('Spočti nový offset').first().json.updates ?? [];
const out = [];

for (const u of updates) {
  const msg = u.message;
  if (!msg?.text) continue;    // fotky, samolepky a spol. ignorujeme
  out.push({ json: { text: msg.text, chatId: msg.chat.id } });
}

return out;                    // prázdné pole = běh tiše skončí, agent se nespustí
"""


VERIFY_SOURCE = r"""// Pojistka proti nedoloženým číslům.
//
// Jestli agent zavolá nástroj, je rozhodnutí modelu — nic ho k tomu nenutí.
// qwen2.5:14b ho občas přeskočí a odpověď si domyslí; pozorováno na dotazu za
// červen, kde vydal 167,5 h a rozpad po projektech, aniž by se API dotkl
// (pravda je 166,0 h). Prompt na to nestačí, protože pravidlo čte tentýž model,
// který ho porušuje.
//
// Tenhle uzel proto nekontroluje model, ale **běh**: podívá se, které tool uzly
// se v tomto běhu opravdu spustily. Volání tím nevynutí — zaručí ale, že se
// nedoložené číslo nedostane k uživateli.
//
// Odpověď bez čísel (pozdrav, upřesňující otázka) nástroj nepotřebuje, takže se
// kontrola uplatní jen tam, kde odpověď něco číselně tvrdí.

const TOOLS = __TOOL_NAMES__;

const used = [];
for (const name of TOOLS) {
  try {
    if ($(name).isExecuted) used.push(name);
  } catch (e) {
    // Uzel se v tomto běhu vůbec neobjevil — to je legitimní stav, ne chyba.
  }
}

const answer = $json.output ?? '';
const claimsNumbers = /\d/.test(answer);

if (claimsNumbers && used.length === 0) {
  return [{
    json: {
      output:
        'Tuhle odpověď neumím doložit — nepodařilo se mi získat data z databáze ' +
        'výkazů, takže bych ti musel čísla odhadnout. Zkus se zeptat znovu, ' +
        'případně upřesni období.',
      verified: false,
      toolsUsed: [],
    },
  }];
}

return [{
  json: {
    // Zdroj se připojuje z běhu, ne z tvrzení modelu. Na otázku „odkud to máš"
    // odpovídá model jen dojmem; tohle je fakt.
    output: used.length ? `${answer}\n\n[zdroj: ${used.join(', ')}]` : answer,
    verified: true,
    toolsUsed: used,
  },
}];
"""


def system_prompt(today: date | None = None) -> str:
    """Prompt z HW1 plus jedno pravidlo navíc.

    Importuje se, neopisuje: tři kopie se dřív rozešly a srovnání platforem
    pak porovnávalo agenty s různým zadáním. Markdown se zakazuje jen tady —
    odpověď se čte i v Telegramu, který ho nerenderuje.
    """
    return build_system_prompt(today or date.today()).rstrip() + (
        "\n\nOdpovídej prostým textem bez markdownu — čte se to i v Telegramu."
    )


def fetch_tools() -> list[dict]:
    """Schémata nástrojů z běžícího API — týž zdroj, ze kterého je bral HW1."""
    try:
        with urllib.request.urlopen(f"{API_FROM_HOST}/tools", timeout=10) as r:
            return json.load(r)["tools"]
    except urllib.error.URLError as exc:
        sys.exit(f"API na {API_FROM_HOST} neodpovídá ({exc}). Spusť: docker compose up -d")


# Nepovinné parametry, které mění výsledek natolik, že bez nich agent odpovídá
# špatně. `project` je nutnost: bez něj se na dotaz „pracoval jsem na Initechu?"
# zavolá součet přes všechny projekty a model ho projektu přiřkne (pozorováno —
# vrátil 179,5 h u projektu, který má nula).
MEANINGFUL_OPTIONAL = {"project", "billable"}


def split_params(fn: dict) -> tuple[dict, list[str], list[str]]:
    """Vlastnosti nástroje rozdělené na povinné a nepovinné, v pořadí ze schématu."""
    params = fn.get("parameters", {})
    props = params.get("properties", {})
    req = set(params.get("required", []))
    return props, [k for k in props if k in req], [k for k in props if k not in req]


def tool_description(fn: dict) -> str:
    """Popis nástroje pro model — text ze schématu plus výčet parametrů."""
    props, required, optional = split_params(fn)

    exposed = required + [k for k in optional if k in MEANINGFUL_OPTIONAL]
    optional = [k for k in optional if k not in MEANINGFUL_OPTIONAL]

    lines = [fn["description"], "", "Parametry (vyplň všechny):"]
    for name in exposed:
        spec = props[name]
        enum = f" Povolené hodnoty: {', '.join(map(str, spec['enum']))}." if "enum" in spec else ""
        hint = "" if name in required else " Prázdný řetězec = bez omezení."
        lines.append(f"- {name}: {spec.get('description', '')}{enum}{hint}")
    if not exposed:
        lines.append("- žádné, nástroj se volá bez parametrů")
    if optional:
        # Ať model nezkouší posílat pole, která ve schématu nemá — vymyšlený
        # parametr navíc skončí chybou o špatných argumentech.
        lines += [
            "",
            "Ostatní nastavení (" + ", ".join(optional) + ") drží API ve výchozích "
            "hodnotách a odsud se měnit nedají.",
        ]
    return "\n".join(lines)


def http_tool_node(fn: dict, index: int) -> dict:
    """Jeden nástroj jako HTTP Request Tool.

    Do těla jdou **jen povinné parametry**: n8n dělá z každého placeholderu
    povinné pole schématu, takže nepovinný parametr se vyjádřit nedá — model ho
    vynechá a běh skončí na `Required → at project`. Výchozí hodnoty proto drží
    API. Co všechno bylo vyzkoušené, je v docs/srovnani.md.

    Node musí být `toolHttpRequest`; obyčejný `httpRequest` je sice
    `usableAsTool`, ale Tools Agent na něm spadne na chybějící `supplyData`.
    """
    name = fn["name"]
    props, required, optional = split_params(fn)
    exposed = required + [k for k in optional if k in MEANINGFUL_OPTIONAL]

    body = {key: f"{{{key}}}" for key in exposed}
    placeholders = []
    for key in exposed:
        spec = props[key]
        desc = spec.get("description", "")
        if "enum" in spec:
            desc += " Jedna z hodnot: " + ", ".join(map(str, spec["enum"])) + "."
        if key not in required:
            # n8n neumí nepovinné pole vyjádřit — každý placeholder je v schématu
            # povinný. Konvence je proto prázdný řetězec, který na druhé straně
            # zahodí `coerce_arguments` z HW1. Slovo „nepovinné" se v popisu
            # záměrně neobjeví: model by pole rovnou vynechal a běh by spadl.
            desc += " Vyplň vždy; prázdný řetězec znamená bez omezení."
        placeholders.append({"name": key, "description": desc, "type": "string"})

    parameters: dict = {
        "toolDescription": tool_description(fn),
        "method": "POST",
        "url": f"{API_IN_NETWORK}/tools/{name}",
        # Nástroj bez povinných parametrů (list_projects) posílá prázdné tělo —
        # placeholder by neměl co držet.
        "sendBody": bool(body),
    }
    if body:
        parameters |= {
            "specifyBody": "json",
            "jsonBody": json.dumps(body, ensure_ascii=False),
            "placeholderDefinitions": {"values": placeholders},
        }

    return {
        "id": f"tool-{name}",
        "name": name,
        "type": "@n8n/n8n-nodes-langchain.toolHttpRequest",
        "typeVersion": 1.1,
        "position": [-360 + index * 220, 480],
        "parameters": parameters,
    }


def verify_node(fns: list[dict]) -> dict:
    """Uzel, který ověří, že odpověď stojí na datech z API."""
    names = json.dumps([fn["name"] for fn in fns], ensure_ascii=False)
    return {
        "id": "verify",
        "name": "Ověř zdroj",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [300, 40],
        "parameters": {"jsCode": VERIFY_SOURCE.replace("__TOOL_NAMES__", names)},
    }


def telegram_nodes(telegram_credential_id: str) -> list[dict]:
    """Druhý vstup: polling Telegramu, a výstup zpátky do chatu.

    Vestavěný Telegram Trigger se nepoužívá schválně — je čistě webhookový, takže
    by Telegram musel na n8n dosáhnout zvenčí. Na notebooku to nejde a
    `n8n start --tunnel`, který to dřív řešil, z n8n zmizel (2.38 zná už jen
    `--open`). Polling má všechna spojení odchozí, takže se nic nevystavuje ven
    a porty zůstávají na loopbacku — a funguje stejně i po přenosu na VM.
    """
    return [
        {
            "id": "schedule",
            "name": "Každých pár vteřin",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.4,
            "position": [-880, 200],
            "parameters": {
                "rule": {"interval": [{"field": "seconds", "secondsInterval": POLL_SECONDS}]}
            },
        },
        {
            "id": "read-offset",
            "name": "Načti offset",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-680, 200],
            "parameters": {"jsCode": READ_OFFSET},
        },
        {
            "id": "get-updates",
            "name": "Telegram getUpdates",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.5,
            "position": [-480, 200],
            "parameters": {
                # Token je v proměnné prostředí, ne v tomhle souboru — odevzdávaný
                # JSON tak neobsahuje tajemství. Credential n8n použít nejde:
                # výraz $credentials se v obyčejném HTTP Request nodu nerozbalí
                # a odešel by do světa doslova (ověřeno, Telegram vrátí 404).
                "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/getUpdates",
                "sendQuery": True,
                "specifyQuery": "keypair",
                "queryParameters": {
                    "parameters": [
                        {"name": "offset", "value": "={{ $json.offset }}"},
                        # timeout=0 → Telegram odpoví hned. Long polling by drželo
                        # běh otevřený a pralo by se to s intervalem plánovače.
                        {"name": "timeout", "value": "0"},
                        {"name": "allowed_updates", "value": '["message"]'},
                    ]
                },
                "options": {},
            },
        },
        {
            "id": "compute-offset",
            "name": "Spočti nový offset",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-320, 200],
            "parameters": {"jsCode": COMPUTE_OFFSET},
        },
        {
            "id": "ack",
            "name": "Potvrď přečtení",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.5,
            "position": [-160, 200],
            # Potvrzení přečtení přímo u Telegramu, ještě než se rozběhne agent.
            # Bez něj bot odpovídá dvakrát: `$getWorkflowStaticData` se ukládá až
            # na konci běhu, takže další poll přečte tutéž zprávu znovu.
            # Podrobně v docs/srovnani.md.
            "parameters": {
                "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/getUpdates",
                "sendQuery": True,
                "specifyQuery": "keypair",
                "queryParameters": {
                    "parameters": [
                        {"name": "offset", "value": "={{ $json.newOffset }}"},
                        {"name": "timeout", "value": "0"},
                        {"name": "limit", "value": "1"},
                    ]
                },
                "options": {},
            },
        },
        {
            "id": "unpack",
            "name": "Rozbal zprávy",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [0, 200],
            "parameters": {"jsCode": UNPACK_UPDATES},
        },
        {
            "id": "is-telegram",
            "name": "Z Telegramu?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.3,
            "position": [420, 40],
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "loose",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": "from-telegram",
                            # Sjednocovacím nodem prochází obě větve, takže se na něj
                            # dá odkázat vždycky — na `Rozbal zprávy` ne, ten se při
                            # dotazu z chatu vůbec nespustí a výraz by spadl.
                            "leftValue": "={{ $('Sjednoť vstup').item.json.channel }}",
                            "rightValue": "telegram",
                            "operator": {"type": "string", "operation": "equals"},
                        }
                    ],
                    "combinator": "and",
                },
                "options": {},
            },
        },
        {
            "id": "send",
            "name": "Odpověz do Telegramu",
            "type": "n8n-nodes-base.telegram",
            "typeVersion": 1.2,
            "position": [640, -40],
            "parameters": {
                "chatId": "={{ $('Sjednoť vstup').item.json.chatId }}",
                # Escapování pro HTML režim (viz `parse_mode` níž) — neescapovaný
                # `<` nebo `&` znamená, že Telegram zahodí celou zprávu.
                "text": (
                    "={{ $json.output"
                    ".replaceAll('&', '&amp;')"
                    ".replaceAll('<', '&lt;')"
                    ".replaceAll('>', '&gt;') }}"
                ),
                # Výslovně HTML. Výchozí Markdown padá na podtržítku v názvu
                # nástroje (`capacity_check`) a tváří se to jako mlčení agenta.
                "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"},
            },
            "credentials": {
                "telegramApi": {
                    "id": telegram_credential_id,
                    "name": "Telegram — TimeAgent bot",
                }
            },
        },
        {
            "id": "chat-end",
            "name": "Konec (odpověď do chatu)",
            "type": "n8n-nodes-base.noOp",
            "typeVersion": 1,
            "position": [640, 120],
            "parameters": {},
        },
    ]


def build(tools: list[dict], ollama_credential_id: str, model: str,
          telegram_credential_id: str | None = None) -> dict:
    fns = [t["function"] for t in tools]
    with_telegram = bool(telegram_credential_id)

    nodes: list[dict] = [
        {
            "id": "chat-trigger",
            "name": "Chat",
            "type": "@n8n/n8n-nodes-langchain.chatTrigger",
            "typeVersion": 1.4,
            "position": [-880, -60],
            "webhookId": "vykazy-agent-chat",
            # `public: true` dělá z triggeru skutečný webhook, takže se workflow dá
            # aktivovat a chat má vlastní stránku na /webhook/<id>/chat. S výchozím
            # `public: false` je chat jen uvnitř editoru a aktivace tiše neprojde.
            # Autentizace je vypnutá záměrně: služba poslouchá jen na loopbacku.
            "parameters": {
                "public": True,
                "mode": "hostedChat",
                "authentication": "none",
                "initialMessages": "Ptej se na výkazy — hodiny, projekty, fakturační podklady.",
                "options": {},
            },
        },
        {
            "id": "normalize",
            "name": "Sjednoť vstup",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.5,
            "position": [-60, 40],
            # Obě větve se tu srovnají na stejný tvar, aby agent nemusel vědět,
            # odkud dotaz přišel. Chat posílá `chatInput`, Telegram `text`+`chatId`.
            "parameters": {
                "assignments": {
                    "assignments": [
                        {
                            "id": "text",
                            "name": "text",
                            "type": "string",
                            "value": "={{ $json.chatInput ?? $json.text }}",
                        },
                        {
                            "id": "channel",
                            "name": "channel",
                            "type": "string",
                            "value": "={{ $json.chatInput ? 'chat' : 'telegram' }}",
                        },
                        {
                            "id": "chatId",
                            "name": "chatId",
                            "type": "string",
                            "value": "={{ $json.chatId ?? '' }}",
                        },
                        {
                            "id": "conversationId",
                            "name": "conversationId",
                            "type": "string",
                            # Telegram dává `chatId`, webový chat `sessionId`.
                            # Bez záložní hodnoty sdílí všechny chatové konverzace
                            # jednu paměť a agent odpovídá z cizí historie.
                            "value": "={{ $json.chatId ?? $json.sessionId ?? 'chat' }}",
                        },
                    ]
                },
                "options": {},
            },
        },
        {
            "id": "agent",
            "name": "Agent nad výkazy",
            "type": "@n8n/n8n-nodes-langchain.agent",
            # Tools Agent v2.2, ne v3.x: novější verze očekává jinak stavěné
            # sub-nody a s toolHttpRequest skončí na chybějícím `execute`.
            "typeVersion": 2.2,
            "position": [180, 40],
            "parameters": {
                "promptType": "define",
                "text": "={{ $json.text }}",
                "options": {"systemMessage": system_prompt()},
            },
        },
        {
            "id": "ollama",
            "name": "Ollama — Spark",
            "type": "@n8n/n8n-nodes-langchain.lmChatOllama",
            "typeVersion": 1,
            "position": [80, 300],
            "parameters": {
                "model": model,
                # Jeden dotaz agenta spolyká 5–21 tisíc tokenů, protože se výsledky
                # nástrojů posílají v každém dalším kroku znovu. S výchozím oknem
                # se konverzace tiše ořízne a agent „zapomene", co mu nástroj vrátil.
                "options": {"numCtx": 32768, "temperature": 0},
            },
            "credentials": {
                "ollamaApi": {"id": ollama_credential_id, "name": "Ollama — DGX Spark"}
            },
        },
        {
            "id": "memory",
            "name": "Paměť konverzace",
            "type": "@n8n/n8n-nodes-langchain.memoryBufferWindow",
            "typeVersion": 1.4,
            "position": [280, 300],
            # Paměť zvlášť pro každý chat — jinak by se dotazy z Telegramu
            # a z webového chatu míchaly do jedné konverzace.
            "parameters": {
                "sessionIdType": "customKey",
                # `MEMORY_EPOCH` v klíči zahazuje historii. Jednou vymyšlená
                # čísla v paměti se opakují dál a promptem se to opravit nedá.
                "sessionKey": f"={{{{ $('Sjednoť vstup').item.json.conversationId }}}}-{MEMORY_EPOCH}",
            },
        },
    ]
    nodes.append(verify_node(fns))
    if with_telegram:
        nodes += telegram_nodes(telegram_credential_id)
    nodes += [http_tool_node(fn, i) for i, fn in enumerate(fns)]

    connections: dict = {
        "Chat": {"main": [[{"node": "Sjednoť vstup", "type": "main", "index": 0}]]},
        "Sjednoť vstup": {"main": [[{"node": "Agent nad výkazy", "type": "main", "index": 0}]]},
        "Agent nad výkazy": {"main": [[{"node": "Ověř zdroj", "type": "main", "index": 0}]]},
        "Ollama — Spark": {
            "ai_languageModel": [
                [{"node": "Agent nad výkazy", "type": "ai_languageModel", "index": 0}]
            ]
        },
        "Paměť konverzace": {
            "ai_memory": [[{"node": "Agent nad výkazy", "type": "ai_memory", "index": 0}]]
        },
    }
    if with_telegram:
        connections |= {
            "Každých pár vteřin": {
                "main": [[{"node": "Načti offset", "type": "main", "index": 0}]]
            },
            "Načti offset": {
                "main": [[{"node": "Telegram getUpdates", "type": "main", "index": 0}]]
            },
            "Telegram getUpdates": {
                "main": [[{"node": "Spočti nový offset", "type": "main", "index": 0}]]
            },
            "Spočti nový offset": {
                "main": [[{"node": "Potvrď přečtení", "type": "main", "index": 0}]]
            },
            "Potvrď přečtení": {
                "main": [[{"node": "Rozbal zprávy", "type": "main", "index": 0}]]
            },
            "Rozbal zprávy": {
                "main": [[{"node": "Sjednoť vstup", "type": "main", "index": 0}]]
            },
            "Ověř zdroj": {
                "main": [[{"node": "Z Telegramu?", "type": "main", "index": 0}]]
            },
            "Z Telegramu?": {
                "main": [
                    [{"node": "Odpověz do Telegramu", "type": "main", "index": 0}],
                    [{"node": "Konec (odpověď do chatu)", "type": "main", "index": 0}],
                ]
            },
        }
    for fn in fns:
        connections[fn["name"]] = {
            "ai_tool": [[{"node": "Agent nad výkazy", "type": "ai_tool", "index": 0}]]
        }

    return {
        "name": "Výkazy — agent (HW2)",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", help="jen vyjmenované nástroje")
    ap.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"))
    # Bez ID se zapíše zástupná hodnota — identifikátor konkrétní instance
    # do odevzdávaného JSONu nepatří; po importu se credential vybere v UI.
    ap.add_argument("--credential-id",
                    default=os.environ.get("N8N_OLLAMA_CREDENTIAL_ID", "OLLAMA-CREDENTIAL-ID"))
    ap.add_argument("--telegram-credential-id",
                    default=os.environ.get("N8N_TELEGRAM_CREDENTIAL_ID", ""))
    ap.add_argument("--no-telegram", action="store_true", help="jen chat, bez Telegramu")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    tools = fetch_tools()
    if args.only:
        tools = [t for t in tools if t["function"]["name"] in args.only]
        if not tools:
            sys.exit(f"Žádný z nástrojů {args.only} v API není.")

    workflow = build(
        tools,
        args.credential_id,
        args.model,
        telegram_credential_id=None if args.no_telegram else args.telegram_credential_id,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    names = [t["function"]["name"] for t in tools]
    vstupy = "chat + Telegram" if not args.no_telegram and args.telegram_credential_id else "chat"
    print(f"Zapsáno {args.out} — {len(names)} nástrojů ({', '.join(names)}), vstupy: {vstupy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
