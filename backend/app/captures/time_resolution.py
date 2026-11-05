"""Resolve the model's time references into dates and times in the user's timezone.

Date arithmetic is done here, not by the model (spec #10 §12). Uncertainty is preserved:
an unstated start time stays unknown, an approximate duration stays approximate.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from app.ai.extraction_schema import DayRef, DueRef, TimeChange, TimeInfo
from app.core.enums import DayPeriod, DurationPrecision, TimePrecision

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_DURATION_MINUTES = 24 * 60
FUTURE_TOLERANCE = timedelta(minutes=10)


@dataclass
class ResolvedTime:
    occurred_on: date
    occurred_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    time_precision: TimePrecision
    duration_precision: DurationPrecision
    day_period: DayPeriod | None
    date_unclear: bool = False
    in_future: bool = False
    warnings: list[str] = field(default_factory=list)


def resolve_day(day: DayRef, today: date, default: date) -> date | None:
    """A past or present calendar day, or None when the reference can't be placed."""
    kind = day.kind
    if kind == "today":
        return today
    if kind == "yesterday":
        return today - timedelta(days=1)
    if kind == "not_mentioned":
        return default
    if kind == "days_ago":
        if day.days_ago is None or not 0 <= day.days_ago <= 3650:
            return None
        return today - timedelta(days=day.days_ago)
    if kind == "weekday":
        if day.weekday not in WEEKDAYS:
            return None
        delta = (today.weekday() - WEEKDAYS.index(day.weekday)) % 7
        if day.weekday_qualifier == "last" and delta == 0:
            delta = 7
        return today - timedelta(days=delta)
    if kind == "date":
        try:
            return date.fromisoformat(day.date or "")
        except ValueError:
            return None
    return None


def resolve_due(due: DueRef, today: date) -> date | None:
    """A present or future calendar day for a task, or None."""
    if due.kind == "today":
        return today
    if due.kind == "tomorrow":
        return today + timedelta(days=1)
    if (
        due.kind == "days_from_now"
        and due.days_from_now is not None
        and 0 <= due.days_from_now <= 3650
    ):
        return today + timedelta(days=due.days_from_now)
    if due.kind == "weekday" and due.weekday in WEEKDAYS:
        delta = (WEEKDAYS.index(due.weekday) - today.weekday()) % 7 or 7
        return today + timedelta(days=delta)
    if due.kind == "date":
        try:
            return date.fromisoformat(due.date or "")
        except ValueError:
            return None
    return None


def parse_clock(value: str | None) -> time | None:
    if not value:
        return None
    match = _CLOCK.match(value.strip())
    return time(int(match.group(1)), int(match.group(2))) if match else None


