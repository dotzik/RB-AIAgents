"""ReAct smyčka.

Reasoning + Acting: model střídavě uvažuje a volá nástroje, dokud nemá dost
podkladů na odpověď. Výsledek každého nástroje se vrací zpátky do konverzace,
takže na něj model může navázat dalším krokem — právě to odlišuje agenta od
jednorázového volání API.

    otázka → [ model → tool_calls? → spustit nástroje → výsledky zpět ] → odpověď
                 ^                                                  |
                 +--------------------------------------------------+
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import llm, tools

MAX_ITERATIONS = 8
# Kolikrát smíme za model spustit nástroj, který napsal jen jako text.
MAX_TEXTUAL_RESCUES = 2
# Po kolika po sobě jdoucích krocích bez nového výsledku vynutíme závěr.
MAX_REPEATED_STEPS = 2

SYSTEM_PROMPT = """\
Jsi asistent pro analýzu výkazů odpracovaného času. Odpovídáš česky, stručně a věcně.

Pravidla:
- Čísla nikdy neodhaduj ani nepočítej zpaměti — vždy je zjisti nástrojem.
- Když neznáš přesný název projektu, nejdřív si vypiš projekty nástrojem list_projects.
- Data zadávej v ISO formátu (YYYY-MM-DD), měsíce jako YYYY-MM.
- Složitější dotaz rozlož na víc volání nástrojů za sebou (např. porovnání dvou období
  = dvě volání) a teprve pak odpověz.
- Nepovinný parametr prostě vynech — neposílej "null" ani prázdný řetězec.
- Nevolej dvakrát tentýž nástroj se stejnými argumenty; výsledek už máš výš.
- Když nástroj vrátí pole "error", oprav argumenty a zkus to znovu.
- Chybovou hlášku z nástroje nikdy nepiš do odpovědi jako výsledek.
- V odpovědi uveď konkrétní čísla, u peněz i měnu.

Dnešní datum je {today} ({weekday}). Aktuální měsíc je {month}.
"""

_WEEKDAYS = [
    "pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle",
]


def build_system_prompt(today: date | None = None) -> str:
    d = today or date.today()
    return SYSTEM_PROMPT.format(
        today=d.isoformat(), weekday=_WEEKDAYS[d.weekday()], month=d.strftime("%Y-%m")
    )


@dataclass
class Step:
    """Jeden proběhlý krok: co model zavolal a co dostal zpátky."""

    iteration: int
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    repeated: bool = False

    @property
    def failed(self) -> bool:
        return "error" in self.result


@dataclass
class AgentResult:
    """Výsledek jednoho dotazu: odpověď, průběh a spotřeba.

    `messages` je celá konverzace včetně volání nástrojů — dá se předat
    do dalšího `run()` jako `history` a navázat na ni.
    """

    answer: str
    steps: list[Step] = field(default_factory=list)
    iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _arguments_to_dict(raw: Any) -> dict[str, Any]:
    """Argumenty chodí jako JSON string (OpenAI) i jako hotový dict (Ollama)."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"__unparsable__": str(raw)}
    return parsed if isinstance(parsed, dict) else {"__unparsable__": str(raw)}


def _arguments_to_str(raw: Any) -> str:
    return raw if isinstance(raw, str) else json.dumps(raw or {}, ensure_ascii=False)


def _candidate_bodies(payload: Any) -> list[dict[str, Any]]:
    """Místa, kde v podvrženém JSON může být popis volání nástroje.

    Modely to balí různě: `{"name": ...}`, `{"function": {...}}` nebo celý
    `{"response": {"tool_calls": [{"function": {...}}]}}`. Rozbalíme všechny
    tvary, které jsme v praxi viděli, a necháme rozhodnout jméno nástroje.
    """
    if not isinstance(payload, dict):
        return []

    bodies: list[dict[str, Any]] = [payload]
    if isinstance(payload.get("function"), dict):
        bodies.append(payload["function"])

    for klic in ("response", "message"):
        vnorene = payload.get(klic)
        if isinstance(vnorene, dict):
            bodies.extend(_candidate_bodies(vnorene))

    volani = payload.get("tool_calls")
    if isinstance(volani, list):
        for polozka in volani:
            bodies.extend(_candidate_bodies(polozka))

    return bodies


