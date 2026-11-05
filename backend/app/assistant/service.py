from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.ai.prompts import load_prompt
from app.ai.provider import AIProvider
from app.assistant.tools import TOOLS, AssistantTools
from app.auth.models import User
from app.clock import Clock
from app.core.timeutil import local_now

ASSISTANT_PROMPT_VERSION = "v2"
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass
class AssistantAnswer:
    text: str
    evidence: list[dict] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    model: str | None = None


def answer_question(
    db: Session, user: User, question: str, ai: AIProvider, clock: Clock
) -> AssistantAnswer:
    now = local_now(user.timezone, clock)
    tools = AssistantTools(db, user, now.date())
    prompt = "\n".join(
        [
            "<context>",
            f"Current local time: {now:%A %Y-%m-%d %H:%M} ({user.timezone})",
            f"Weeks start on: {WEEKDAY_NAMES[user.week_start]}",
            f"Default currency: {user.default_currency or 'none set'}",
            "</context>",
            "",
            "<question>",
            question,
            "</question>",
        ]
    )
    result = ai.run_tool_loop(
        task="assistant",
        system=load_prompt("assistant", ASSISTANT_PROMPT_VERSION),
        user=prompt,
        tools=TOOLS,
        execute=tools.execute,
    )
    evidence = [
        {"tool": call.name, "input": call.input, "ok": not call.is_error}
        for call in result.tool_calls
    ]
    text = result.text or "I couldn't put together an answer from your records."
    return AssistantAnswer(
        text=text,
        evidence=evidence,
        event_ids=list(dict.fromkeys(tools.event_ids)),
        model=result.model,
    )
