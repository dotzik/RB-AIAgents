"""Tenká vrstva nad LiteLLM — jediné místo, kde je vidět poskytovatel.

Poskytovatel se přepíná v `.env` (`TIMEAGENT_MODEL`, volitelně
`TIMEAGENT_API_BASE`), ne v kódu.
Ollama, LM Studio, Anthropic i OpenAI mají každý jiný tvar tool-callingu;
LiteLLM je sjednocuje na OpenAI formát, takže smyčka agenta je pro všechny
jedna a tatáž.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Prefix `ollama_chat/`, ne `ollama/`: ten druhý používá starší cestu, na které
# novější modely (qwen3, gpt-oss) tiše vrátí prázdnou odpověď místo volání
# nástroje. Podrobnosti v docs/modely.md.
# Menší modely tool calling v této úloze nezvládají — viz docs/mereni.md.
DEFAULT_MODEL = "ollama_chat/qwen2.5:14b"


def _env(specific: str, generic: str) -> str | None:
    """Nejdřív jméno s prefixem, pak obecné.

    `MODEL` a `API_BASE` jsou tak obecné názvy, že je někdo může mít nastavené
    globálně pro něco úplně jiného. `TIMEAGENT_MODEL` má proto přednost.
    """
    return os.environ.get(specific) or os.environ.get(generic) or None


def model_name() -> str:
    return _env("TIMEAGENT_MODEL", "MODEL") or DEFAULT_MODEL


def api_base() -> str | None:
    return _env("TIMEAGENT_API_BASE", "API_BASE")


# Poskytovatelé s pevným endpointem. Poslat jim vlastní `api_base` znamená
# poslat požadavek jinam, než kam patří — typicky na localhost, který v .env
# zbyl po lokálním modelu.
_HOSTED_PREFIXES = ("anthropic/", "gemini/", "openrouter/", "xai/", "vertex_ai/")


def api_base_for(model: str) -> str | None:
    """Endpoint pro daný model, nebo None u poskytovatelů s pevnou adresou."""
    base = api_base()
    if base and model.startswith(_HOSTED_PREFIXES):
        return None
    return base


def extra_headers_for(model: str) -> dict[str, str] | None:
    """Hlavičky navíc pro daný model.

    Klíče Anthropicu navázané na identitu (identity-linked) vyžadují u každého
    požadavku hlavičku `anthropic-workspace-id` — bez ní API vrátí 400. Běžné
    klíče ji nepotřebují, proto se posílá jen když je workspace v prostředí.
    """
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace and model.startswith("anthropic/"):
        return {"anthropic-workspace-id": workspace}
    return None


class LLMError(RuntimeError):
    """Volání modelu selhalo — s nápovědou, co bývá příčinou."""


def complete(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    model: str | None = None,
    temperature: float = 0.0,
) -> Any:
    """Jedno volání LLM. Vrací odpověď v OpenAI tvaru (`choices[0].message`)."""
    import litellm  # import až tady — zdržuje start CLI o vteřiny

    litellm.drop_params = True  # ať neznámé parametry poskytovatele nespadnou

    kwargs: dict[str, Any] = {
        "model": model or model_name(),
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    base = api_base_for(kwargs["model"])
    if base:
        kwargs["api_base"] = base
    headers = extra_headers_for(kwargs["model"])
    if headers:
        kwargs["extra_headers"] = headers

    try:
        return litellm.completion(**kwargs)
    except Exception as exc:
        raise LLMError(
            f"Volání modelu {kwargs['model']!r} selhalo: {exc}\n"
            "Zkontroluj MODEL a API_BASE v .env; u lokálních modelů, jestli "
            "Ollama / LM Studio běží a jestli model umí tool calling."
        ) from exc


def usage_of(response: Any) -> tuple[int, int]:
    """(prompt_tokens, completion_tokens) — ne každý poskytovatel je vrací."""
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(
        getattr(usage, "completion_tokens", 0) or 0
    )
