"""Projede stejnou sadu dotazů oběma platformami a porovná je s pravdou z API.

Pravda se nebere z ručně opsaných čísel, ale počítá se **z téhož API**, které
volají agenti — test tak nezestárne, když se přegeneruje demo dataset.

    python scripts/compare_platforms.py                 # obě platformy
    python scripts/compare_platforms.py --only n8n
    python scripts/compare_platforms.py --json vysledky.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8000"
N8N_CHAT = "http://127.0.0.1:5678/webhook/vykazy-agent-chat/chat"
LANGFLOW = "http://127.0.0.1:7860"

GZIP_MAGIC = bytes([0x1F, 0x8B])

# Číslo s volitelným oddělovačem tisíců (mezera nebo nezlomitelná mezera).
NUMBER_RE = re.compile(r"\d{1,3}(?:[\s\u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")

# Sada vychází z benchmarku HW1 a schválně obsahuje i dotazy, na kterých se to
# tam lámalo: řetězení dvou období, ukončený projekt a období mimo data.
CASES: list[dict] = [
    {
        "id": "mesic",
        "question": "Kolik hodin jsem odpracoval v srpnu 2026?",
        "expect": lambda t: [t["srpen"]["total"]],
    },
    {
        # Hodiny musí sedět vždy; u částky stačí jedna z obou, protože „85 305 Kč
        # včetně DPH" je na tuhle otázku stejně dobrá odpověď jako základ bez DPH.
        "id": "faktura",
        "question": "Kolik jsem v srpnu 2026 nafakturoval klientovi Acme?",
        "expect": lambda t: [t["acme"]["hours"]],
        "any_number_of": lambda t: [t["acme"]["base"], t["acme"]["incl"]],
    },
    {
        "id": "nejvic",
        "question": "Na jakém projektu jsem v srpnu 2026 strávil nejvíc času?",
        "expect": lambda t: [t["srpen"]["top_hours"]],
        "must_contain": lambda t: [t["srpen"]["top"]],
    },
    {
        "id": "retezeni",
        "question": "Porovnej červenec a srpen 2026 — kolik hodin v každém?",
        "expect": lambda t: [t["cervenec"]["total"], t["srpen"]["total"]],
    },
    {
        "id": "projekty",
        "question": "Které projekty mám a jaké mají hodinové sazby?",
        "expect": lambda t: [t["sazby"]["acme"]],
    },
    {
        # Initech je ukončený projekt — v srpnu má nula hodin. Správná odpověď to
        # musí říct; hlídá se proto výskyt záporné formulace, ne konkrétní číslo.
        "id": "ukonceny",
        "question": "Pracoval jsem v srpnu 2026 na projektu Initech?",
        "expect": lambda t: [],
        "must_contain": lambda t: ["nepracoval", "žádn", "nula", "0 hodin", "neodpracoval"],
        "any_of": True,
    },
    {
        # Musí být opravdu mimo dataset. Dřív tu byl leden 2026 — po rozšíření dat
        # na leden 2025 už do rozsahu spadá a test hlásil chybu za správnou odpověď.
        "id": "mimo_data",
        "question": "Kolik hodin jsem odpracoval v červnu 2024?",
        "expect": lambda t: [],
        "must_contain": lambda t: ["nejsou", "žádn"],
        "any_of": True,
    },
    {
        "id": "kapacita",
        "question": "Splnil jsem v červnu 2026 cíl 160 hodin?",
        "expect": lambda t: [t["cerven"]["total"]],
    },
]


def _post(url: str, payload: dict, headers: dict | None = None, timeout: int = 600) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Accept-Encoding": "identity", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8"))


def _get(url: str, headers: dict | None = None) -> dict:
    import gzip
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == GZIP_MAGIC:
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def truth() -> dict:
    """Očekávané hodnoty spočítané z API — ne opsané konstanty."""
    def call(name: str, **params: str) -> dict:
        query = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        return _get(f"{API}/run/{name}?{query}")

    srpen = call("capacity_check", month="2026-08")
    rozpad = call("summarize_by", dimension="project",
                  date_from="2026-08-01", date_to="2026-08-31")
    top = rozpad["groups"][0]
    acme = call("compute_invoice", project="ACME", month="2026-08")
    projekty = _get(f"{API}/run/list_projects")

    return {
        "srpen": {"total": srpen["total_hours"], "top": top["bucket"], "top_hours": top["hours"]},
        "cervenec": {"total": call("capacity_check", month="2026-07")["total_hours"]},
        "cerven": {"total": call("capacity_check", month="2026-06")["total_hours"]},
        "acme": {"hours": acme["billable_hours"], "base": acme["amount_excl_vat"],
                 "incl": acme["amount_incl_vat"]},
        "sazby": {"acme": next(p["hourly_rate"] for p in projekty["projects"] if p["id"] == "ACME")},
    }


def _numbers(text: str) -> set[str]:
    """Čísla z odpovědi, znormalizovaná na porovnatelný tvar.

    Model píše `93 000` i `93000,0` i `179.5`. Mezera se jako oddělovač tisíců
    smí spojit jen s trojicí číslic — jinak by se `v srpnu 2026 179.5` slepilo
    do jednoho čísla a správná odpověď by se vyhodnotila jako chybná
    (stalo se při prvním měření).
    """
    out = set()
    for raw in NUMBER_RE.findall(text):
        cleaned = re.sub(r"[   ]", "", raw).replace(",", ".")
        try:
            out.add(f"{float(cleaned):g}")
        except ValueError:
            continue
    return out


def check(case: dict, answer: str, t: dict) -> tuple[bool, str]:
    found = _numbers(answer)
    missing = [f"{v:g}" for v in case["expect"](t) if f"{float(v):g}" not in found]
    if missing:
        return False, "chybí čísla: " + ", ".join(missing)

    alternatives = case.get("any_number_of", lambda _: [])(t)
    if alternatives and not any(f"{float(v):g}" in found for v in alternatives):
        return False, "chybí částka: " + " nebo ".join(f"{v:g}" for v in alternatives)

    needles = case.get("must_contain", lambda _: [])(t)
    if needles:
        low = answer.lower()
        hits = [n for n in needles if n.lower() in low]
        ok = bool(hits) if case.get("any_of") else len(hits) == len(needles)
        if not ok:
            return False, "chybí text: " + ", ".join(needles)
    return True, "ok"


def ask_n8n(question: str, session: str) -> str:
    out = _post(N8N_CHAT, {"action": "sendMessage", "sessionId": session, "chatInput": question})
    return out.get("output", "")


def ask_langflow(question: str, session: str, flow_id: str, api_key: str) -> str:
    out = _post(f"{LANGFLOW}/api/v1/run/{flow_id}",
                {"input_value": question, "input_type": "chat",
                 "output_type": "chat", "session_id": session},
                {"x-api-key": api_key})
    return out["outputs"][0]["outputs"][0]["results"]["message"]["text"]


def langflow_handles() -> tuple[str, str]:
    token = _get(f"{LANGFLOW}/api/v1/auto_login")["access_token"]
    flows = _get(f"{LANGFLOW}/api/v1/flows/?get_all=true", {"Authorization": f"Bearer {token}"})
    flow = next(f for f in flows if f.get("name") == "Výkazy — agent (HW2)")
    key = _post(f"{LANGFLOW}/api/v1/api_key/", {"name": "compare"},
                {"Authorization": f"Bearer {token}"})["api_key"]
    return flow["id"], key


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["n8n", "langflow"])
    ap.add_argument("--json", type=Path, help="uložit surové výsledky")
    args = ap.parse_args()

    try:
        t = truth()
    except urllib.error.URLError as exc:
        sys.exit(f"API na {API} neodpovídá ({exc}). Spusť: docker compose up -d")

    platforms = []
    if args.only != "langflow":
        platforms.append(("n8n", lambda q, s: ask_n8n(q, s)))
    if args.only != "n8n":
        flow_id, key = langflow_handles()
        platforms.append(("LangFlow", lambda q, s: ask_langflow(q, s, flow_id, key)))

    stamp = int(time.time())
    results: dict = {"truth": t, "runs": {}}

    for label, ask in platforms:
        print(f"\n=== {label} ===")
        rows = []
        for case in CASES:
            started = time.perf_counter()
            try:
                answer = ask(case["question"], f"cmp-{label}-{case['id']}-{stamp}")
                ok, note = check(case, answer, t)
            except Exception as exc:  # noqa: BLE001 — chyba platformy je taky výsledek
                answer, ok, note = "", False, f"selhalo: {type(exc).__name__}"
            secs = round(time.perf_counter() - started, 1)
            rows.append({"id": case["id"], "ok": ok, "note": note,
                         "seconds": secs, "answer": answer})
            print(f"  {'OK  ' if ok else 'CHYBA'} {case['id']:<10} {secs:>6}s  {note}")
        passed = sum(r["ok"] for r in rows)
        total_time = round(sum(r["seconds"] for r in rows), 1)
        print(f"  --- {passed}/{len(rows)} správně, {total_time} s celkem")
        results["runs"][label] = {"rows": rows, "passed": passed, "seconds": total_time}

    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSurová data: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
