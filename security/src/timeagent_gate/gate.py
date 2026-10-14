"""Rozhodnutí gate: smí tato identita zavolat tento nástroj s těmito argumenty?

Vše kromě identity je nedůvěryhodné, včetně argumentů nástroje. Projekt
klienta se vyhodnocuje jen mezi jeho vlastními projekty a nástroji se předá
už rozpoznané `id`. Částečná shoda v `tools._resolve_project` tak nemůže
trefit cizí projekt a chybová hláška nevypíše cizí projekty.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from timeagent import db, tools

from .policy import Identity

# Nástroje, které klient smí volat, a zda vyžadují projekt.
CLIENT_TOOLS = {
    "list_projects": False,
    "query_time_entries": True,
    "summarize_by": True,
    "compute_invoice": True,
}
_SCHEMA_PROPS = {
    s["function"]["name"]: set(s["function"]["parameters"]["properties"])
    for s in tools.TOOL_SCHEMAS
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict)
    message: str = ""


def _own_projects(client: str) -> list[sqlite3.Row]:
    with closing(db.connect_ro()) as conn:
        return conn.execute(
            "SELECT id, name FROM projects WHERE client = ? ORDER BY id", (client,)
        ).fetchall()


def _match(own: list[sqlite3.Row], needle: str) -> list[sqlite3.Row]:
    needle = needle.strip().lower()
    exact = [p for p in own if p["id"].lower() == needle]
    if exact:
        return exact
    return [p for p in own if needle and needle in p["name"].lower()]


def _listing(own: list[sqlite3.Row]) -> str:
    return ", ".join(f"{p['id']} ({p['name']})" for p in own) or "žádné"


def authorize(identity: Identity | None, name: str, arguments: dict[str, Any]) -> Decision:
    if identity is None:
        return Decision(False, "unauthenticated", message="Neověřený volající.")
    if identity.role == "owner":
        return Decision(True, "owner", dict(arguments))
    if identity.role != "client-proxy":
        return Decision(False, "unknown_role", message="Přístup zamítnut.")
    if identity.chat_id is None:
        return Decision(False, "missing_chat_id", message="Chybí identita uživatele.")
    if identity.client is None:
        return Decision(False, "unknown_chat_id", message="Tento účet nemá přístup.")

    if name not in CLIENT_TOOLS:
        return Decision(False, "tool_not_allowed", message="Tento dotaz není pro klienty dostupný.")

    # Argumenty mimo schéma (např. podvržené `chat_id`) se zahodí.
    args = {k: v for k, v in arguments.items() if k in _SCHEMA_PROPS[name]}

    if name == "summarize_by" and str(args.get("dimension", "")).lower() == "client":
        return Decision(False, "dimension_not_allowed", message="Souhrn přes klienty není dostupný.")

    if not CLIENT_TOOLS[name]:
        return Decision(True, "client_scoped", args)

    own = _own_projects(identity.client)
    needle = str(args.get("project") or "")
    if not needle:
        return Decision(
            False, "project_required",
            message=f"Uveďte projekt. Vaše projekty: {_listing(own)}",
        )
    found = _match(own, needle)
    if len(found) != 1:
        reason = "project_ambiguous" if found else "project_not_allowed"
        return Decision(
            False, reason,
            message=f"Projekt není dostupný nebo není jednoznačný. Vaše projekty: {_listing(own)}",
        )
    args["project"] = found[0]["id"]
    return Decision(True, "client_scoped", args)


def filter_result(identity: Identity | None, name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Zúží výstup `list_projects` na projekty klienta."""
    if identity is None or identity.role == "owner" or name != "list_projects":
        return result
    if "projects" not in result:
        return result
    own = [p for p in result["projects"] if p.get("client") == identity.client]
    return {**result, "count": len(own), "projects": own}


def audit(identity: Identity | None, tool: str | None, arguments: Any, allowed: bool, reason: str) -> None:
    """Jeden řádek JSON na rozhodnutí. Bez cesty v env se neloguje."""
    path = os.environ.get("TIMEAGENT_AUDIT_LOG")
    if not path:
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "service": identity.service if identity else None,
        "role": identity.role if identity else None,
        "chat_id": identity.chat_id if identity else None,
        "client": identity.client if identity else None,
        "tool": tool,
        "arguments": arguments,
        "decision": "allow" if allowed else "deny",
        "reason": reason,
    }
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