def parse_textual_tool_call(content: str | None) -> tuple[str, dict[str, Any]] | None:
    """Rozpozná volání nástroje, které model napsal jako text.

    Slabší modely občas místo skutečného `tool_calls` vypíšou jeho JSON do
    odpovědi. Turn formálně skončí bez volání nástroje, takže by se ten text
    vrátil uživateli jako výsledek. Tady se z něj vytáhne jméno a argumenty,
    aby smyčka mohla pokračovat.

    Za volání se považuje jen JSON, jehož `name` odpovídá skutečnému nástroji —
    běžná odpověď ani výsledek nástroje tou podmínkou neprojdou.
    """
    if not content:
        return None
    text = content.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except (TypeError, ValueError):
        return None

    for body in _candidate_bodies(payload):
        name = body.get("name")
        if not isinstance(name, str) or name not in tools.REGISTRY:
            continue
        arguments = body.get("arguments", body.get("parameters", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError):
                continue
        if isinstance(arguments, dict):
            return name, arguments
    return None


class ReactAgent:
    """Provider-agnostický ReAct agent nad nástroji z `tools.REGISTRY`."""

    def __init__(
        self,
        *,
        model: str | None = None,
        max_iterations: int = MAX_ITERATIONS,
        trace: bool = True,
        complete_fn: Callable[..., Any] | None = None,
        today: date | None = None,
    ) -> None:
        self.model = model or llm.model_name()
        self.max_iterations = max_iterations
        self.trace = trace
        self._complete = complete_fn or llm.complete
        self.today = today
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    # -- výpis průběhu ----------------------------------------------------

    def _emit(self, text: str) -> None:
        if self.trace:
            print(text, flush=True)

    def _emit_thought(self, content: str | None) -> None:
        if content and content.strip():
            self._emit(f"  úvaha: {content.strip()}")

    def _emit_step(self, step: Step) -> None:
        args = ", ".join(f"{k}={v!r}" for k, v in step.arguments.items())
        self._emit(f"  nástroj: {step.tool}({args})")
        preview = json.dumps(step.result, ensure_ascii=False, default=str)
        if len(preview) > 220:
            preview = preview[:220] + "…"
        marker = "chyba" if step.failed else "výsledek"
        if step.repeated:
            marker += " (opakované volání, vzato z paměti)"
        self._emit(f"  {marker}: {preview}")

    # -- pojistky proti zacyklení -----------------------------------------

    def _execute(self, name: str, arguments: dict[str, Any], iteration: int) -> Step:
        """Spustí nástroj, nebo vrátí zapamatovaný výsledek.

        Slabší modely mají sklon volat pořád dokola totéž místo aby odpověděly.
        Opakované volání se proto neprovádí znovu — vrátí se uložený výsledek
        s poznámkou, která modelu říká, ať už odpoví.
        """
        key = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str))
        cached = self._cache.get(key)
        if cached is not None:
            result = dict(cached)
            result["_poznamka"] = (
                "Tenhle nástroj jsi už volal se stejnými argumenty. Další volání "
                "nic nepřinese — odpověz uživateli z toho, co víš."
            )
            return Step(iteration, name, arguments, result, repeated=True)

        result = tools.call_tool(name, arguments)
        self._cache[key] = result
        return Step(iteration, name, arguments, result)

    def _force_answer(self, messages: list[dict[str, Any]], result: AgentResult) -> str:
        """Poslední volání bez nástrojů — model musí odpovědět textem.

        Použije se, když se model zacyklil nebo vyčerpal limit kroků. Podklady
        v konverzaci už má; jen se mu odebere možnost sáhnout po dalším nástroji.
        """
        self._emit("  model se netrhne od nástrojů — vynucuji závěr bez nich")
        nudge = [
            *messages,
            {
                "role": "user",
                "content": "Shrň teď odpověď z podkladů výše. Další nástroje nevolej.",
            },
        ]
        try:
            response = self._complete(nudge, None, model=self.model)
        except Exception:  # noqa: BLE001 — vynucený závěr je bonus, ne povinnost
            return ""
        prompt_tokens, completion_tokens = llm.usage_of(response)
        result.prompt_tokens += prompt_tokens
        result.completion_tokens += completion_tokens
        return (getattr(response.choices[0].message, "content", None) or "").strip()

    # -- vlastní smyčka ---------------------------------------------------

    def run(
        self, question: str, history: list[dict[str, Any]] | None = None
    ) -> AgentResult:
        messages: list[dict[str, Any]] = list(history) if history else [
            {"role": "system", "content": build_system_prompt(self.today)}
        ]
        messages.append({"role": "user", "content": question})

        # Dedup je v rámci jedné otázky; nová otázka smí nástroje volat znovu.
        self._cache.clear()

        result = AgentResult(answer="", model=self.model, messages=messages)
        repeated_only = 0
        rescues = 0

        for iteration in range(1, self.max_iterations + 1):
            self._emit(f"\n--- krok {iteration} ---")
            response = self._complete(messages, tools.TOOL_SCHEMAS, model=self.model)

            prompt_tokens, completion_tokens = llm.usage_of(response)
            result.prompt_tokens += prompt_tokens
            result.completion_tokens += completion_tokens

            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []
            content = getattr(message, "content", None)

            if not tool_calls:
                textual = parse_textual_tool_call(content)
                if textual and rescues < MAX_TEXTUAL_RESCUES:
                    rescues += 1
                    name, arguments = textual
                    self._emit("  model napsal volání nástroje jako text — spouštím ho")
                    step = self._execute(name, arguments, iteration)
                    result.steps.append(step)
                    self._emit_step(step)
                    messages.append({"role": "assistant", "content": content or ""})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Nástroj {name} jsem spustil za tebe, tady je výsledek: "
                            + json.dumps(step.result, ensure_ascii=False, default=str)
                            + " Příště nástroj volej přes tool calling, ne textem. "
                            "Teď pokračuj."
                        ),
                    })
                    continue

                self._emit("  hotovo — model už nepotřebuje nástroj")
                result.answer = (content or "").strip()
                result.iterations = iteration
                messages.append({"role": "assistant", "content": result.answer})
                return result

            self._emit_thought(content)

            messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": _arguments_to_str(tc.function.arguments),
                        },
                    }
                    for tc in tool_calls
                ],
            })

            fresh = 0
            for tc in tool_calls:
                arguments = _arguments_to_dict(tc.function.arguments)
                step = self._execute(tc.function.name, arguments, iteration)
                fresh += 0 if step.repeated else 1
                result.steps.append(step)
                self._emit_step(step)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                    "content": json.dumps(step.result, ensure_ascii=False, default=str),
                })

            if fresh == 0:
                # Celý krok byl jen opakování — model se točí, dál to nemá smysl.
                repeated_only += 1
                if repeated_only >= MAX_REPEATED_STEPS:
                    result.iterations = iteration
                    result.answer = self._force_answer(messages, result) or (
                        "[Model se zacyklil na opakovaném volání nástroje a nedospěl "
                        "k odpovědi.]"
                    )
                    messages.append({"role": "assistant", "content": result.answer})
                    return result
            else:
                repeated_only = 0

        result.iterations = self.max_iterations
        result.answer = self._force_answer(messages, result) or (
            f"[Vyčerpán limit {self.max_iterations} kroků, model nedospěl k odpovědi. "
            f"Provedené nástroje: {', '.join(s.tool for s in result.steps) or 'žádné'}]"
        )
        messages.append({"role": "assistant", "content": result.answer})
        return result
