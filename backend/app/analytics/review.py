"""The weekly review: a week against the week before and the four weeks before it.

Every number comes from SQL over recorded events, and the observations are fixed rules with
thresholds, so the same records always give the same review. No language model is involved.

A week still in progress is compared fairly: with three days gone, each earlier week counts
its first three days too ("last week by Wednesday"). Averages only count weeks since the
person started recording, so a new account isn't compared with weeks it never had.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.service import habit_outcomes, money_totals, time_totals
from app.core.enums import EventType, HabitFrequency, HabitStatus
from app.core.formatting import format_amount, format_duration
from app.errors import ValidationFailedError
from app.events.models import Event
from app.habits.models import Habit

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
EARLIER_WEEKS = 4
# Always shown: what the system is mostly for. Other timed types appear once they have data.
CORE_TIME = (EventType.STUDY, EventType.PROJECT_WORK)
OTHER_TIME = (EventType.WORK, EventType.EXERCISE, EventType.SLEEP)
TIME_LABELS = {
    EventType.STUDY: "Study",
    EventType.PROJECT_WORK: "Project work",
    EventType.WORK: "Work",
    EventType.EXERCISE: "Exercise",
    EventType.SLEEP: "Sleep",
}
HOUR = 3600
# Observation thresholds: a change has to be both large and real to be worth a sentence.
MIN_TIME_CHANGE = HOUR
MIN_TIME_SHARE = 0.30
MIN_MONEY_SHARE = 0.25
MIN_PROJECT_TIME = HOUR
MIN_CATEGORY_SHARE = 0.5
MAX_OBSERVATIONS = 3

Kind = Literal["time", "money", "count"]


class Measure(BaseModel):
    value: float
    display: str | None


class Metric(BaseModel):
    key: str
    label: str
    kind: Kind
    currency: str | None = None
    this_week: Measure
    last_week: Measure
    average: Measure | None  # None until there's an earlier week to average
    change: str | None  # against last week, e.g. "+1h 30m"; None when there's nothing to compare
    direction: Literal["up", "down", "same"]
    note: str | None = None


class HabitProgress(BaseModel):
    habit_id: uuid.UUID
    name: str
    frequency: str
    completed: int
    target: int | None
    display: str


class Observation(BaseModel):
    text: str
    metric: str | None = None


class WeekInfo(BaseModel):
    start: date
    end: date
    is_current: bool
    days_counted: int
    # Set while the week is in progress: earlier weeks are counted up to this weekday.
    compared_through: str | None


class WeeklyReview(BaseModel):
    week: WeekInfo
    previous_week: date
    next_week: date | None
    weeks_in_average: int
    metrics: list[Metric]
    habits: list[HabitProgress]
    observations: list[Observation]


@dataclass(frozen=True)
class Window:
    start: date
    end: date


def week_start_of(day: date, week_start: int) -> date:
    """week_start: 0 = Monday ... 6 = Sunday."""
    return day - timedelta(days=(day.weekday() - week_start) % 7)


def _signed(delta: float, fmt) -> str:
    sign = "+" if delta > 0 else "−"
    return f"{sign}{fmt(abs(delta))}"


def _hours(seconds: float) -> str:
    return format_duration(round(seconds)) or "0m"


def _direction(delta: float) -> Literal["up", "down", "same"]:
    return "up" if delta > 0 else "down" if delta < 0 else "same"


def _percent(delta: float, base: float) -> int:
    return round(abs(delta) / base * 100)


class _Review:
    def __init__(self, db: Session, user_id: uuid.UUID, week_start: date, today: date) -> None:
        self.db = db
        self.user_id = user_id
        self.start = week_start
        self.is_current = week_start <= today <= week_start + timedelta(days=6)
        self.days = (today - week_start).days + 1 if self.is_current else 7
        self.windows = [
            Window(
                week_start - timedelta(weeks=k),
                week_start - timedelta(weeks=k) + timedelta(days=self.days - 1),
            )
            for k in range(EARLIER_WEEKS + 1)
        ]
        first = db.scalar(
            select(func.min(Event.occurred_on)).where(
                Event.user_id == user_id, Event.deleted_at.is_(None)
            )
        )
        # Earlier weeks that overlap the time the person has been recording. They're always
        # the most recent ones, so averages use windows[1 : 1 + history].
        self.history = 0 if first is None else sum(1 for w in self.windows[1:] if w.end >= first)
        self.this = self.windows[0]
        # Named for the weeks it really covers: "your 2-week average" for a new account.
        self.average_name = f"your {self.history}-week average"
        self.by = (
            f" by {WEEKDAYS[self.this.end.weekday()]}" if self.is_current and self.days < 7 else ""
        )

    # --- measurements --------------------------------------------------------------------

    def time_by_type(self, window: Window) -> dict[str, dict]:
        rows = time_totals(
            self.db,
            self.user_id,
            start=window.start,
            end=window.end,
            event_types=[*CORE_TIME, *OTHER_TIME],
            group_by="event_type",
        )
        return {row["key"]: row for row in rows}

    def spending(self, window: Window) -> dict[str, dict]:
        rows = money_totals(self.db, self.user_id, start=window.start, end=window.end)
        return {row["currency"]: row for row in rows if row["currency"]}

    def check_ins(self, window: Window) -> int:
        rows = habit_outcomes(self.db, self.user_id, start=window.start, end=window.end)
        return sum(row["completed"] for row in rows)

    def average(self, values: list[float]) -> float | None:
        earlier = values[1 : 1 + self.history]
        return sum(earlier) / len(earlier) if earlier else None


def _metric(
    key: str,
    label: str,
    kind: Kind,
    values: list[float],
    average: float | None,
    fmt,
    *,
    currency: str | None = None,
    note: str | None = None,
    show_zero: bool = False,
) -> Metric:
    def measure(value: float) -> Measure:
        return Measure(value=value, display=fmt(value) if value or show_zero else None)

    this, last = values[0], values[1]
    delta = this - last
    return Metric(
        key=key,
        label=label,
        kind=kind,
        currency=currency,
        this_week=measure(this),
        last_week=measure(last),
        average=measure(average) if average is not None else None,
        change=_signed(delta, fmt) if delta else None,
        direction=_direction(delta),
        note=note,
    )


def weekly_review(
    db: Session, user_id: uuid.UUID, week_start_day: int, today: date, week_of: date | None
) -> WeeklyReview:
    start = week_start_of(week_of or today, week_start_day)
    if start > today:
        raise ValidationFailedError("That week hasn't started yet.")
    review = _Review(db, user_id, start, today)
    metrics: list[Metric] = []
    observations: list[tuple[float, int, Observation]] = []

    def observe(score: float, text: str, metric: str | None = None) -> None:
        observations.append((score, len(observations), Observation(text=text, metric=metric)))

    # Time --------------------------------------------------------------------------------
    times = [review.time_by_type(w) for w in review.windows]
    for event_type in (*CORE_TIME, *OTHER_TIME):
        key = event_type.value
        values = [float(t.get(key, {}).get("seconds", 0)) for t in times]
        if event_type in OTHER_TIME and not any(values):
            continue
        missing = times[0].get(key, {}).get("events_without_duration", 0)
        note = (
            f"{missing} entr{'y has' if missing == 1 else 'ies have'} no duration, "
            "so the total may be higher."
            if missing
            else None
        )
        average = review.average(values)
        label = TIME_LABELS[event_type]
        metrics.append(
            _metric(key, label, "time", values, average, _hours, note=note, show_zero=True)
        )
        if event_type != EventType.SLEEP:
            _time_observations(observe, review, key, label, values, average)

    # Spending ----------------------------------------------------------------------------
    spending = [review.spending(w) for w in review.windows]
    currencies = sorted({c for s in spending for c in s})
    for currency in currencies:
        values = [float(Decimal(s.get(currency, {}).get("amount", "0"))) for s in spending]

        def money(value: float, currency: str = currency) -> str:
            return format_amount(Decimal(str(round(value, 2))), currency) or ""

        average = review.average(values)
        key = f"SPENDING:{currency}"
        metrics.append(
            _metric(
                key, "Spending", "money", values, average, money, currency=currency, show_zero=True
            )
        )
        _money_observations(observe, review, key, values, average, money)
        _category_observation(observe, review, key, currency, values[0], money)

    # Habits ------------------------------------------------------------------------------
    habits = _habit_progress(db, user_id, review)
    check_ins = [float(review.check_ins(w)) for w in review.windows]
    if habits or any(check_ins):
        metrics.append(
            _metric(
                "HABITS",
                "Habit check-ins",
                "count",
                check_ins,
                review.average(check_ins),
                lambda v: f"{v:g}" if v == int(v) else f"{v:.1f}",
                show_zero=True,
            )
        )
    for item in habits:
        _habit_observation(observe, review, item)

    _project_observation(observe, db, user_id, review)

    observations.sort(key=lambda o: (-o[0], o[1]))
    return WeeklyReview(
        week=WeekInfo(
            start=start,
            end=start + timedelta(days=6),
            is_current=review.is_current,
            days_counted=review.days,
            compared_through=WEEKDAYS[review.this.end.weekday()] if review.by else None,
        ),
        previous_week=start - timedelta(weeks=1),
        next_week=None if review.is_current else start + timedelta(weeks=1),
        weeks_in_average=review.history,
        metrics=metrics,
        habits=habits,
        observations=[o for _, _, o in observations[:MAX_OBSERVATIONS]],
    )


# --- observations --------------------------------------------------------------------------


def _time_observations(observe, review: _Review, key, label, values, average) -> None:
    this, last = values[0], values[1]
    if review.history >= 2 and average is not None:
        delta = this - average
        if average >= MIN_TIME_CHANGE and this == 0:
            observe(
                1.0,
                f"No {label.lower()} recorded{' yet' if review.by else ''} this week; "
                f"{review.average_name}{review.by} is {_hours(average)}.",
                key,
            )
        elif average == 0 and this >= MIN_TIME_CHANGE:
            observe(
                1.0,
                f"{label}: {_hours(this)} this week, after none in the "
                f"{review.history} weeks before.",
                key,
            )
        elif (
            average > 0 and abs(delta) >= MIN_TIME_CHANGE and abs(delta) / average >= MIN_TIME_SHARE
        ):
            observe(
                abs(delta) / average,
                f"{label} is {'up' if delta > 0 else 'down'} {_percent(delta, average)}% on "
                f"{review.average_name}{review.by}: {_hours(this)} against {_hours(average)}.",
                key,
            )
    elif review.history == 1:
        delta = this - last
        if last > 0 and abs(delta) >= MIN_TIME_CHANGE and abs(delta) / last >= MIN_TIME_SHARE:
            observe(
                abs(delta) / last,
                f"{label} is {'up' if delta > 0 else 'down'} {_percent(delta, last)}% on last "
                f"week{review.by}: {_hours(this)} against {_hours(last)}.",
                key,
            )


def _money_observations(observe, review: _Review, key, values, average, money) -> None:
    this = values[0]
    base, against = (
        (average, review.average_name)
        if review.history >= 2
        else (values[1], "last week")
        if review.history == 1
        else (None, "")
    )
    if not base or this == 0:
        return
    delta = this - base
    if abs(delta) / base >= MIN_MONEY_SHARE:
        observe(
            abs(delta) / base,
            f"Spending is {'up' if delta > 0 else 'down'} {_percent(delta, base)}% on "
            f"{against}{review.by}: {money(this)} against {money(base)}.",
            key,
        )


def _category_observation(observe, review: _Review, key, currency, total, money) -> None:
    if total <= 0:
        return
    rows = money_totals(
        review.db,
        review.user_id,
        start=review.this.start,
        end=review.this.end,
        group_by="category",
    )
    rows = [r for r in rows if r["currency"] == currency and r.get("category")]
    if len(rows) < 2:
        return
    top = max(rows, key=lambda r: Decimal(r["amount"]))
    amount = float(Decimal(top["amount"]))
    share = amount / total
    if share >= MIN_CATEGORY_SHARE:
        observe(
            0.2,
            f"{top['category'].capitalize()} was {round(share * 100)}% of your spending "
            f"this week: {money(amount)} of {money(total)}.",
            key,
        )


def _project_observation(observe, db: Session, user_id: uuid.UUID, review: _Review) -> None:
    rows = time_totals(
        db, user_id, start=review.this.start, end=review.this.end, group_by="project"
    )
    rows = [r for r in rows if r["seconds"] > 0]
    total = sum(r["seconds"] for r in rows)
    if len(rows) < 2 or total < MIN_PROJECT_TIME:
        return
    top = rows[0]
    observe(
        0.2,
        f"{top['label']} got {round(top['seconds'] / total * 100)}% of your project time "
        f"this week: {_hours(top['seconds'])} of {_hours(total)}.",
        "PROJECT_WORK",
    )


def _habit_progress(db: Session, user_id: uuid.UUID, review: _Review) -> list[HabitProgress]:
    done = {
        row["habit_id"]: row
        for row in habit_outcomes(db, user_id, start=review.this.start, end=review.this.end)
    }
    habits = db.scalars(
        select(Habit)
        .where(
            Habit.user_id == user_id,
            Habit.status == HabitStatus.ACTIVE,
            Habit.frequency.in_([HabitFrequency.DAILY, HabitFrequency.WEEKLY]),
        )
        .order_by(Habit.name)
    )
    result = []
    for habit in habits:
        row = done.get(str(habit.id), {})
        if habit.frequency == HabitFrequency.DAILY:
            completed = row.get("completed_days", 0)
            target = review.days
            display = f"{completed} of {target} day{'s' if target != 1 else ''}"
        else:
            completed = row.get("completed", 0)
            target = habit.target_count
            display = f"{completed} of {target}" if target else f"{completed}×"
        result.append(
            HabitProgress(
                habit_id=habit.id,
                name=habit.name,
                frequency=habit.frequency.value,
                completed=completed,
                target=target,
                display=display,
            )
        )
    return result


def _habit_observation(observe, review: _Review, item: HabitProgress) -> None:
    if item.frequency != HabitFrequency.WEEKLY or not item.target:
        return
    days_left = 7 - review.days
    if item.completed >= item.target:
        observe(0.5, f"{item.name}: weekly target reached, {item.completed} of {item.target}.")
    elif not review.is_current:
        observe(0.5, f"{item.name}: {item.completed} of {item.target}, short of the target.")
    elif item.target - item.completed > days_left:
        observe(
            0.6,
            f"{item.name}: {item.completed} of {item.target}, with {days_left} "
            f"day{'' if days_left == 1 else 's'} left this week.",
        )
