"""Nahraje `flows/n8n/vykazy-agent-mcp.json` do běžícího n8n a aktivuje ho.

    python scripts/import_n8n_workflow.py
    python scripts/import_n8n_workflow.py --ask "Kolik hodin jsem odpracoval v srpnu 2026?"

Aktualizuje na místě — n8n si duplicitní jména nechá líbit.
Přihlašuje se vlastníkem z `HW2/.env` (zakládá ho `HW2/scripts/init-accounts.ps1`).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HW3 = ROOT / "HW3"
FLOW_FILE = HW3 / "flows" / "n8n" / "vykazy-agent-mcp.json"
N8N = "http://127.0.0.1:5678"
CHAT_PATH = "/webhook/vykazy-agent-mcp-chat/chat"

# n8n zapéká browser-id do tokenu a ověřuje ho — musí být u přihlášení
# i u všech dalších volání stejné.
BROWSER_ID = "hw3-import"

_auth_cookie: str | None = None


def _call(method: str, path: str, payload: dict | None = None, timeout: int = 60) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Encoding": "identity",
        "browser-id": BROWSER_ID,
    }
    # Ručně, ne přes CookieJar: n8n značkuje cookie jako `Secure`, takže by ji
    # jar přes prosté http neodeslal a každé volání by skončilo na 401.
    if _auth_cookie:
        headers["Cookie"] = f"n8n-auth={_auth_cookie}"

    req = urllib.request.Request(N8N + path, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        _capture_cookie(r.headers.get_all("Set-Cookie") or [])
    return json.loads(raw.decode("utf-8")) if raw else {}


def _capture_cookie(set_cookies: list[str]) -> None:
    global _auth_cookie
    for header in set_cookies:
        if header.startswith("n8n-auth="):
            _auth_cookie = header.split(";", 1)[0].removeprefix("n8n-auth=")


def env_value(path: Path, key: str) -> str:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    sys.exit(f"V {path} chybí {key}.")


def login() -> None:
    env = ROOT / "HW2" / ".env"
    _call(
        "POST",
        "/rest/login",
        {
            "emailOrLdapLoginId": env_value(env, "N8N_OWNER_EMAIL"),
            "password": env_value(env, "N8N_OWNER_PASSWORD"),
        },
    )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, default=FLOW_FILE)
    ap.add_argument("--ask", help="po nahrání položit workflow tuhle otázku")
    args = ap.parse_args()

    if not args.file.exists():
        sys.exit(
            f"Chybí {args.file}. Vygeneruj ho:\n"
            "  python scripts/build_n8n_workflow.py --credential-id <id>"
        )
    flow = json.loads(args.file.read_text(encoding="utf-8"))
    name = flow["name"]

    try:
        login()
    except urllib.error.URLError as exc:
        sys.exit(
            f"n8n na {N8N} neodpovídá ({exc}). "
            "Spusť HW2 stack: docker compose -p rb-aiagents up -d"
        )

    existing = [w for w in _call("GET", "/rest/workflows")["data"] if w["name"] == name]
    payload = {
        "name": name,
        "nodes": flow["nodes"],
        "connections": flow["connections"],
        "settings": flow["settings"],
    }

    if existing:
        workflow_id = existing[0]["id"]
        _call("PATCH", f"/rest/workflows/{workflow_id}", payload)
        print(f"Aktualizováno workflow {workflow_id} ({name})")
        for extra in existing[1:]:
            _call("DELETE", f"/rest/workflows/{extra['id']}")
            print(f"  smazán duplikát {extra['id']}")
    else:
        workflow_id = _call("POST", "/rest/workflows", payload)["data"]["id"]
        print(f"Založeno workflow {workflow_id} ({name})")

    # Bez aktivace webhook chatu neexistuje → 404.
    version = _call("GET", f"/rest/workflows/{workflow_id}")["data"]["versionId"]
    _call("POST", f"/rest/workflows/{workflow_id}/activate", {"versionId": version})
    print(f"  aktivováno, UI: {N8N}/workflow/{workflow_id}")

    if args.ask:
        out = _call(
            "POST",
            CHAT_PATH,
            {"action": "sendMessage", "sessionId": "hw3-import-smoke", "chatInput": args.ask},
            timeout=300,
        )
        print(f"\n> {args.ask}\n{out.get('output', out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
