import time
from functools import lru_cache

import anthropic
from pydantic import BaseModel, ValidationError

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
from app.ai.schema_utils import strict_json_schema
from app.config import Settings

# On a safety-classifier decline the API reruns the request on a suitable model server-side.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000


@lru_cache(maxsize=32)
def _schema_for(model: type[BaseModel]) -> dict:
    return strict_json_schema(model)


def _usage(response: object) -> dict:
    usage = getattr(response, "usage", None)
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    return {name: value for name in fields if (value := getattr(usage, name, None)) is not None}


def _add_usage(total: dict, usage: dict) -> None:
    for name, value in usage.items():
        total[name] = total.get(name, 0) + value


def _check_stop_reason(response: object) -> None:
    if response.stop_reason == "refusal":
        raise AIProviderError("AI_REFUSED", "The model declined to process this input.")
    if response.stop_reason == "max_tokens":
        raise AIProviderError(
            "AI_OUTPUT_TRUNCATED", "The model ran out of output space.", retryable=True
        )


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        client_kwargs: dict = {"timeout": settings.ai_timeout_seconds, "max_retries": 2}
        if settings.anthropic_api_key:
            client_kwargs["api_key"] = settings.anthropic_api_key
        # Without an explicit key the SDK resolves credentials from the environment or profile.
        self.client = anthropic.Anthropic(**client_kwargs)

    def _model_and_effort(self, task: str) -> tuple[str, str]:
        if task == "assistant":
            return self.settings.ai_assistant_model, self.settings.ai_assistant_effort
        return self.settings.ai_extraction_model, self.settings.ai_extraction_effort

    def _create(self, **request: object) -> object:
        if self.settings.ai_server_fallback:
            request.update(betas=[FALLBACK_BETA], fallbacks="default")
        try:
            return self.client.beta.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise AIProviderError("AI_AUTH_FAILED", "The Anthropic API key was rejected.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AIProviderError("AI_AUTH_FAILED", "The API key can't use this model.") from exc
        except anthropic.NotFoundError as exc:
            raise AIProviderError(
                "AI_MODEL_NOT_FOUND", "The configured model was not found."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise AIProviderError(
                "AI_RATE_LIMITED", "The AI service is rate limited.", retryable=True
            ) from exc
        except anthropic.BadRequestError as exc:
            raise AIProviderError(
                "AI_BAD_REQUEST", f"The AI request was rejected: {exc.message}"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise AIProviderError(
                "AI_UNAVAILABLE", f"The AI service failed ({exc.status_code}).", retryable=True
            ) from exc
        except anthropic.APITimeoutError as exc:
            raise AIProviderError(
                "AI_TIMEOUT", "The AI service timed out.", retryable=True
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise AIProviderError(
                "AI_UNAVAILABLE", "Couldn't reach the AI service.", retryable=True
            ) from exc
        except anthropic.CredentialsError as exc:
            raise AIProviderError(
                "AI_NOT_CONFIGURED",
                "No Anthropic credentials are configured (set ANTHROPIC_API_KEY).",
            ) from exc
        except anthropic.AnthropicError as exc:
            raise AIProviderError("AI_ERROR", str(exc) or "The AI request failed.") from exc

    def generate_structured(
        self, *, task: str, system: str, user: str, output_model: type[T]
    ) -> StructuredResult[T]:
        model, effort = self._model_and_effort(task)
        started = time.perf_counter()
        response = self._create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": _schema_for(output_model)},
            },
        )
        _check_stop_reason(response)
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            output = output_model.model_validate_json(text)
        except ValidationError as exc:
            raise AIProviderError(
                "AI_INVALID_OUTPUT", "The model's output didn't match the expected structure."
            ) from exc
        return StructuredResult(
            output=output,
            model=response.model,
            usage=_usage(response),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

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
        model, effort = self._model_and_effort(task)
        tool_definitions = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": _schema_for(tool.input_model),
                "strict": True,
            }
            for tool in tools
        ]
        messages: list[dict] = [{"role": "user", "content": user}]
        records: list[ToolCallRecord] = []
        usage: dict = {}
        started = time.perf_counter()
        for _ in range(max_steps):
            response = self._create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tool_definitions,
                messages=messages,
                output_config={"effort": effort},
            )
            _add_usage(usage, _usage(response))
            _check_stop_reason(response)
            tool_uses = [block for block in response.content if block.type == "tool_use"]
            if not tool_uses:
                text = "".join(block.text for block in response.content if block.type == "text")
                return ToolLoopResult(
                    text=text.strip(),
                    tool_calls=records,
                    model=response.model,
                    usage=usage,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
            # Thinking and tool_use blocks go back unchanged, as the API requires.
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in tool_uses:
                arguments = dict(block.input)
                outcome = execute(block.name, arguments)
                records.append(
                    ToolCallRecord(block.name, arguments, outcome.content, outcome.is_error)
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": outcome.content,
                        "is_error": outcome.is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
        raise AIProviderError(
            "AI_TOOL_LOOP_LIMIT", "The assistant needed too many steps to answer."
        )
