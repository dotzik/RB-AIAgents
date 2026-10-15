"""Politika přístupu: kdo je volající a za koho jedná.

Identita se odvozuje jen z HTTP hlaviček, které nastavuje volající služba,
nikdy z argumentů nástroje. Model hlavičky nevidí ani nenastaví.

Soubor politiky (TOML) spravuje vlastník a čte se při každém požadavku,
takže odebrání `chat_id` platí okamžitě, bez restartu. Tokeny v něm nejsou,
jen jejich SHA-256.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

CHAT_ID_HEADER = "x-timeagent-chat-id"
# Typ chatu z Telegram updatu (`message.chat.type`). Ve skupině je `chat.id`
# id skupiny, ne člověka, proto identitu uznáme jen v soukromém chatu.
CHAT_TYPE_HEADER = "x-timeagent-chat-type"
PRIVATE_CHAT = "private"
ROLES = {"owner", "client-proxy"}


class PolicyError(Exception):
    """Politiku nejde načíst. Gate pak zamítá vše (fail closed)."""


@dataclass(frozen=True)
class Service:
    name: str
    token_sha256: str
    role: str


@dataclass(frozen=True)
class Policy:
    services: tuple[Service, ...]
    clients: Mapping[str, str]  # chat_id -> projects.client
    owner_chat_ids: frozenset[str] = frozenset()  # vlastník přes Telegram


@dataclass(frozen=True)
class Identity:
    service: str
    role: str
    chat_id: str | None = None
    client: str | None = None  # vyplněno jen pro ověřeného klienta
    chat_type: str | None = None


def policy_path() -> Path:
    raw = os.environ.get("TIMEAGENT_POLICY")
    if not raw:
        raise PolicyError("TIMEAGENT_POLICY není nastavená")
    return Path(raw)


def load_policy(path: Path | None = None) -> Policy:
    path = path or policy_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"politiku nejde načíst: {type(exc).__name__}") from None

    services = []
    for name, cfg in (data.get("services") or {}).items():
        role = cfg.get("role")
        digest = str(cfg.get("token_sha256", "")).lower()
        if role not in ROLES or len(digest) != 64:
            raise PolicyError(f"služba {name!r}: neplatná role nebo hash tokenu")
        services.append(Service(name, digest, role))
    clients = {str(k): str(v) for k, v in (data.get("clients") or {}).items()}
    owners = frozenset(str(c) for c in (data.get("owner_chat_ids") or []))
    if owners & clients.keys():
        raise PolicyError("chat_id nesmí být zároveň vlastník i klient")
    return Policy(tuple(services), clients, owners)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate(policy: Policy, authorization: str | None) -> Service | None:
    """Služba podle `Authorization: Bearer <token>`, jinak None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    digest = hash_token(authorization.removeprefix("Bearer ").strip())
    for service in policy.services:
        if hmac.compare_digest(digest, service.token_sha256):
            return service
    return None


def resolve_identity(policy: Policy, headers: Mapping[str, str]) -> Identity | None:
    """Identita z hlaviček. None = neověřený volající."""
    service = authenticate(policy, headers.get("authorization"))
    if service is None:
        return None
    if service.role == "owner":
        return Identity(service.name, service.role)
    chat_id = (headers.get(CHAT_ID_HEADER) or "").strip() or None
    chat_type = (headers.get(CHAT_TYPE_HEADER) or "").strip().lower() or None
    if chat_type != PRIVATE_CHAT:
        # Bez soukromého chatu nevíme, kdo píše: nikdo, ani vlastník.
        return Identity(service.name, service.role, chat_id, None, chat_type)
    if chat_id in policy.owner_chat_ids:
        return Identity(service.name, "owner", chat_id, None, chat_type)
    client = policy.clients.get(chat_id) if chat_id else None
    return Identity(service.name, service.role, chat_id, client, chat_type)
