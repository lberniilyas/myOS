"""A deterministic AI for end-to-end tests and offline demos (AI_PROVIDER=demo).

It understands a small, fixed set of English phrasings with regular expressions, so automated
browser tests get the same answer every run, instantly and without a network. Never used in
production: get_ai_provider refuses it there.

Test controls, written anywhere in a message: "[slow 3]" waits 3 seconds, "[fail]" always
answers "rate limited", "[fail once]" fails the first time a message is seen and works after.
"""

import json
import re
import threading
import time

from app.ai.extraction_schema import ExtractionOutput
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
from app.core.formatting import format_duration

_UNIT = r"(?P<n>\d+(?:\.\d+)?)\s?(?P<unit>hours?|hrs?|h|minutes?|mins?|m)\b"
_STUDY = re.compile(rf"\bstud(?:ied|y)\s+(?P<topic>[\w .+-]+?)\s+for\s+{_UNIT}", re.I)
_WORK = re.compile(rf"\bworked\s+on\s+(?P<project>[\w .-]+?)\s+for\s+{_UNIT}", re.I)
_SPENT = re.compile(
    r"\b(?:spent|paid)\s+(?P<amount>\d+(?:[.,]\d{1,2})?)\s?(?P<currency>dh|dirhams?|mad|eur|euros?|usd)?"
    r"\s+(?:on|for)\s+(?P<what>[\w ]+)",
    re.I,
)
_TASK = re.compile(r"\bi need to\s+(?P<task>[\w ]+?)(?P<tomorrow>\s+tomorrow)?\s*$", re.I)
_EXERCISE = re.compile(r"\b(?:went|ran|did)\b[\w ]*\b(?:run|running|gym|workout)\b", re.I)
_MISSED = re.compile(r"\bdidn'?t\s+(?:exercise|go to the gym|work out)\b", re.I)
_QUESTION = re.compile(r"^\s*(?:how|what|which|did|when|where)\b.*\?\s*$", re.I | re.S)
_SLOW = re.compile(r"\[slow (\d+)\]", re.I)
_CURRENCIES = {"dh": "MAD", "dirham": "MAD", "dirhams": "MAD", "mad": "MAD", "eur": "EUR"}
_CURRENCIES |= {"euro": "EUR", "euros": "EUR", "usd": "USD"}
_CATEGORIES = {
    "food": ("lunch", "dinner", "breakfast", "food", "coffee", "restaurant", "meal"),
    "transport": ("taxi", "bus", "uber", "train", "fuel", "petrol"),
    "groceries": ("groceries", "supermarket"),
    "utilities": ("internet", "electricity", "water", "phone bill"),
}


def _minutes(match: re.Match) -> float:
    value = float(match["n"])
    return value * 60 if match["unit"].lower().startswith("h") else value


def _day() -> dict:
    return {
        "kind": "not_mentioned",
        "days_ago": None,
        "weekday": None,
        "weekday_qualifier": None,
        "date": None,
    }


def _time(minutes: float | None = None) -> dict:
    return {
        "day": _day(),
        "start_time": None,
        "end_time": None,
        "clock_precision": None,
        "part_of_day": None,
        "duration_minutes": minutes,
        "duration_precision": "exact" if minutes else None,
        "expression": None,
    }


def _event(event_type: str, title: str, evidence: str, **fields) -> dict:
    return {
        "event_type": event_type,
        "title": title,
        "description": None,
        "topic": None,
        "output": None,
        "time": _time(),
        "project": None,
        "knowledge": [],
        "habit": None,
        "completes_task_ref": None,
        "goal_ref": None,
        "area_ref": None,
        "money": None,
        "device": None,
        "state": None,
        "relation": {"kind": "new", "ref": None},
        "is_user_estimate": False,
        "evidence": evidence,
        "confidence": 0.95,
        **fields,
    }


