from datetime import date, timedelta
from typing import Literal, get_args

from app.errors import ValidationFailedError

Period = Literal[
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "last_7_days",
    "last_30_days",
    "this_year",
    "all_time",
    "custom",
]
PERIODS: tuple[str, ...] = get_args(Period)
MAX_CUSTOM_DAYS = 3660


def resolve_period(
    period: str,
    today: date,
    *,
    week_start: int = 0,
    start: date | None = None,
    end: date | None = None,
) -> tuple[date, date]:
    """Return an inclusive (start, end) date range. week_start: 0 = Monday ... 6 = Sunday."""
    if period == "today":
        return today, today
    if period == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if period in ("this_week", "last_week"):
        week_begin = today - timedelta(days=(today.weekday() - week_start) % 7)
        if period == "this_week":
            return week_begin, today
        return week_begin - timedelta(days=7), week_begin - timedelta(days=1)
    if period == "this_month":
        return today.replace(day=1), today
    if period == "last_month":
        last_day = today.replace(day=1) - timedelta(days=1)
        return last_day.replace(day=1), last_day
    if period == "last_7_days":
        return today - timedelta(days=6), today
    if period == "last_30_days":
        return today - timedelta(days=29), today
    if period == "this_year":
        return today.replace(month=1, day=1), today
    if period == "all_time":
        return date(1970, 1, 1), today
    if period == "custom":
        if start is None or end is None:
            raise ValidationFailedError("A custom period needs both start_date and end_date.")
        if start > end:
            raise ValidationFailedError("start_date must be on or before end_date.")
        if (end - start).days > MAX_CUSTOM_DAYS:
            raise ValidationFailedError("A custom period can cover at most ten years.")
        return start, end
    raise ValidationFailedError(f"Unknown period '{period}'.")
