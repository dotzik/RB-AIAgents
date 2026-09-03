"""Příkazová řádka.

    uv run timeagent seed                   # vygeneruje anonymní demo databázi
    uv run timeagent tools                  # vypíše nástroje a jejich schémata
    uv run timeagent ask "..."              # jeden dotaz
    uv run timeagent chat                   # konverzace s pamětí
    uv run timeagent import --month 2026-08 # volitelně reálná data z Clockify
    uv run timeagent bench --models a,b      # srovnání modelů na stejných dotazech
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from . import agent as agent_mod
from . import db, llm, seed, tools


def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _apply_db_option(path: str | None) -> None:
    if path:
        os.environ["TIMEAGENT_DB"] = path


# --------------------------------------------------------------------------
# Příkazy
# --------------------------------------------------------------------------

def cmd_seed(args: argparse.Namespace) -> int:
    path = Path(os.environ.get("TIMEAGENT_DB") or db.default_db_path())
    conn = db.connect_rw(path)
    try:
        counts = seed.seed_database(conn, months=args.months, rng_seed=args.rng_seed)
    finally:
        conn.close()
    print(f"Databáze: {path}")
    print(f"Vloženo: {counts['projects']} projektů, {counts['time_entries']} záznamů "
          f"za posledních {args.months} měsíců.")
    print("Data jsou vygenerovaná a anonymní — žádný reálný klient.")
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(tools.TOOL_SCHEMAS, ensure_ascii=False, indent=2))
        return 0
    for schema in tools.TOOL_SCHEMAS:
        fn = schema["function"]
        params = fn["parameters"]
        required = set(params.get("required", []))
        print(f"\n{fn['name']}")
        print(f"  {fn['description']}")
        for pname, prop in params.get("properties", {}).items():
            flag = "povinné" if pname in required else "volitelné"
            print(f"    - {pname} ({prop.get('type')}, {flag}): {prop.get('description', '')}")
    print()
    return 0


def _run_agent(question: str, args: argparse.Namespace, history=None):
    a = agent_mod.ReactAgent(
        model=args.model,
        max_iterations=args.max_iterations,
        trace=not args.quiet,
    )
    result = a.run(question, history=history)
    print("\n" + "=" * 72)
    print(result.answer)
    print("=" * 72)
    if not args.quiet:
        print(
            f"model: {result.model} | kroků: {result.iterations} | "
            f"volání nástrojů: {len(result.steps)} | tokeny: {result.total_tokens}"
        )
    return result


def cmd_ask(args: argparse.Namespace) -> int:
    question = " ".join(args.question)
    print(f"Otázka: {question}")
    try:
        _run_agent(question, args)
    except llm.LLMError as exc:
        print(f"\nCHYBA: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    print(f"timeagent — model {args.model or llm.model_name()}. Konec: prázdný řádek "
          "nebo Ctrl+C.\n")
    history = None
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            return 0
        try:
            result = _run_agent(question, args, history=history)
            history = result.messages
        except llm.LLMError as exc:
            print(f"\nCHYBA: {exc}", file=sys.stderr)


def cmd_bench(args: argparse.Namespace) -> int:
    from . import bench

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    outcomes = bench.run(
        models,
        api_base=args.api_base,
        max_iterations=args.max_iterations,
        trace=args.trace,
    )
    print()
    print(bench.to_markdown(outcomes))
    if args.json:
        print()
        print(json.dumps(bench.as_rows(outcomes), ensure_ascii=False, indent=2))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from .importers import clockify

    path = Path(os.environ.get("TIMEAGENT_DB") or db.default_db_path())
    conn = db.connect_rw(path)
    try:
        counts = clockify.import_month(
            conn, month=args.month, replace=not args.append, verbose=True
        )
    except clockify.ClockifyError as exc:
        print(f"CHYBA: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Naimportováno: {counts['projects']} projektů, "
          f"{counts['time_entries']} záznamů za {args.month} do {path}.")
    print("POZOR: databáze teď obsahuje reálná data — je v .gitignore, necommituj ji.")
    return 0


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timeagent",
        description="ReAct agent nad výkazy odpracovaného času",
    )
    parser.add_argument("--db", help="cesta k SQLite databázi (jinak TIMEAGENT_DB)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_seed = sub.add_parser("seed", help="vygenerovat anonymní demo databázi")
    p_seed.add_argument("--months", type=int, default=6, help="kolik měsíců zpět (6)")
    p_seed.add_argument("--rng-seed", type=int, default=42, help="seed generátoru (42)")
    p_seed.set_defaults(func=cmd_seed)

    p_tools = sub.add_parser("tools", help="vypsat dostupné nástroje")
    p_tools.add_argument("--json", action="store_true", help="surová JSON schémata")
    p_tools.set_defaults(func=cmd_tools)

    def add_agent_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", help="přebije TIMEAGENT_MODEL z .env")
        p.add_argument("--quiet", action="store_true", help="bez výpisu kroků")
        p.add_argument("--max-iterations", type=int, default=agent_mod.MAX_ITERATIONS)

    p_ask = sub.add_parser("ask", help="jeden dotaz")
    p_ask.add_argument("question", nargs="+")
    add_agent_options(p_ask)
    p_ask.set_defaults(func=cmd_ask)

    p_chat = sub.add_parser("chat", help="konverzace s pamětí")
    add_agent_options(p_chat)
    p_chat.set_defaults(func=cmd_chat)

    p_bench = sub.add_parser("bench", help="srovnat modely na stejné sadě dotazů")
    p_bench.add_argument("--models", required=True,
                         help="seznam modelů oddělený čárkou")
    p_bench.add_argument("--api-base", help="endpoint pro všechny modely v běhu")
    p_bench.add_argument("--max-iterations", type=int, default=agent_mod.MAX_ITERATIONS)
    p_bench.add_argument("--trace", action="store_true", help="vypisovat i kroky")
    p_bench.add_argument("--json", action="store_true", help="přidat surová data")
    p_bench.set_defaults(func=cmd_bench)

    p_imp = sub.add_parser("import", help="načíst reálná data z Clockify (volitelné)")
    p_imp.add_argument("--month", default=date.today().strftime("%Y-%m"),
                       help="měsíc YYYY-MM (výchozí aktuální)")
    p_imp.add_argument("--append", action="store_true",
                       help="nemazat existující záznamy daného měsíce")
    p_imp.set_defaults(func=cmd_import)

    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    args = build_parser().parse_args(argv)
    _apply_db_option(args.db)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