def resolve_time(
    info: TimeInfo, now_local: datetime, *, default_day: date | None = None
) -> ResolvedTime:
    zone = now_local.tzinfo
    today = now_local.date()
    warnings: list[str] = []

    day = resolve_day(info.day, today, default_day or today)
    date_unclear = day is None
    if day is None:
        day = default_day or today

    start_clock, end_clock = parse_clock(info.start_time), parse_clock(info.end_time)
    if info.start_time and start_clock is None:
        warnings.append(f"Ignored an unreadable start time '{info.start_time}'.")
    if info.end_time and end_clock is None:
        warnings.append(f"Ignored an unreadable end time '{info.end_time}'.")

    duration_seconds: int | None = None
    duration_precision = DurationPrecision.UNKNOWN
    if info.duration_minutes is not None:
        if 0 < info.duration_minutes <= MAX_DURATION_MINUTES:
            duration_seconds = round(info.duration_minutes * 60)
            duration_precision = (
                DurationPrecision.APPROXIMATE
                if info.duration_precision == "approximate"
                else DurationPrecision.EXACT
            )
        else:
            warnings.append(f"Ignored an impossible duration of {info.duration_minutes} minutes.")

    clock_precision = (
        TimePrecision.APPROXIMATE if info.clock_precision == "approximate" else TimePrecision.EXACT
    )
    clock_duration_precision = (
        DurationPrecision.APPROXIMATE
        if clock_precision == TimePrecision.APPROXIMATE
        else DurationPrecision.EXACT
    )
    start = datetime.combine(day, start_clock, tzinfo=zone) if start_clock else None
    end = datetime.combine(day, end_clock, tzinfo=zone) if end_clock else None
    if start and end:
        if end <= start:
            end += timedelta(days=1)  # "from 11pm to 1am"
        span = int((end - start).total_seconds())
        if duration_seconds is not None and abs(duration_seconds - span) > max(600, 0.2 * span):
            warnings.append(
                "The stated duration didn't match the start and end times; used the times."
            )
        duration_seconds = span
        duration_precision = clock_duration_precision
    elif start and duration_seconds is not None:
        end = start + timedelta(seconds=duration_seconds)
    elif end and duration_seconds is not None:
        start = end - timedelta(seconds=duration_seconds)

    in_future = False
    if start is not None and start > now_local + FUTURE_TOLERANCE:
        in_future = True
    elif start is None and day > today:
        in_future = True
    if end is not None and end > now_local + FUTURE_TOLERANCE and not in_future:
        warnings.append("The end time is still in the future; kept the start only.")
        end = None
        if start_clock and end_clock:
            duration_seconds, duration_precision = None, DurationPrecision.UNKNOWN

    if start is not None:
        time_precision = clock_precision
        occurred_on = start.date()
    else:
        time_precision = TimePrecision.UNKNOWN if date_unclear else TimePrecision.DATE_ONLY
        occurred_on = day

    period = DayPeriod(info.part_of_day.upper()) if info.part_of_day and start is None else None
    return ResolvedTime(
        occurred_on=occurred_on,
        occurred_at=start,
        ended_at=end,
        duration_seconds=duration_seconds,
        time_precision=time_precision,
        duration_precision=duration_precision,
        day_period=period,
        date_unclear=date_unclear,
        in_future=in_future,
        warnings=warnings,
    )


def time_info_from_event(event, zone) -> TimeInfo:
    """Describe an existing event's time in the model's vocabulary so a change can be layered on."""
    start = event.occurred_at.astimezone(zone) if event.occurred_at else None
    end = event.ended_at.astimezone(zone) if event.ended_at else None
    approximate_clock = event.time_precision == TimePrecision.APPROXIMATE
    return TimeInfo(
        day=DayRef(
            kind="date",
            days_ago=None,
            weekday=None,
            weekday_qualifier=None,
            date=event.occurred_on.isoformat(),
        ),
        start_time=start.strftime("%H:%M") if start else None,
        end_time=end.strftime("%H:%M") if end else None,
        clock_precision=("approximate" if approximate_clock else "exact") if start else None,
        part_of_day=event.day_period.value.lower() if event.day_period else None,
        duration_minutes=event.duration_seconds / 60
        if event.duration_seconds is not None
        else None,
        duration_precision=(
            "approximate" if event.duration_precision == DurationPrecision.APPROXIMATE else "exact"
        )
        if event.duration_seconds is not None
        else None,
        expression=None,
    )


def apply_time_change(base: TimeInfo, change: TimeChange) -> TimeInfo:
    """Overlay the parts the user changed. A new length or start invalidates the old end."""
    data = base.model_dump()
    if change.day is not None:
        data["day"] = change.day.model_dump()
    for name in ("start_time", "end_time", "clock_precision", "part_of_day"):
        if getattr(change, name) is not None:
            data[name] = getattr(change, name)
    if change.duration_minutes is not None:
        data["duration_minutes"] = change.duration_minutes
        data["duration_precision"] = change.duration_precision or "exact"
        if change.end_time is None:
            data["end_time"] = None
    if (
        change.start_time is not None
        and change.end_time is None
        and base.duration_minutes is not None
    ):
        data["end_time"] = None
    return TimeInfo.model_validate(data)
