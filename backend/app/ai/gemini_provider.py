import json
import time
from functools import lru_cache

import httpx
from google import genai
from google.genai import errors, types
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
from app.ai.schema_utils import inline_refs, restore_nulls, strict_json_schema
from app.config import Settings

MAX_OUTPUT_TOKENS = 16000
_BLOCKED = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}


@lru_cache(maxsize=32)
def _schema_for(model: type[BaseModel]) -> dict:
    return inline_refs(strict_json_schema(model))


def _usage(response: types.GenerateContentResponse) -> dict:
    meta = response.usage_metadata
    if meta is None:
        return {}
    fields = {
        "input_tokens": meta.prompt_token_count,
        "output_tokens": meta.candidates_token_count,
        "thinking_tokens": meta.thoughts_token_count,
        "cache_read_input_tokens": meta.cached_content_token_count,
    }
    return {name: value for name, value in fields.items() if value is not None}


def _add_usage(total: dict, usage: dict) -> None:
    for name, value in usage.items():
        total[name] = total.get(name, 0) + value


def _check_finish(response: types.GenerateContentResponse) -> None:
    feedback = response.prompt_feedback
    if feedback is not None and feedback.block_reason is not None:
        raise AIProviderError("AI_REFUSED", "The model declined to process this input.")
    if not response.candidates:
        raise AIProviderError("AI_EMPTY_RESPONSE", "The model returned no answer.", retryable=True)
    reason = response.candidates[0].finish_reason
    name = reason.name if reason is not None else "STOP"
    if name in _BLOCKED:
        raise AIProviderError("AI_REFUSED", "The model declined to process this input.")
    if name == "MAX_TOKENS":
        raise AIProviderError(
            "AI_OUTPUT_TRUNCATED", "The model ran out of output space.", retryable=True
        )


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.gemini_api_key:
            self.client = None
            return
        self.client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=int(settings.ai_timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(
                    attempts=2, http_status_codes=[500, 502, 503, 504]
                ),
            ),
        )

    def _model_for(self, task: str) -> str:
        if task == "assistant":
            return self.settings.gemini_assistant_model
        return self.settings.gemini_extraction_model

    def _thinking(self) -> types.ThinkingConfig | None:
        level = self.settings.gemini_thinking_level
        return types.ThinkingConfig(thinking_level=level.upper()) if level else None

    def _generate(
        self, model: str, contents: object, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        """Call the API; when the model is rate limited, overloaded or too slow, retry once on
        the fallback model."""
        if self.client is None:
            raise AIProviderError(
                "AI_NOT_CONFIGURED", "No Gemini API key is configured (set GEMINI_API_KEY)."
            )
        models = [model]
        fallback = self.settings.gemini_fallback_model
        if fallback and fallback != model:
            models.append(fallback)
        for index, candidate in enumerate(models):
            has_fallback = index + 1 < len(models)
            try:
                return self.client.models.generate_content(
                    model=candidate, contents=contents, config=config
                )
            except errors.ClientError as exc:
                if exc.code == 429 and has_fallback:
                    continue
                raise self._client_error(exc) from exc
            except errors.ServerError as exc:
                if has_fallback:
                    continue
                raise AIProviderError(
                    "AI_UNAVAILABLE",
                    f"Gemini is busy ({exc.code}); try again shortly.",
                    retryable=True,
                ) from exc
            except httpx.TimeoutException as exc:
                if has_fallback:
                    continue
                raise AIProviderError("AI_TIMEOUT", "Gemini timed out.", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise AIProviderError(
                    "AI_UNAVAILABLE", "Couldn't reach Gemini.", retryable=True
                ) from exc
        raise AIProviderError("AI_RATE_LIMITED", "Gemini is rate limited.", retryable=True)

    @staticmethod
    def _client_error(exc: errors.ClientError) -> AIProviderError:
        if exc.code == 429:
            return AIProviderError(
                "AI_RATE_LIMITED",
                "The Gemini free-tier limit was reached; try again shortly.",
                retryable=True,
            )
        if exc.code in (401, 403):
            return AIProviderError("AI_AUTH_FAILED", "The Gemini API key was rejected.")
        if exc.code == 404:
            return AIProviderError(
                "AI_MODEL_NOT_FOUND", "The configured Gemini model was not found."
            )
        return AIProviderError("AI_BAD_REQUEST", f"Gemini rejected the request: {exc.message}")

    def generate_structured(
        self, *, task: str, system: str, user: str, output_model: type[T]
    ) -> StructuredResult[T]:
        started = time.perf_counter()
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=_schema_for(output_model),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=self._thinking(),
        )
        response = self._generate(self._model_for(task), user, config)
        _check_finish(response)
        try:
            output = output_model.model_validate(restore_nulls(json.loads(response.text or "")))
        except (ValidationError, ValueError) as exc:
            raise AIProviderError(
                "AI_INVALID_OUTPUT", "The model's output didn't match the expected structure."
            ) from exc
        return StructuredResult(
            output=output,
            model=response.model_version or self._model_for(task),
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
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=_schema_for(tool.input_model),
                        )
                        for tool in tools
                    ]
                )
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=self._thinking(),
        )
        contents: list[types.Content] = [types.Content(role="user", parts=[types.Part(text=user)])]
        records: list[ToolCallRecord] = []
        usage: dict = {}
        model = self._model_for(task)
        started = time.perf_counter()
        for _ in range(max_steps):
            response = self._generate(model, contents, config)
            _add_usage(usage, _usage(response))
            _check_finish(response)
            calls = response.function_calls or []
            if not calls:
                return ToolLoopResult(
                    text=(response.text or "").strip(),
                    tool_calls=records,
                    model=response.model_version or model,
                    usage=usage,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
            # The model's turn goes back unchanged so its thought signatures stay valid.
            contents.append(response.candidates[0].content)
            parts = []
            for call in calls:
                arguments = restore_nulls(dict(call.args or {}))
                outcome = execute(call.name, arguments)
                records.append(
                    ToolCallRecord(call.name, arguments, outcome.content, outcome.is_error)
                )
                key = "error" if outcome.is_error else "result"
                parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=call.id, name=call.name, response={key: _as_json(outcome.content)}
                        )
                    )
                )
            contents.append(types.Content(role="user", parts=parts))
        raise AIProviderError(
            "AI_TOOL_LOOP_LIMIT", "The assistant needed too many steps to answer."
        )


def _as_json(content: str) -> object:
    try:
        return json.loads(content)
    except ValueError:
        return content
