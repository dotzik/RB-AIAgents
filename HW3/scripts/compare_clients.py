"""Projede stejnou sadu dotazů klienty HW3 a porovná je s pravdou.

    python scripts/compare_clients.py --repeat 3
    python scripts/compare_clients.py --only langgraph
    python scripts/compare_clients.py --json vysledky.json

Sada dotazů a hodnocení se importují z `HW2/scripts/compare_platforms.py`,
aby čísla zůstala srovnatelná s HW2. Očekávané hodnoty se počítají
z `timeagent.tools`, ne z konstant — měření nezestárne s novým datasetem.

Běhy se opakují ze stejného důvodu, jaký popisuje HW1/docs/mereni.md: odpověď,
která visí na hraně, se mezi běhy překlápí i při temperature 0. Jeden průchod
by z toho udělal vlastnost klienta.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "HW1" / "src"))
sys.path.insert(0, str(ROOT / "HW2" / "scripts"))

# Sada dotazů a hodnocení z HW2 — viz docstring; HW2 se nemění.
from compare_platforms import CASES, check
from timeagent import tools

HW3 = ROOT / "HW3"

CLIENTS: dict[str, list[str]] = {
    "langgraph": [
        "uv", "run", "--project", str(HW3 / "agents" / "langgraph"),
        "lgagent", "ask", "{question}", "--json",
    ],
    "pydantic": [
        "uv", "run", "--project", str(HW3 / "agents" / "python"),
        "mcpagent", "ask", "{question}", "--json",
    ],
    "dotnet": [
        "dotnet", "run", "--project",
        str(HW3 / "agents" / "dotnet" / "McpAgent"), "--no-build", "--",
        "ask", "{question}", "--json",
    ],
}

LABELS = {
    "langgraph": "LangGraph",
    "pydantic": "Pydantic AI",
    "dotnet": "Microsoft Agent Framework",
}


def truth() -> dict:
    """Očekávané hodnoty spočítané z nástrojů. Tvar se řídí sadou z HW2."""
    srpen = tools.call_tool("capacity_check", {"month": "2026-08"})
    rozpad = tools.call_tool(
        "summarize_by",
        {"dimension": "project", "date_from": "2026-08-01", "date_to": "2026-08-31"},
    )
    top = rozpad["groups"][0]
    acme = tools.call_tool("compute_invoice", {"project": "ACME", "month": "2026-08"})
    projekty = tools.call_tool("list_projects", {})

    return {
        "srpen": {
            "total": srpen["total_hours"],
            "top": top["bucket"],
            "top_hours": top["hours"],
        },
        "cervenec": {
            "total": tools.call_tool("capacity_check", {"month": "2026-07"})["total_hours"]
        },
        "cerven": {
            "total": tools.call_tool("capacity_check", {"month": "2026-06"})["total_hours"]
        },
        "acme": {
            "hours": acme["billable_hours"],
            "base": acme["amount_excl_vat"],
            "incl": acme["amount_incl_vat"],
        },
        "sazby": {
            "acme": next(
                p["hourly_rate"] for p in projekty["projects"] if p["id"] == "ACME"
            )
        },
    }


def ask(client: str, question: str) -> dict:
    """Spustí klienta jako podproces. CLI je jediné společné rozhraní
    Pythonu a .NETu; měří se tím i start procesu, u obou stejně."""
    cmd = [part.replace("{question}", question) for part in CLIENTS[client]]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        timeout=600, check=False,   # nenulový návrat je výsledek, ne důvod k pádu
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError((proc.stderr or "").strip()[-300:] or f"exit {proc.returncode}")
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    if "error" in payload and "answer" not in payload:
        raise RuntimeError(payload["error"])
    return payload


def run_once(client: str, t: dict) -> list[dict]:
    rows = []
    for case in CASES:
        started = time.perf_counter()
        try:
            out = ask(client, case["question"])
            answer = out["answer"]
            ok, note = check(case, answer, t)
            calls = out.get("tool_calls", [])
        except Exception as exc:  # noqa: BLE001 — selhání klienta je taky výsledek
            answer, ok, note, calls = "", False, f"selhalo: {exc}", []
        rows.append(
            {
                "id": case["id"],
                "ok": ok,
                "note": note,
                "seconds": round(time.perf_counter() - started, 1),
                "tool_call_count": len(calls),
                # Trasa volání, ne jen jejich počet: bez ní se pád nedá po týdnu
                # vysvětlit a diagnóza v dokumentaci není doložitelná.
                "tool_calls": calls,
                "answer": answer,
            }
        )
        stav = "OK   " if ok else "CHYBA"
        print(f"  {stav} {case['id']:<10} {rows[-1]['seconds']:>6}s  "
              f"{len(calls)} volání  {note}")
    return rows


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=sorted(CLIENTS))
    ap.add_argument("--repeat", type=int, default=3, help="kolik běhů na klienta")
    ap.add_argument("--json", type=Path, help="uložit surové výsledky")
    args = ap.parse_args()

    t = truth()
    if t["srpen"]["total"] == 0:
        sys.exit(
            "Databáze nemá data za srpen 2026. Přegeneruj ji: "
            "cd HW1 && uv run timeagent seed --months 21"
        )

    chosen = [args.only] if args.only else list(CLIENTS)
    results: dict = {"truth": t, "repeat": args.repeat, "runs": {}}

    for client in chosen:
        runs = []
        for n in range(args.repeat):
            print(f"\n=== {client} ({LABELS[client]}) — běh {n + 1}/{args.repeat} ===")
            rows = run_once(client, t)
            passed = sum(r["ok"] for r in rows)
            total = round(sum(r["seconds"] for r in rows), 1)
            print(f"  --- {passed}/{len(rows)} správně, {total} s")
            runs.append({"rows": rows, "passed": passed, "seconds": total})

        scores = [r["passed"] for r in runs]
        times = sorted(s for r in runs for s in (x["seconds"] for x in r["rows"]))
        # Které případy padly aspoň jednou — to je jediné, co jde z pár běhů
        # poctivě tvrdit. Skóre jednoho běhu je u hraničních dotazů hod mincí.
        flaky = sorted({row["id"] for r in runs for row in r["rows"] if not row["ok"]})
        results["runs"][client] = {
            "label": LABELS[client],
            "runs": runs,
            "scores": scores,
            "best": max(scores),
            "worst": min(scores),
            "median_seconds": times[len(times) // 2],
            "failed_at_least_once": flaky,
        }
        print(f"\n  === {LABELS[client]}: {scores} z {len(CASES)}, "
              f"medián {times[len(times) // 2]} s")
        if flaky:
            print(f"      aspoň jednou padlo: {', '.join(flaky)}")

    if args.json:
        args.json.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nSurová data: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