def understand(message: str) -> dict:
    """The extraction output for a message, as plain data."""
    if _QUESTION.match(message):
        return {
            "language": "en",
            "intent": "question",
            "events": [],
            "corrections": [],
            "tasks": [],
            "question": message.strip(),
        }
    events, tasks = [], []
    for match in _STUDY.finditer(message):
        topic = match["topic"].strip()
        events.append(
            _event("STUDY", f"{topic} study", match[0], topic=topic, time=_time(_minutes(match)))
        )
    for match in _WORK.finditer(message):
        name = match["project"].strip()
        project = {"text": name, "ref": None, "kind": "named"}
        events.append(
            _event(
                "PROJECT_WORK",
                f"{name} work",
                match[0],
                project=project,
                time=_time(_minutes(match)),
            )
        )
    for match in _SPENT.finditer(message):
        what = match["what"].strip()
        category = next(
            (c for c, words in _CATEGORIES.items() if any(w in what.lower() for w in words)), None
        )
        currency = _CURRENCIES.get((match["currency"] or "").lower())
        money = {
            "amount": match["amount"].replace(",", "."),
            "amount_precision": "exact",
            "currency": currency,
            "category": category,
            "merchant": None,
        }
        events.append(_event("EXPENSE", what.capitalize(), match[0], money=money))
    for match in _EXERCISE.finditer(message):
        habit = {"ref": None, "name": "exercise", "status": "completed"}
        events.append(_event("EXERCISE", "Workout", match[0], habit=habit))
    for match in _MISSED.finditer(message):
        habit = {"ref": None, "name": "exercise", "status": "missed"}
        events.append(_event("HABIT", "Missed exercise", match[0], habit=habit))
    for match in _TASK.finditer(message):
        due = {
            "kind": "tomorrow" if match["tomorrow"] else "none",
            "days_from_now": None,
            "weekday": None,
            "date": None,
        }
        tasks.append(
            {
                "title": match["task"].strip().capitalize(),
                "due": due,
                "project": None,
                "goal_ref": None,
                "evidence": match[0].strip(),
                "confidence": 0.9,
            }
        )
    text = re.sub(r"\[[^\]]*\]", "", message).strip()
    if not events and not tasks and len(text.split()) >= 2:
        events.append(_event("OTHER", " ".join(text.split()[:5]), text))
    intent = "record" if events or tasks else "other"
    return {
        "language": "en",
        "intent": intent,
        "events": events,
        "corrections": [],
        "tasks": tasks,
        "question": None,
    }


class DemoAIProvider(AIProvider):
    name = "demo"
    model = "demo-rules-v1"

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def _controls(self, message: str) -> None:
        if slow := _SLOW.search(message):
            time.sleep(min(int(slow[1]), 20))
        if "[fail]" in message.lower():
            raise AIProviderError("AI_RATE_LIMITED", "Demo AI asked to fail.", retryable=True)
        if "[fail once]" in message.lower():
            with self._lock:
                first = message not in self._seen
                self._seen.add(message)
            if first:
                raise AIProviderError("AI_RATE_LIMITED", "Demo AI fails this once.", retryable=True)

    def generate_structured(
        self, *, task: str, system: str, user: str, output_model: type[T]
    ) -> StructuredResult[T]:
        if output_model is not ExtractionOutput:
            raise AIProviderError(
                "AI_BAD_REQUEST", f"The demo AI only does extraction, not {task}."
            )
        message = user.rsplit("<message>\n", 1)[-1].rsplit("\n</message>", 1)[0]
        self._controls(message)
        output = output_model.model_validate(understand(message))
        return StructuredResult(output=output, model=self.model, usage={}, latency_ms=0)

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
        question = user.rsplit("<question>\n", 1)[-1].lower()
        week = {"period": "this_week", "start_date": None, "end_date": None}
        if "spen" in question:
            name, args = (
                "get_spending",
                {**week, "kind": "expense", "category": None, "group_by": "none"},
            )
        elif "stud" in question:
            name, args = (
                "get_activity_totals",
                {**week, "event_types": ["STUDY"], "project": None, "group_by": "none"},
            )
        else:
            name, args = (
                "list_events",
                {**week, "event_types": None, "project": None, "text": None, "limit": 5},
            )
        outcome = execute(name, args)
        record = ToolCallRecord(name, args, outcome.content, outcome.is_error)
        return ToolLoopResult(
            text=_answer(name, outcome.content), tool_calls=[record], model=self.model
        )


def _answer(tool: str, content: str) -> str:
    data = json.loads(content)
    if "error" in data:
        return "I couldn't look that up."
    if tool == "get_spending":
        rows = [r for r in data["rows"] if r["display"]]
        if not rows:
            return "You haven't recorded any spending this week."
        return "This week you spent " + " and ".join(r["display"] for r in rows) + "."
    if tool == "get_activity_totals":
        seconds = data["rows"][0]["seconds"]
        return (
            f"You studied {format_duration(seconds)} this week."
            if seconds
            else "You haven't recorded any study this week."
        )
    titles = [e["title"] for e in data["events"]]
    return (
        ("Recently: " + ", ".join(titles) + ".")
        if titles
        else "I don't have any entries for this week yet."
    )
