import json

import pytest
from google.genai import errors, types

from app.ai.extraction_schema import ExtractionOutput
from app.ai.gemini_provider import GeminiProvider
from app.ai.provider import AIProviderError, ToolOutcome, ToolSpec
from app.assistant.tools import NoArgs
from app.config import Settings
from tests import factories as f


def response(
    *parts: dict, finish: str = "STOP", block: str | None = None
) -> types.GenerateContentResponse:
    body = {
        "candidates": [
            {"content": {"role": "model", "parts": list(parts)}, "finish_reason": finish}
        ],
        "usage_metadata": {"prompt_token_count": 100, "candidates_token_count": 20},
        "model_version": "main-model",
    }
    if block:
        body = {"prompt_feedback": {"block_reason": block}}
    return types.GenerateContentResponse.model_validate(body)


class StubModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def provider(replies, **settings) -> tuple[GeminiProvider, StubModels]:
    config = {
        "gemini_api_key": "test-key",
        "gemini_extraction_model": "main-model",
        "gemini_assistant_model": "main-model",
        "gemini_fallback_model": "fallback-model",
        **settings,
    }
    gemini = GeminiProvider(Settings(**config))
    stub = StubModels(replies)
    gemini.client = type("Client", (), {"models": stub})()
    return gemini, stub


def test_structured_output_is_validated_and_schema_is_inlined():
    expected = f.output(events=[f.event("STUDY", "AI study", "studied AI")])
    gemini, stub = provider([response({"text": expected.model_dump_json()})])
    result = gemini.generate_structured(
        task="extraction", system="sys", user="msg", output_model=ExtractionOutput
    )
    assert result.output == expected
    assert result.usage == {"input_tokens": 100, "output_tokens": 20}
    config = stub.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert "$ref" not in json.dumps(config.response_json_schema)
    assert stub.calls[0]["model"] == "main-model"


def test_rate_limit_falls_back_to_the_lighter_model_once():
    limited = errors.ClientError(
        429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )
    gemini, stub = provider([limited, response({"text": f.output().model_dump_json()})])
    gemini.generate_structured(
        task="extraction", system="s", user="u", output_model=ExtractionOutput
    )
    assert [c["model"] for c in stub.calls] == ["main-model", "fallback-model"]

    gemini, _ = provider([limited, limited])
    with pytest.raises(AIProviderError) as exc:
        gemini.generate_structured(
            task="extraction", system="s", user="u", output_model=ExtractionOutput
        )
    assert exc.value.code == "AI_RATE_LIMITED" and exc.value.retryable


def test_busy_model_falls_back_once():
    busy = errors.ServerError(
        503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}
    )
    gemini, stub = provider([busy, response({"text": f.output().model_dump_json()})])
    gemini.generate_structured(
        task="extraction", system="s", user="u", output_model=ExtractionOutput
    )
    assert [c["model"] for c in stub.calls] == ["main-model", "fallback-model"]


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (response({"text": "not json"}), "AI_INVALID_OUTPUT"),
        (response({"text": "{}"}, finish="SAFETY"), "AI_REFUSED"),
        (response(block="SAFETY"), "AI_REFUSED"),
        (response({"text": "{"}, finish="MAX_TOKENS"), "AI_OUTPUT_TRUNCATED"),
        (
            errors.ClientError(
                403, {"error": {"code": 403, "message": "bad key", "status": "PERMISSION_DENIED"}}
            ),
            "AI_AUTH_FAILED",
        ),
        (
            errors.ServerError(
                503, {"error": {"code": 503, "message": "down", "status": "UNAVAILABLE"}}
            ),
            "AI_UNAVAILABLE",
        ),
    ],
)
def test_failures_map_to_stable_codes(reply, code):
    gemini, _ = provider([reply], gemini_fallback_model=None)
    with pytest.raises(AIProviderError) as exc:
        gemini.generate_structured(
            task="extraction", system="s", user="u", output_model=ExtractionOutput
        )
    assert exc.value.code == code


def test_missing_key_is_reported_clearly():
    gemini = GeminiProvider(Settings(gemini_api_key=None))
    with pytest.raises(AIProviderError) as exc:
        gemini.generate_structured(
            task="extraction", system="s", user="u", output_model=ExtractionOutput
        )
    assert exc.value.code == "AI_NOT_CONFIGURED"


def test_tool_loop_runs_tools_and_returns_the_answer():
    call = {
        "function_call": {"id": "c1", "name": "list_projects", "args": {}},
        "thought_signature": "c2ln",
    }
    gemini, stub = provider([response(call), response({"text": "You have 2 projects."})])
    executed = []

    def execute(name, arguments):
        executed.append((name, arguments))
        return ToolOutcome(json.dumps({"projects": ["A", "B"]}))

    result = gemini.run_tool_loop(
        task="assistant",
        system="s",
        user="q",
        tools=[ToolSpec("list_projects", "List", NoArgs)],
        execute=execute,
    )
    assert result.text == "You have 2 projects."
    assert executed == [("list_projects", {})]
    second_turn = stub.calls[1]["contents"]
    # The model's own turn (with its thought signature) is sent back unchanged.
    assert second_turn[1].parts[0].thought_signature is not None
    function_response = second_turn[2].parts[0].function_response
    assert function_response.id == "c1" and function_response.response == {
        "result": {"projects": ["A", "B"]}
    }
    assert stub.calls[0]["config"].automatic_function_calling.disable is True


def test_tool_loop_has_a_step_limit():
    call = {"function_call": {"id": "c", "name": "list_projects", "args": {}}}
    gemini, _ = provider([response(call)] * 3)
    with pytest.raises(AIProviderError) as exc:
        gemini.run_tool_loop(
            task="assistant",
            system="s",
            user="q",
            tools=[ToolSpec("list_projects", "List", NoArgs)],
            execute=lambda n, a: ToolOutcome("{}"),
            max_steps=3,
        )
    assert exc.value.code == "AI_TOOL_LOOP_LIMIT"


def test_word_null_from_gemini_becomes_a_real_null():
    expected = f.output(tasks=[f.task("Read", "read later")])
    raw = json.loads(expected.model_dump_json())
    raw["question"] = "null"
    raw["tasks"][0]["due"]["date"] = "null"
    gemini, _ = provider([response({"text": json.dumps(raw)})])
    result = gemini.generate_structured(
        task="extraction", system="s", user="u", output_model=ExtractionOutput
    )
    assert result.output.question is None
    # Lowercase "none" is a legitimate enum value and must survive.
    assert result.output.tasks[0].due.kind == "none" and result.output.tasks[0].due.date is None

    call = {"function_call": {"id": "c1", "name": "list_projects", "args": {"x": "null"}}}
    gemini, _ = provider([response(call), response({"text": "done"})])
    seen = []
    gemini.run_tool_loop(
        task="assistant",
        system="s",
        user="q",
        tools=[ToolSpec("list_projects", "List", NoArgs)],
        execute=lambda name, arguments: seen.append(arguments) or ToolOutcome("{}"),
    )
    assert seen == [{"x": None}]
