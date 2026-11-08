"""Provider-neutral AI interface (specs #4 §45, #5 §42, #8 §13).

The rest of the application asks for "structured output matching this schema" or "answer
using these tools" and never imports a vendor SDK directly.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class AIProviderError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class StructuredResult(Generic[T]):
    output: T
    model: str
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0


@dataclass
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False


@dataclass
class ToolCallRecord:
    name: str
    input: dict
    output: str
    is_error: bool


@dataclass
class ToolLoopResult:
    text: str
    tool_calls: list[ToolCallRecord]
    model: str
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0


ToolExecutor = Callable[[str, dict], ToolOutcome]


class AIProvider(ABC):
    name: str

    @abstractmethod
    def generate_structured(
        self, *, task: str, system: str, user: str, output_model: type[T]
    ) -> StructuredResult[T]:
        """Return output that validates against output_model, or raise AIProviderError."""

    @abstractmethod
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
        """Let the model call tools until it answers, or raise AIProviderError."""


@lru_cache
def _provider(name: str) -> AIProvider:
    if name == "demo":
        from app.ai.demo_provider import DemoAIProvider

        return DemoAIProvider()
    if name == "anthropic":
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(get_settings())
    from app.ai.gemini_provider import GeminiProvider

    return GeminiProvider(get_settings())


def get_ai_provider() -> AIProvider | None:
    """FastAPI dependency. None means AI processing is switched off."""
    settings = get_settings()
    name = settings.ai_provider.lower()
    if name in ("gemini", "anthropic"):
        return _provider(name)
    # The rule-based demo AI exists for automated tests; a public server never uses it.
    if name == "demo" and not settings.is_production:
        return _provider(name)
    return None
