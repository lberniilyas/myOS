"""Score real extraction against the golden dataset (spec #10 §7).

Each case runs the full capture pipeline with the configured AI provider for a fresh user in
the test database, then checks the records it created. Nothing is kept: every case is rolled back.

    python -m evals.run_extraction                  # all cases
    python -m evals.run_extraction --case french    # one case
    python -m evals.run_extraction --delay 7        # seconds between calls (free-tier rate limits)
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ai.provider import get_ai_provider
from app.auth import service as auth_service
from app.auth.schemas import RegisterRequest
from app.captures.models import Clarification
from app.captures.pipeline import submit_capture
from app.captures.schemas import CaptureCreate
from app.clock import FixedClock
from app.config import get_settings
from app.db import all_models  # noqa: F401
from app.events.models import Event
from app.habits.models import Habit
from app.projects import service as project_service
from app.projects.schemas import ProjectCreate

DATASET = Path(__file__).parent / "extraction_v1.jsonl"
REPORTS = Path(__file__).parent / "reports"
NOW = datetime(2026, 10, 4, 19, 30, tzinfo=UTC)
TODAY = NOW.date()


def seed(db: Session, clock: FixedClock):
    user, _ = auth_service.register(
        db,
        RegisterRequest(
            email="eval@example.com",
            password="evaluation-password",
            timezone="UTC",
            default_currency="MAD",
        ),
        clock,
    )
    project_service.create_project(
        db, user, ProjectCreate(name="TenderPilot", aliases=["tender app"])
    )
    project_service.create_project(db, user, ProjectCreate(name="BLANI", aliases=["travel app"]))
    db.add(Habit(user_id=user.id, name="Exercise", name_key="exercise", target_count=3))
    db.commit()
    return user


def describe(event: Event) -> dict:
    return {
        "event_type": event.event_type.value,
        "duration_minutes": event.duration_seconds / 60
        if event.duration_seconds is not None
        else None,
        "duration_precision": event.duration_precision.value,
        "time_precision": event.time_precision.value,
        "occurred_on": event.occurred_on.isoformat(),
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "local_time": event.occurred_at.strftime("%H:%M") if event.occurred_at else None,
        "project": event.project_links[0].project.name if event.project_links else None,
        "amount": str(event.amount) if event.amount is not None else None,
        "amount_precision": event.amount_precision.value if event.amount_precision else None,
        "currency": event.currency,
        "category": event.category,
        "knowledge": [link.knowledge.title.lower() for link in event.knowledge_links],
        "understanding": [
            link.knowledge.understanding_state.value for link in event.knowledge_links
        ],
        "habit": event.habit_links[0].habit.name if event.habit_links else None,
        "habit_outcome": event.habit_links[0].outcome.value if event.habit_links else None,
        "has_output": bool((event.structured_data or {}).get("output")),
        "title": event.title,
    }


def field_ok(name: str, expected, actual: dict) -> bool:
    if name == "occurred_on" and expected == "yesterday":
        return actual["occurred_on"] == (TODAY - timedelta(days=1)).isoformat()
    if name == "knowledge":
        return any(expected in title for title in actual["knowledge"])
    if name == "understanding":
        return expected in actual["understanding"]
    if name == "duration_minutes" and expected is not None and actual[name] is not None:
        return abs(actual[name] - expected) <= 1
    if name == "amount" and expected is not None and actual[name] is not None:
        return Decimal(actual[name]) == Decimal(expected)
    return actual.get(name) == expected


def score_case(
    case: dict, events: list[dict], clarifications: list[str], tasks: int, intent: str | None
) -> dict:
    expect = case["expect"]
    remaining = list(events)
    checks, failures = 0, []
    for wanted in expect.get("events", []):
        match = next(
            (
                e
                for e in remaining
                if all(
                    field_ok(k, v, e)
                    for k, v in wanted.items()
                    if k in ("event_type", "project", "habit")
                )
            ),
            None,
        )
        if match is None:
            failures.append(f"missing {wanted}")
            checks += len(wanted)
            continue
        remaining.remove(match)
        for name, value in wanted.items():
            checks += 1
            if not field_ok(name, value, match):
                failures.append(
                    f"{match['event_type']}.{name}: expected {value!r}, got {match.get(name)!r}"
                )
    extra = [] if expect.get("allow_extra") else remaining
    for event in extra:
        failures.append(f"unexpected event {event['event_type']} '{event['title']}'")
    for forbidden in expect.get("forbid_types", []):
        if any(e["event_type"] == forbidden for e in events):
            failures.append(f"forbidden type {forbidden}")
    for kind in expect.get("clarifications", []):
        checks += 1
        if kind not in clarifications:
            failures.append(f"missing question {kind}")
    if "tasks" in expect:
        checks += 1
        if tasks != len(expect["tasks"]):
            failures.append(f"expected {len(expect['tasks'])} task(s), got {tasks}")
    if "intent" in expect:
        checks += 1
        if intent != expect["intent"]:
            failures.append(f"intent {intent!r}")
    return {
        "id": case["id"],
        "category": case["category"],
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "extra_events": len(extra),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    parser.add_argument("--delay", type=float, default=7.0)
    args = parser.parse_args()

    settings = get_settings()
    ai = get_ai_provider()
    if ai is None:
        print("AI is switched off (AI_PROVIDER=none).")
        return 2
    cases = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]

    engine = create_engine(settings.test_database_url)
    clock = FixedClock(NOW)
    results = []
    for index, case in enumerate(cases):
        if index:
            time.sleep(args.delay)
        connection = engine.connect()
        transaction = connection.begin()
        db = Session(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            user = seed(db, clock)
            outcome = submit_capture(db, user, CaptureCreate(content=case["input"]), ai, clock)
            if outcome.error:
                result = {
                    "id": case["id"],
                    "category": case["category"],
                    "passed": False,
                    "checks": 1,
                    "failures": [f"error {outcome.error.code}: {outcome.error.message}"],
                    "extra_events": 0,
                }
            else:
                events = [
                    describe(e)
                    for e in db.scalars(
                        select(Event).where(Event.user_id == user.id, Event.deleted_at.is_(None))
                    )
                ]
                kinds = [
                    c.kind.value
                    for c in db.scalars(
                        select(Clarification).where(Clarification.user_id == user.id)
                    )
                ]
                result = score_case(
                    case, events, kinds, len(outcome.tasks_created), outcome.capture.intent
                )
                result["reply"] = outcome.message
        finally:
            db.close()
            transaction.rollback()
            connection.close()
        results.append(result)
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark}  {case['id']:<28} {'; '.join(result['failures'])[:150]}")

    passed = sum(r["passed"] for r in results)
    false_extractions = sum(r["extra_events"] for r in results)
    print(
        f"\n{passed}/{len(results)} cases passed · {false_extractions} unexpected events · model: "
        f"{settings.gemini_extraction_model if settings.ai_provider == 'gemini' else settings.ai_extraction_model}"
    )
    REPORTS.mkdir(exist_ok=True)
    report = REPORTS / f"extraction_{datetime.now():%Y%m%d_%H%M%S}.json"
    report.write_text(
        json.dumps({"provider": settings.ai_provider, "results": results}, indent=2),
        encoding="utf-8",
    )
    print(f"Report: {report}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
