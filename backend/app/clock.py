from datetime import UTC, datetime


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock(Clock):
    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


_clock = Clock()


def get_clock() -> Clock:
    return _clock
