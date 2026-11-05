import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import habit_outcomes
from app.areas.models import Area
from app.auth.deps import get_current_user
from app.auth.models import User
from app.clock import Clock, get_clock
from app.core.enums import HabitFrequency, HabitStatus
from app.core.periods import resolve_period
from app.core.text import compact_key
from app.core.timeutil import local_today
from app.db.queries import get_owned
from app.db.session import get_db
from app.errors import ConflictError, ValidationFailedError
from app.events.models import Event, EventHabit
from app.habits.models import Habit
from app.habits.schemas import (
    HabitCreate,
    HabitDetail,
    HabitOccurrence,
    HabitOut,
    HabitPeriod,
    HabitUpdate,
)

router = APIRouter(prefix="/v1/habits", tags=["habits"])

_PERIOD_FOR = {
    HabitFrequency.DAILY: "today",
    HabitFrequency.WEEKLY: "this_week",
    HabitFrequency.MONTHLY: "this_month",
}


def _unique_key(db: Session, user: User, name: str, habit_id: uuid.UUID | None = None) -> str:
    key = compact_key(name)
    if not key:
        raise ValidationFailedError("The habit name needs at least one letter or digit.")
    clash = db.scalar(
        select(Habit).where(
            Habit.user_id == user.id, Habit.name_key == key, Habit.archived_at.is_(None)
        )
    )
    if clash is not None and clash.id != habit_id:
        raise ConflictError(f"You already have a habit called '{clash.name}'.", code="HABIT_EXISTS")
    return key


def _to_out(habit: Habit) -> HabitOut:
    return HabitOut(
        id=habit.id,
        name=habit.name,
        description=habit.description,
        frequency=habit.frequency,
        target_count=habit.target_count,
        status=habit.status,
        area_id=habit.area_id,
        created_at=habit.created_at,
    )


@router.get("", response_model=list[HabitOut])
def list_habits(
    include_archived: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[HabitOut]:
    stmt = select(Habit).where(Habit.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(Habit.archived_at.is_(None))
    return [_to_out(h) for h in db.scalars(stmt.order_by(Habit.name))]


@router.post("", response_model=HabitOut, status_code=201)
def create_habit(
    payload: HabitCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> HabitOut:
    name = payload.name.strip()
    if payload.area_id:
        get_owned(db, Area, payload.area_id, user.id, label="Area")
    habit = Habit(
        user_id=user.id,
        name=name,
        name_key=_unique_key(db, user, name),
        description=payload.description,
        frequency=payload.frequency,
        target_count=payload.target_count,
        area_id=payload.area_id,
    )
    db.add(habit)
    db.commit()
    return _to_out(habit)


@router.get("/{habit_id}", response_model=HabitDetail)
def read_habit(
    habit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> HabitDetail:
    habit = get_owned(db, Habit, habit_id, user.id, label="Habit")
    start, end = resolve_period(
        _PERIOD_FOR[habit.frequency], local_today(user.timezone, clock), week_start=user.week_start
    )
    rows = habit_outcomes(db, user.id, start=start, end=end, habit_id=habit.id)
    completed = rows[0]["completed_days"] if rows else 0
    missed = rows[0]["missed"] if rows else 0
    recent = db.execute(
        select(Event.id, Event.occurred_on, Event.title, EventHabit.outcome)
        .join(EventHabit, EventHabit.event_id == Event.id)
        .where(EventHabit.habit_id == habit.id, Event.deleted_at.is_(None))
        .order_by(Event.occurred_on.desc(), Event.sort_at.desc())
        .limit(20)
    ).all()
    return HabitDetail(
        **_to_out(habit).model_dump(),
        current_period=HabitPeriod(
            start=start,
            end=end,
            completed=completed,
            missed=missed,
            target_count=habit.target_count,
        ),
        recent=[
            HabitOccurrence(event_id=eid, occurred_on=day, title=title, outcome=outcome)
            for eid, day, title, outcome in recent
        ],
    )


@router.patch("/{habit_id}", response_model=HabitOut)
def update_habit(
    habit_id: uuid.UUID,
    payload: HabitUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> HabitOut:
    habit = get_owned(db, Habit, habit_id, user.id, label="Habit")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name"):
        habit.name = changes["name"].strip()
        habit.name_key = _unique_key(db, user, habit.name, habit.id)
    for field in ("description", "frequency", "target_count", "area_id"):
        if field in changes and not (field == "frequency" and changes[field] is None):
            setattr(habit, field, changes[field])
    if changes.get("status"):
        habit.status = changes["status"]
        habit.archived_at = clock.now() if habit.status == HabitStatus.ARCHIVED else None
    db.commit()
    return _to_out(habit)


@router.delete("/{habit_id}", status_code=204)
def archive_habit(
    habit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    """Archive rather than delete: past events keep their habit links."""
    habit = get_owned(db, Habit, habit_id, user.id, label="Habit")
    habit.status = HabitStatus.ARCHIVED
    habit.archived_at = clock.now()
    db.commit()
    return Response(status_code=204)
