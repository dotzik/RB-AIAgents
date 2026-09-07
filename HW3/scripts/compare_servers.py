"""Ověří, že C# proxy vrací totéž co Python server.

    python scripts/compare_servers.py
    python scripts/compare_servers.py --a http://127.0.0.1:8010/mcp --b …

Existuje proto, že tvrzení „schémata i výsledky jsou bit-identické" bylo dřív
doložené jen úryvkem v dokumentaci, který nikdo znovu nespustil. Takový důkaz
tiše zestárne. Tohle je regresní pojistka: nenulový návratový kód při první
odchylce.

Sada volání schválně obsahuje hraniční případy, na kterých se překlad
HTTP → MCP láme nejspíš: prázdné období s `note`, neexistující projekt,
neznámý nástroj a argument, který musí projít narovnáním typů.
"""
from __future__ import annotations

import argparse
import json
import sys

import anyio
from mcp import Client

DEFAULT_A = "http://127.0.0.1:8010/mcp"
DEFAULT_B = "http://127.0.0.1:8011/mcp"

CALLS: list[tuple[str, dict]] = [
    ("capacity_check", {"month": "2026-08"}),
    ("compute_invoice", {"project": "ACME", "month": "2026-08"}),
    ("summarize_by", {"dimension": "tag", "date_from": "2026-08-01",
                      "date_to": "2026-08-31"}),
    ("list_projects", {"active_only": True}),
    # Hraniční případy.
    ("capacity_check", {"month": "2026-11"}),                       # note
    ("compute_invoice", {"project": "Neexistuje", "month": "2026-08"}),  # error
    ("neznamy_nastroj", {}),                                        # neznámý nástroj
    ("capacity_check", {"month": "2026-08", "target_hours": "160"}),    # coercion
]


async def probe(url: str) -> tuple[list[dict], list[dict]]:
    async with Client(url) as client:
        tools = [t.model_dump() for t in (await client.list_tools()).tools]
        results = []
        for name, arguments in CALLS:
            result = await client.call_tool(name, arguments)
            results.append(
                {
                    "is_error": result.is_error,
                    "content": [c.model_dump() for c in result.content],
                    "structured_content": result.structured_content,
                }
            )
    return tools, results


async def main_async(a: str, b: str) -> int:
    try:
        tools_a, results_a = await probe(a)
        tools_b, results_b = await probe(b)
    except Exception as exc:  # noqa: BLE001 — CLI má selhat srozumitelně
        print(
            f"Chyba: {type(exc).__name__}: {exc}\n"
            "Běží oba servery? `cd HW3 && docker compose up -d`",
            file=sys.stderr,
        )
        return 1

    problemy = 0

    if tools_a == tools_b:
        print(f"OK    tools/list — {len(tools_a)} nástrojů shodných")
    else:
        problemy += 1
        print(f"CHYBA tools/list se liší ({len(tools_a)} vs {len(tools_b)})")

    for (name, arguments), left, right in zip(CALLS, results_a, results_b, strict=True):
        popis = f"{name}({json.dumps(arguments, ensure_ascii=False)})"
        if left == right:
            print(f"OK    {popis}")
        else:
            problemy += 1
            print(f"CHYBA {popis}")
            print(f"        {a}: {json.dumps(left, ensure_ascii=False)[:200]}")
            print(f"        {b}: {json.dumps(right, ensure_ascii=False)[:200]}")

    print()
    if problemy:
        print(f"{problemy} odchylek z {len(CALLS) + 1} kontrol.")
        return 1
    print(f"Shodné do posledního bajtu: {len(CALLS)} volání + tools/list.")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", default=DEFAULT_A, help="Python server")
    ap.add_argument("--b", default=DEFAULT_B, help="C# proxy")
    args = ap.parse_args()
    return anyio.run(main_async, args.a, args.b)


if __name__ == "__main__":
    raise SystemExit(main())
