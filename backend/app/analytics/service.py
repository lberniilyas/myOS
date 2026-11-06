"""Deterministic measurements over events. Numbers come from SQL, never from a language model."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import case, distinct, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.core.enums import (
    AmountPrecision,
    DurationPrecision,
    EventType,
    HabitOutcome,
    TaskStatus,
)
from app.core.formatting import format_amount, format_duration
from app.core.timeutil import zone_for
from app.events.models import Event, EventHabit, EventKnowledge, EventProject
from app.habits.models import Habit
from app.knowledge.models import Knowledge
from app.projects.models import Project
from app.tasks.models import Task

TYPE_LABELS = {
    EventType.STUDY: "Study",
    EventType.WORK: "Work",
    EventType.PROJECT_WORK: "Project work",
    EventType.TASK_ACTIVITY: "Tasks",
    EventType.EXERCISE: "Exercise",
    EventType.DEVICE_USAGE: "Device use",
    EventType.SLEEP: "Sleep",
}


def _live_events(user_id: uuid.UUID, start: date | None, end: date | None) -> list:
    conditions = [Event.user_id == user_id, Event.deleted_at.is_(None)]
    if start is not None:
        conditions.append(Event.occurred_on >= start)
    if end is not None:
        conditions.append(Event.occurred_on <= end)
    return conditions


def time_totals(
    db: Session,
    user_id: uuid.UUID,
    *,
    start: date | None,
    end: date | None,
    event_types: list[EventType] | None = None,
    project_id: uuid.UUID | None = None,
    group_by: str | None = None,
) -> list[dict]:
    """Sum recorded durations. Rows report how many durations were approximate or missing."""
    seconds = func.coalesce(func.sum(Event.duration_seconds), 0)
    approximate = func.count(case((Event.duration_precision == DurationPrecision.APPROXIMATE, 1)))
    missing = func.count(case((Event.duration_seconds.is_(None), 1)))
    conditions = _live_events(user_id, start, end)
    if event_types:
        conditions.append(Event.event_type.in_(event_types))
    if project_id is not None:
        # A separate alias, so the filter doesn't correlate with the join used by group_by="project".
        project_filter = aliased(EventProject)
        conditions.append(
            exists().where(
                project_filter.event_id == Event.id, project_filter.project_id == project_id
            )
        )

    if group_by == "project":
        stmt = (
            select(Project.id, Project.name, seconds, func.count(Event.id), approximate, missing)
            .join(EventProject, EventProject.event_id == Event.id)
            .join(Project, Project.id == EventProject.project_id)
            .where(*conditions)
            .group_by(Project.id, Project.name)
            .order_by(seconds.desc())
        )
        rows = db.execute(stmt).all()
        return [
            _time_row(str(pid), name, secs, count, approx, miss)
            for pid, name, secs, count, approx, miss in rows
        ]
    if group_by in ("event_type", "day"):
        key = Event.event_type if group_by == "event_type" else Event.occurred_on
        stmt = (
            select(key, seconds, func.count(Event.id), approximate, missing)
            .where(*conditions)
            .group_by(key)
            .order_by(key)
        )
        rows = db.execute(stmt).all()
        result = []
        for value, secs, count, approx, miss in rows:
            if group_by == "event_type":
                result.append(
                    _time_row(
                        value.value,
                        TYPE_LABELS.get(value, value.value.title()),
                        secs,
                        count,
                        approx,
                        miss,
                    )
                )
            else:
                result.append(
                    _time_row(value.isoformat(), value.isoformat(), secs, count, approx, miss)
                )
        return result
    stmt = select(seconds, func.count(Event.id), approximate, missing).where(*conditions)
    secs, count, approx, miss = db.execute(stmt).one()
    return [_time_row("total", "Total", secs, count, approx, miss)]


def _time_row(
    key: str, label: str, seconds: int, events: int, approximate: int, missing: int
) -> dict:
    precision = DurationPrecision.APPROXIMATE if approximate else DurationPrecision.EXACT
    return {
        "key": key,
        "label": label,
        "seconds": int(seconds),
        # With no recorded length, "0m" would read as a measurement; show nothing instead.
        "display": format_duration(int(seconds), precision) if seconds else None,
        "events": events,
        "approximate_events": approximate,
        "events_without_duration": missing,
    }


def money_totals(
    db: Session,
    user_id: uuid.UUID,
    *,
    start: date | None,
    end: date | None,
    event_type: EventType = EventType.EXPENSE,
    category: str | None = None,
    group_by: str | None = None,
) -> list[dict]:
    """Sum amounts per currency. Different currencies are never added together."""
    amount = func.coalesce(func.sum(Event.amount), 0)
    approximate = func.count(case((Event.amount_precision == AmountPrecision.APPROXIMATE, 1)))
    missing = func.count(case((Event.amount.is_(None), 1)))
    conditions = _live_events(user_id, start, end) + [Event.event_type == event_type]
    if category:
        conditions.append(Event.category == category)
    keys = [Event.currency]
    if group_by == "category":
        keys.append(Event.category)
    elif group_by == "day":
        keys.append(Event.occurred_on)
    stmt = (
        select(*keys, amount, func.count(Event.id), approximate, missing)
        .where(*conditions)
        .group_by(*keys)
        .order_by(*keys)
    )
    result = []
    for row in db.execute(stmt).all():
        currency = row[0]
        group_value = row[1] if len(keys) > 1 else None
        total, count, approx, miss = row[-4:]
        total = Decimal(total)
        precision = AmountPrecision.APPROXIMATE if approx else AmountPrecision.EXACT
        entry = {
            "currency": currency,
            "amount": str(total.quantize(Decimal("0.01"))),
            # With no recorded amount, "0" would read as a measurement; show nothing instead.
            "display": format_amount(total, currency, precision) if count > miss else None,
            "events": count,
            "approximate_events": approx,
            "events_without_amount": miss,
        }
        if group_by == "category":
            entry["category"] = group_value
        elif group_by == "day":
            entry["day"] = group_value.isoformat()
        result.append(entry)
    return result


def habit_outcomes(
    db: Session,
    user_id: uuid.UUID,
    *,
    start: date | None,
    end: date | None,
    habit_id: uuid.UUID | None = None,
) -> list[dict]:
    completed = func.count(case((EventHabit.outcome == HabitOutcome.COMPLETED, 1)))
    missed = func.count(case((EventHabit.outcome == HabitOutcome.MISSED, 1)))
    completed_days = func.count(
        distinct(case((EventHabit.outcome == HabitOutcome.COMPLETED, Event.occurred_on)))
    )
    conditions = _live_events(user_id, start, end)
    if habit_id is not None:
        conditions.append(Habit.id == habit_id)
    stmt = (
        select(
            Habit.id,
            Habit.name,
            Habit.frequency,
            Habit.target_count,
            completed,
            missed,
            completed_days,
        )
        .join(EventHabit, EventHabit.habit_id == Habit.id)
        .join(Event, Event.id == EventHabit.event_id)
        .where(*conditions)
        .group_by(Habit.id, Habit.name, Habit.frequency, Habit.target_count)
        .order_by(Habit.name)
    )
    return [
        {
            "habit_id": str(hid),
            "name": name,
            "frequency": frequency.value,
            "target_count": target,
            "completed": done,
            "missed": miss,
            "completed_days": days,
        }
        for hid, name, frequency, target, done, miss, days in db.execute(stmt).all()
    ]


def daily_summary(db: Session, user_id: uuid.UUID, timezone_name: str, day: date) -> dict:
    """What the Home screen shows: only sections that have real data for that day."""
    timed_types = list(TYPE_LABELS)
    time_rows = [
        row
        for row in time_totals(
            db, user_id, start=day, end=day, event_types=timed_types, group_by="event_type"
        )
        if row["seconds"] > 0 or row["events"] > 0
    ]
    project_rows = time_totals(db, user_id, start=day, end=day, group_by="project")
    devices = _device_time(db, user_id, day)

    knowledge_rows = db.execute(
        select(Knowledge.id, Knowledge.title, Knowledge.understanding_state)
        .join(EventKnowledge, EventKnowledge.knowledge_id == Knowledge.id)
        .join(Event, Event.id == EventKnowledge.event_id)
        .where(*_live_events(user_id, day, day), Knowledge.deleted_at.is_(None))
        .distinct()
    ).all()

    zone = zone_for(timezone_name)
    completed_tasks = [
        task
        for task in db.scalars(
            select(Task).where(
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
                Task.status == TaskStatus.COMPLETED,
                Task.completed_at.is_not(None),
            )
        )
        if task.completed_at.astimezone(zone).date() == day
    ]

    habit_rows = db.execute(
        select(Habit.id, Habit.name, EventHabit.outcome)
        .join(EventHabit, EventHabit.habit_id == Habit.id)
        .join(Event, Event.id == EventHabit.event_id)
        .where(*_live_events(user_id, day, day))
        .order_by(Habit.name)
    ).all()
    habits: dict[str, dict] = {}
    for hid, name, outcome in habit_rows:
        entry = habits.setdefault(
            str(hid), {"habit_id": str(hid), "name": name, "status": outcome.value}
        )
        if outcome == HabitOutcome.COMPLETED:
            entry["status"] = HabitOutcome.COMPLETED.value

    states = [
        {"title": event.title, **(event.structured_data or {}).get("state", {})}
        for event in db.scalars(
            select(Event).where(
                *_live_events(user_id, day, day), Event.event_type == EventType.STATE
            )
        )
    ]
    events_count = db.scalar(select(func.count(Event.id)).where(*_live_events(user_id, day, day)))

    return {
        "date": day.isoformat(),
        "events_count": events_count or 0,
        "time": time_rows,
        "projects": project_rows,
        "devices": devices,
        "spending": money_totals(db, user_id, start=day, end=day, event_type=EventType.EXPENSE),
        "income": money_totals(db, user_id, start=day, end=day, event_type=EventType.INCOME),
        "knowledge": [
            {"id": str(kid), "title": title, "understanding_state": state.value}
            for kid, title, state in knowledge_rows
        ],
        "tasks_completed": [{"id": str(task.id), "title": task.title} for task in completed_tasks],
        "habits": list(habits.values()),
        "states": states,
    }


def _device_time(db: Session, user_id: uuid.UUID, day: date) -> list[dict]:
    device = Event.structured_data["device"]["device"].astext
    stmt = (
        select(
            device,
            func.coalesce(func.sum(Event.duration_seconds), 0),
            func.count(case((Event.duration_precision == DurationPrecision.APPROXIMATE, 1))),
        )
        .where(*_live_events(user_id, day, day), Event.event_type == EventType.DEVICE_USAGE)
        .group_by(device)
    )
    result = []
    for name, seconds, approx in db.execute(stmt).all():
        precision = DurationPrecision.APPROXIMATE if approx else DurationPrecision.EXACT
        result.append(
            {
                "device": name or "unknown",
                "seconds": int(seconds),
                "display": format_duration(int(seconds), precision) if seconds else None,
            }
        )
    return result
