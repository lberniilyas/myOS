"""A scripted AI provider for tests and offline development. It never calls a network."""

import re
from collections.abc import Callable

from pydantic import BaseModel

from app.ai.provider import (
    AIProvider,
    AIProviderError,
    StructuredResult,
    T,
    ToolCallRecord,
    ToolExecutor,
    ToolLoopResult,
    ToolSpec,
)

_MESSAGE = re.compile(r"<message>\n(.*)\n</message>", re.DOTALL)


def message_of(user_prompt: str) -> str:
    match = _MESSAGE.search(user_prompt)
    return match.group(1) if match else user_prompt


class FakeAIProvider(AIProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self._rules: list[tuple[str, object]] = []
        self.calls: list[dict] = []
        self.error: AIProviderError | None = None
        self.tool_plan: list[tuple[str, dict]] = []
        self.answer: Callable[[list[ToolCallRecord]], str] = lambda records: "Done."

    def respond(self, contains: str, output: object) -> None:
        """When the user's message contains `contains`, return `output` (a model, dict or callable)."""
        self._rules.append((contains, output))

    def generate_structured(
        self, *, task: str, system: str, user: str, output_model: type[T]
    ) -> StructuredResult[T]:
        self.calls.append({"task": task, "system": system, "user": user})
        if self.error is not None:
            raise self.error
        message = message_of(user)
        for contains, output in reversed(self._rules):
            if contains in message:
                value = output(user) if callable(output) else output
                parsed = (
                    value if isinstance(value, BaseModel) else output_model.model_validate(value)
                )
                return StructuredResult(
                    output=parsed,
                    model=self.model,
                    usage={"input_tokens": len(user) // 4, "output_tokens": 50},
                    latency_ms=1,
                )
        raise AIProviderError("FAKE_NO_RULE", f"No scripted response for: {message[:80]!r}")

    def run_tool_loop(
        self,
        *,
        task: str,
        system: str,
        user: str,
        tools: list[ToolSpec],
        execute: ToolExecutor,
        max_steps: int = 8,
    ) -> ToolLoopResult:
        self.calls.append({"task": task, "system": system, "user": user})
        if self.error is not None:
            raise self.error
        records = []
        for name, arguments in self.tool_plan[:max_steps]:
            outcome = execute(name, arguments)
            records.append(ToolCallRecord(name, arguments, outcome.content, outcome.is_error))
        return ToolLoopResult(text=self.answer(records), tool_calls=records, model=self.model)
