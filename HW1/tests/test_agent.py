"""Testy ReAct smyčky s podvrženým LLM.

Běží **bez API klíče a bez běžícího modelu** — ověřují mechaniku agenta, ne
kvalitu odpovědí modelu. Díky tomu je celá test suite spustitelná kdekoli.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from timeagent.agent import ReactAgent


def _tool_call(call_id: str, name: str, arguments) -> SimpleNamespace:
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(content=None, tool_calls=None, prompt_tokens=100, completion_tokens=20):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


class FakeLLM:
    """Přehraje připravenou sekvenci odpovědí a zapamatuje si, co dostal."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def __call__(self, messages, tools=None, **kwargs):
        self.calls.append([dict(m) for m in messages])
        if not self.responses:
            return _response(content="už nemám co říct")
        return self.responses.pop(0)


def test_single_tool_call(demo_db):
    fake = FakeLLM([
        _response(tool_calls=[
            _tool_call("c1", "capacity_check", {"month": "2026-08", "target_hours": 100})
        ]),
        _response(content="V srpnu jsi odpracoval dost."),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("Kolik mi chybí do 100 h?")

    assert result.answer == "V srpnu jsi odpracoval dost."
    assert result.iterations == 2
    assert [s.tool for s in result.steps] == ["capacity_check"]
    assert result.steps[0].result["month"] == "2026-08"
    assert not result.steps[0].failed


def test_tool_result_is_fed_back_to_model(demo_db):
    fake = FakeLLM([
        _response(tool_calls=[_tool_call("c1", "list_projects", {})]),
        _response(content="Projektů je pět."),
    ])
    ReactAgent(complete_fn=fake, trace=False).run("Jaké mám projekty?")

    # Druhé volání modelu už musí obsahovat zprávu role "tool" s výsledkem.
    second_call = fake.calls[1]
    tool_messages = [m for m in second_call if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "c1"
    assert "ACME" in tool_messages[0]["content"]
    # a předtím assistant zprávu s tool_calls
    assert any(m["role"] == "assistant" and m.get("tool_calls") for m in second_call)


def test_multiple_tool_calls_in_one_step(demo_db):
    """Model může v jednom kroku vyžádat víc nástrojů — musí se spustit všechny."""
    fake = FakeLLM([
        _response(tool_calls=[
            _tool_call("a", "summarize_by", {
                "dimension": "project",
                "date_from": "2026-07-01",
                "date_to": "2026-07-31",
            }),
            _tool_call("b", "summarize_by", {
                "dimension": "project",
                "date_from": "2026-08-01",
                "date_to": "2026-08-31",
            }),
        ]),
        _response(content="Porovnání hotovo."),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("Porovnej červenec a srpen")

    assert len(result.steps) == 2
    assert {s.arguments["date_from"] for s in result.steps} == {
        "2026-07-01", "2026-08-01"
    }
    assert len([m for m in fake.calls[1] if m["role"] == "tool"]) == 2


def test_sequential_reasoning(demo_db):
    """Řetězení: nejdřív zjisti projekty, pak spočítej fakturu."""
    fake = FakeLLM([
        _response(content="Nejdřív se podívám na projekty.",
                  tool_calls=[_tool_call("c1", "list_projects", {"active_only": True})]),
        _response(tool_calls=[
            _tool_call("c2", "compute_invoice", {"project": "ACME", "month": "2026-08"})
        ]),
        _response(content="Fakturovat můžeš."),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("Kolik fakturovat Acme?")

    assert [s.tool for s in result.steps] == ["list_projects", "compute_invoice"]
    assert result.iterations == 3
    assert result.steps[1].result["amount_incl_vat"] > 0


def test_tool_error_is_returned_to_model_not_raised(demo_db):
    fake = FakeLLM([
        _response(tool_calls=[
            _tool_call("c1", "compute_invoice", {"project": "Nexus", "month": "2026-08"})
        ]),
        _response(tool_calls=[
            _tool_call("c2", "compute_invoice", {"project": "ACME", "month": "2026-08"})
        ]),
        _response(content="Opraveno."),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("Fakturuj Nexus")

    assert result.steps[0].failed
    assert not result.steps[1].failed
    assert result.answer == "Opraveno."


def test_malformed_arguments_do_not_crash(demo_db):
    fake = FakeLLM([
        _response(tool_calls=[_tool_call("c1", "list_projects", "{tohle není JSON")]),
        _response(content="Zkusím to jinak."),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("?")
    assert result.steps[0].failed


def test_max_iterations_guard(demo_db):
    """Model, který nikdy neskončí, nesmí smyčku roztočit donekonečna.

    Každé volání má jiné argumenty, takže nejde o zacyklení — testuje se čistě
    strop počtu kroků.
    """
    looping = FakeLLM([
        _response(tool_calls=[
            _tool_call(f"c{i}", "capacity_check", {"month": f"2026-{i + 1:02d}"})
        ])
        for i in range(20)
    ])
    result = ReactAgent(complete_fn=looping, trace=False, max_iterations=3).run("?")

    assert result.iterations == 3
    assert len(result.steps) == 3
    assert "Vyčerpán limit" in result.answer


def test_token_accounting(demo_db):
    fake = FakeLLM([
        _response(tool_calls=[_tool_call("c1", "list_projects", {})],
                  prompt_tokens=100, completion_tokens=20),
        _response(content="hotovo", prompt_tokens=150, completion_tokens=30),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("?")
    assert result.prompt_tokens == 250
    assert result.completion_tokens == 50
    assert result.total_tokens == 300


def test_system_prompt_carries_todays_date(demo_db):
    from datetime import date

    fake = FakeLLM([_response(content="ok")])
    ReactAgent(complete_fn=fake, trace=False, today=date(2026, 8, 31)).run("?")
    system = fake.calls[0][0]
    assert system["role"] == "system"
    assert "2026-08-31" in system["content"]


def test_history_is_reused(demo_db):
    """REPL režim: druhá otázka navazuje na předchozí konverzaci."""
    fake = FakeLLM([_response(content="první"), _response(content="druhá")])
    agent = ReactAgent(complete_fn=fake, trace=False)
    first = agent.run("otázka 1")
    second = agent.run("otázka 2", history=first.messages)

    assert second.answer == "druhá"
    user_messages = [m for m in fake.calls[1] if m["role"] == "user"]
    assert [m["content"] for m in user_messages] == ["otázka 1", "otázka 2"]


# --------------------------------------------------------------------------
# Pojistky proti zacyklení
# --------------------------------------------------------------------------

def test_repeated_call_is_served_from_cache(demo_db):
    """Druhé identické volání se nespouští znovu — vrátí se uložený výsledek."""
    fake = FakeLLM([
        _response(tool_calls=[_tool_call("c1", "capacity_check", {"month": "2026-08"})]),
        _response(tool_calls=[_tool_call("c2", "capacity_check", {"month": "2026-08"})]),
        _response(content="hotovo"),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("?")

    assert result.steps[0].repeated is False
    assert result.steps[1].repeated is True
    assert "_poznamka" in result.steps[1].result
    # čísla zůstávají stejná, jen s poznámkou navíc
    assert result.steps[1].result["total_hours"] == result.steps[0].result["total_hours"]
    assert result.answer == "hotovo"


def test_looping_model_is_stopped_and_forced_to_answer(demo_db):
    """Model točící pořád totéž se zastaví a dostane šanci odpovědět bez nástrojů."""
    fake = FakeLLM([
        _response(tool_calls=[_tool_call(f"c{i}", "list_projects", {})])
        for i in range(3)
    ] + [_response(content="Projektů je pět.")])
    result = ReactAgent(complete_fn=fake, trace=False, max_iterations=8).run("?")

    assert result.answer == "Projektů je pět."
    assert result.iterations == 3  # 1 čerstvé volání + 2 opakování
    # poslední volání modelu proběhlo bez nástrojů
    assert len(fake.calls) == 4


def test_forced_answer_falls_back_when_model_stays_silent(demo_db):
    silent = FakeLLM([
        _response(tool_calls=[_tool_call(f"c{i}", "list_projects", {})])
        for i in range(3)
    ] + [_response(content=None)])
    result = ReactAgent(complete_fn=silent, trace=False, max_iterations=8).run("?")
    assert "zacyklil" in result.answer


def test_different_arguments_are_not_treated_as_repeat(demo_db):
    fake = FakeLLM([
        _response(tool_calls=[_tool_call("c1", "capacity_check", {"month": "2026-07"})]),
        _response(tool_calls=[_tool_call("c2", "capacity_check", {"month": "2026-08"})]),
        _response(content="porovnáno"),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("?")
    assert [s.repeated for s in result.steps] == [False, False]
    assert result.answer == "porovnáno"


# --------------------------------------------------------------------------
# Volání nástroje napsané jako text
# --------------------------------------------------------------------------

def test_parses_openai_shaped_textual_call():
    from timeagent.agent import parse_textual_tool_call

    text = ('{"id": "call_1", "type": "function", "function": {"name": "summarize_by", '
            '"arguments": {"dimension": "project", "date_from": "2026-08-01", '
            '"date_to": "2026-08-31"}}}')
    assert parse_textual_tool_call(text) == (
        "summarize_by",
        {"dimension": "project", "date_from": "2026-08-01", "date_to": "2026-08-31"},
    )


def test_parses_flat_shaped_textual_call():
    from timeagent.agent import parse_textual_tool_call

    assert parse_textual_tool_call('{"name": "list_projects", "parameters": {}}') == (
        "list_projects", {},
    )


def test_parses_call_wrapped_in_prose():
    from timeagent.agent import parse_textual_tool_call

    text = 'Zavolám nástroj: {"name": "capacity_check", "arguments": {"month": "2026-08"}}'
    assert parse_textual_tool_call(text) == ("capacity_check", {"month": "2026-08"})


def test_normal_answer_is_not_mistaken_for_a_call():
    from timeagent.agent import parse_textual_tool_call

    assert parse_textual_tool_call("V srpnu jsi odpracoval 179,5 hodiny.") is None
    assert parse_textual_tool_call('{"total_hours": 179.5}') is None   # výsledek, ne volání
    assert parse_textual_tool_call('{"name": "neznamy_nastroj"}') is None
    assert parse_textual_tool_call(None) is None


def test_textual_call_is_executed_and_fed_back(demo_db):
    """Reálné chování qwen2.5 na Ollamě: volání vypsané jako text."""
    fake = FakeLLM([
        _response(content='{"function": {"name": "capacity_check", '
                          '"arguments": {"month": "2026-08"}}}'),
        _response(content="V srpnu jsi odpracoval dost."),
    ])
    result = ReactAgent(complete_fn=fake, trace=False).run("?")

    assert [s.tool for s in result.steps] == ["capacity_check"]
    assert result.answer == "V srpnu jsi odpracoval dost."
    # výsledek se modelu vrátil a je v něm nabádání používat tool calling
    followup = [m for m in fake.calls[1] if m["role"] == "user"][-1]["content"]
    assert "total_hours" in followup
    assert "tool calling" in followup


def test_textual_call_rescue_is_limited(demo_db):
    """Model, který text posílá pořád, nesmí smyčku držet donekonečna."""
    stubborn = FakeLLM([
        _response(content='{"name": "capacity_check", "arguments": '
                          f'{{"month": "2026-0{i + 1}"}}}}')
        for i in range(6)
    ])
    result = ReactAgent(complete_fn=stubborn, trace=False).run("?")

    from timeagent.agent import MAX_TEXTUAL_RESCUES

    assert len(result.steps) == MAX_TEXTUAL_RESCUES
    # po vyčerpání záchran se text vrátí tak, jak přišel
    assert result.answer.startswith("{")
