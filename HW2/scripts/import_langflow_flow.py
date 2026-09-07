"""Nahraje `flows/langflow/vykazy-agent.json` do běžícího LangFlow.

**Aktualizuje na místě**, nezakládá nový flow. `POST /api/v1/flows/` totiž pokaždé
vytvoří další kopii a LangFlow ji přejmenuje na „… (1)", „… (2)" — po pár
iteracích generátoru je v seznamu pět skoro stejných flow a není poznat, který
z nich je ten odevzdávaný. Skript proto flow **hledá podle jména** a existující
přepíše přes PATCH.

    python scripts/import_langflow_flow.py
    python scripts/import_langflow_flow.py --ask "Kolik hodin jsem odpracoval v srpnu 2026?"
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOW_FILE = ROOT / "flows" / "langflow" / "vykazy-agent.json"
LANGFLOW = "http://127.0.0.1:7860"
ENV_FILE = ROOT / ".env"

# Odevzdávaný flow má místo adresy Ollamy zástupný text, aby v repozitáři nebyla
# interní adresa. Sem se dosadí skutečná hodnota z `.env`.
OLLAMA_PLACEHOLDER = "http://OLLAMA-HOST:11434"

GZIP_MAGIC = bytes([0x1F, 0x8B])


def _request(method: str, path: str, token: str, payload: dict | None = None,
             *, as_api_key: bool = False) -> dict:
    """Volání LangFlow API.

    `as_api_key` přepne hlavičku na `x-api-key`. Endpoint `/api/v1/run` totiž
    Bearer token nebere — chce API klíč, a to i při zapnutém auto-loginu.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    req = urllib.request.Request(
        f"{LANGFLOW}{path}",
        data=body,
        method=method,
        headers={
            ("x-api-key" if as_api_key else "Authorization"):
                token if as_api_key else f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        # LangFlow odpovídá gzipem i při `Accept-Encoding: identity`.
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == GZIP_MAGIC:
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8")) if raw else {}


def ollama_base_url() -> str:
    """Adresa Ollamy z `.env`; bez ní by flow po nahrání neběžel."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("OLLAMA_BASE_URL="):
                return line.split("=", 1)[1].strip()
    sys.exit(f"V {ENV_FILE} chybí OLLAMA_BASE_URL — flow by neměl kam poslat dotaz.")


def token() -> str:
    """LangFlow běží s LANGFLOW_AUTO_LOGIN, takže token dá bez hesla."""
    with urllib.request.urlopen(f"{LANGFLOW}/api/v1/auto_login", timeout=15) as r:
        return json.load(r)["access_token"]


def api_key(tok: str) -> str:
    """Klíč pro `/api/v1/run` — endpoint ho vyžaduje i při zapnutém auto-loginu."""
    return _request("POST", "/api/v1/api_key/", tok, {"name": "hw2-import"})["api_key"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, default=FLOW_FILE)
    ap.add_argument("--ask", help="po nahrání položit flow tuhle otázku")
    args = ap.parse_args()

    if not args.file.exists():
        sys.exit(f"Chybí {args.file}. Vygeneruj ho:\n"
                 "  docker compose exec -T langflow python - "
                 "< scripts/build_langflow_flow.py > flows/langflow/vykazy-agent.json")

    raw = args.file.read_text(encoding="utf-8")
    if OLLAMA_PLACEHOLDER in raw:
        raw = raw.replace(OLLAMA_PLACEHOLDER, ollama_base_url())
        print(f"Adresa Ollamy dosazena z {ENV_FILE.name}")
    flow = json.loads(raw)
    name = flow["name"]

    try:
        tok = token()
    except urllib.error.URLError as exc:
        sys.exit(f"LangFlow na {LANGFLOW} neodpovídá ({exc}). Spusť: docker compose up -d")

    existing = [f for f in _request("GET", "/api/v1/flows/?get_all=true", tok)
                if f.get("name") == name]

    if existing:
        flow_id = existing[0]["id"]
        _request("PATCH", f"/api/v1/flows/{flow_id}", tok, flow)
        print(f"Aktualizován flow {flow_id} ({name})")
        for extra in existing[1:]:
            _request("DELETE", f"/api/v1/flows/{extra['id']}", tok)
            print(f"  smazán duplikát {extra['id']}")
    else:
        flow_id = _request("POST", "/api/v1/flows/", tok, flow)["id"]
        print(f"Založen flow {flow_id} ({name})")

    print(f"  UI: {LANGFLOW}/flow/{flow_id}")

    if args.ask:
        answer = _request("POST", f"/api/v1/run/{flow_id}", api_key(tok), {
            "input_value": args.ask,
            "input_type": "chat",
            "output_type": "chat",
            "session_id": "import-smoke",
        }, as_api_key=True)
        text = answer["outputs"][0]["outputs"][0]["results"]["message"]["text"]
        print(f"\n> {args.ask}\n{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
