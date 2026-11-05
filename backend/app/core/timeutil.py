from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from app.clock import Clock

UTC_ZONE = ZoneInfo("UTC")


def is_valid_timezone(name: str) -> bool:
    return name in available_timezones()


def zone_for(timezone_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return UTC_ZONE


def local_now(timezone_name: str | None, clock: Clock) -> datetime:
    return clock.now().astimezone(zone_for(timezone_name))


def local_today(timezone_name: str | None, clock: Clock) -> date:
    return local_now(timezone_name, clock).date()


def local_date_of(moment: datetime, timezone_name: str | None) -> date:
    return moment.astimezone(zone_for(timezone_name)).date()
