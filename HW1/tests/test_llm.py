"""Testy volby poskytovatele — bez jakéhokoli síťového volání."""
from __future__ import annotations

from timeagent import llm


def test_model_prefers_prefixed_env(monkeypatch):
    monkeypatch.setenv("MODEL", "neco-ciziho")
    monkeypatch.setenv("TIMEAGENT_MODEL", "ollama/llama3.2:3b")
    assert llm.model_name() == "ollama/llama3.2:3b"


def test_model_falls_back_to_generic_env(monkeypatch):
    monkeypatch.delenv("TIMEAGENT_MODEL", raising=False)
    monkeypatch.setenv("MODEL", "ollama/qwen2.5:7b")
    assert llm.model_name() == "ollama/qwen2.5:7b"


def test_model_has_default(monkeypatch):
    monkeypatch.delenv("TIMEAGENT_MODEL", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    assert llm.model_name() == llm.DEFAULT_MODEL


def test_local_provider_keeps_api_base(monkeypatch):
    monkeypatch.setenv("TIMEAGENT_API_BASE", "http://localhost:11434")
    assert llm.api_base_for("ollama/llama3.2:3b") == "http://localhost:11434"
    assert llm.api_base_for("openai/qwen3-4b") == "http://localhost:11434"


def test_hosted_provider_ignores_stale_api_base(monkeypatch):
    """Po přepnutí na cloud nesmí v .env zbylý localhost přesměrovat volání."""
    monkeypatch.setenv("TIMEAGENT_API_BASE", "http://localhost:11434")
    for model in ("anthropic/claude-haiku-4-5", "gemini/gemini-2.0-flash"):
        assert llm.api_base_for(model) is None


def test_no_api_base_configured(monkeypatch):
    monkeypatch.delenv("TIMEAGENT_API_BASE", raising=False)
    monkeypatch.delenv("API_BASE", raising=False)
    assert llm.api_base_for("ollama/llama3.2:3b") is None


def test_usage_handles_missing_usage():
    from types import SimpleNamespace

    assert llm.usage_of(SimpleNamespace()) == (0, 0)
    assert llm.usage_of(
        SimpleNamespace(usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7))
    ) == (5, 7)


def test_workspace_header_only_for_anthropic(monkeypatch):
    """Identity-linked klíč potřebuje workspace; ostatní poskytovatelé ne."""
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_test")
    assert llm.extra_headers_for("anthropic/claude-haiku-4-5") == {
        "anthropic-workspace-id": "wrkspc_test"
    }
    assert llm.extra_headers_for("ollama/llama3.2:3b") is None


def test_no_workspace_header_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    assert llm.extra_headers_for("anthropic/claude-haiku-4-5") is None
