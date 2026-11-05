"""Build model outputs for the fake AI without spelling out every nullable field."""

from app.ai.extraction_schema import (
    Correction,
    DayRef,
    EventChanges,
    ExtractedEvent,
    ExtractedTask,
    ExtractionOutput,
    TimeChange,
    TimeInfo,
)


def day(kind: str = "not_mentioned", **kw) -> DayRef:
    return DayRef(
        **{
            "kind": kind,
            "days_ago": None,
            "weekday": None,
            "weekday_qualifier": None,
            "date": None,
            **kw,
        }
    )


def when(day_ref: DayRef | None = None, **kw) -> TimeInfo:
    base = {
        "day": day_ref or day(),
        "start_time": None,
        "end_time": None,
        "clock_precision": None,
        "part_of_day": None,
        "duration_minutes": None,
        "duration_precision": None,
        "expression": None,
    }
    return TimeInfo(**{**base, **kw})


def event(event_type: str, title: str, evidence: str, **kw) -> ExtractedEvent:
    base = {
        "event_type": event_type,
        "title": title,
        "description": None,
        "topic": None,
        "output": None,
        "time": when(),
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
    }
    return ExtractedEvent.model_validate({**base, **kw})


def money(
    amount: str | None,
    category: str | None = None,
    currency: str | None = None,
    precision: str = "exact",
) -> dict:
    return {
        "amount": amount,
        "amount_precision": precision,
        "currency": currency,
        "category": category,
        "merchant": None,
    }


def project(text: str, ref: str | None = None, kind: str = "named") -> dict:
    return {"text": text, "ref": ref, "kind": kind}


def knowledge(
    title: str, understanding: str = "studied", ref: str | None = None, aliases=()
) -> dict:
    return {"title": title, "ref": ref, "understanding": understanding, "aliases": list(aliases)}


def time_change(**kw) -> TimeChange:
    base = {
        "day": None,
        "start_time": None,
        "end_time": None,
        "clock_precision": None,
        "part_of_day": None,
        "duration_minutes": None,
        "duration_precision": None,
    }
    return TimeChange(**{**base, **kw})


def changes(**kw) -> EventChanges:
    base = {
        "event_type": None,
        "title": None,
        "description": None,
        "topic": None,
        "output": None,
        "time": None,
        "project": None,
        "remove_project": False,
        "money": None,
    }
    return EventChanges.model_validate({**base, **kw})


def correction(action: str, evidence: str, target_ref: str | None = None, **kw) -> Correction:
    base = {
        "action": action,
        "target_ref": target_ref,
        "candidate_refs": [],
        "changes": None,
        "split_into": [],
        "evidence": evidence,
        "confidence": 0.9,
    }
    return Correction.model_validate({**base, **kw})


def task(title: str, evidence: str, due_kind: str = "none", **kw) -> ExtractedTask:
    base = {
        "title": title,
        "due": {"kind": due_kind, "days_from_now": None, "weekday": None, "date": None},
        "project": None,
        "goal_ref": None,
        "evidence": evidence,
        "confidence": 0.9,
    }
    return ExtractedTask.model_validate({**base, **kw})


def output(
    events=(), corrections=(), tasks=(), intent: str = "record", question: str | None = None
) -> ExtractionOutput:
    return ExtractionOutput(
        language="en",
        intent=intent,
        events=list(events),
        corrections=list(corrections),
        tasks=list(tasks),
        question=question,
    )
