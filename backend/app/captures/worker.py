"""Understanding captures after the reply, and recovering any that didn't finish.

Saving answers at once and the AI runs afterwards (spec #5 §31: confirm the capture before any
analysis). A sweep picks up what a restart, a sleeping server or a busy AI left behind:
captures never started, runs cut off midway, and failures worth retrying, with growing pauses
between attempts. Every run first claims its capture atomically, so no capture is ever
understood twice, whichever way it gets picked up.

The sweep runs at startup, then sleeps until the next piece of work is due, waking early when
a capture fails (signals.changed). With nothing pending it looks only every few hours, so a
server kept awake doesn't keep a hosted database (Neon) awake and spending its compute.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from datetime import timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider
from app.auth.models import User
from app.captures import signals
from app.captures.models import Capture
from app.captures.pipeline import STALE_PROCESSING, claim_for_retry, process_capture
from app.captures.retries import RETRY_DELAYS, retrying
from app.clock import Clock
from app.core.enums import CaptureStatus

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

# A capture saved but not started after this was dropped by a restart or the server sleeping.
NOT_STARTED_AFTER = timedelta(minutes=1)
SWEEP_BATCH = 20
# With nothing pending, look anyway this often: a safety net that keeps the database awake
# for a few minutes, not the whole day.
IDLE_CHECK_SECONDS = 3 * 3600


def run_capture(
    sessions: SessionFactory,
    capture_id: uuid.UUID,
    ai: AIProvider | None,
    clock: Clock,
    *,
    claimed: bool = False,
) -> None:
    """Understand one saved capture. claimed: the caller already took it with claim_for_retry."""
    try:
        with sessions() as db:
            capture = db.get(Capture, capture_id)
            if capture is None or not (claimed or claim_for_retry(db, capture)):
                return
            user = db.get(User, capture.user_id)
            process_capture(db, user, capture, ai, clock)
    except Exception:  # noqa: BLE001 - logged; the sweep finds the capture again later
        logger.exception("Understanding capture %s in the background failed", capture_id)


def due_for_work(db: Session, retry_unit_seconds: float) -> list[uuid.UUID]:
    """Captures to (re)run now, oldest first."""
    now = func.now()
    retry_due = or_(
        *(
            and_(
                Capture.attempts == attempt,
                Capture.updated_at < now - timedelta(seconds=delay * retry_unit_seconds),
            )
            for attempt, delay in enumerate(RETRY_DELAYS, start=1)
        )
    )
    return list(
        db.scalars(
            select(Capture.id)
            .where(
                or_(
                    and_(
                        Capture.processing_status == CaptureStatus.CAPTURED,
                        Capture.updated_at < now - NOT_STARTED_AFTER,
                    ),
                    and_(
                        Capture.processing_status == CaptureStatus.PROCESSING,
                        Capture.updated_at < now - STALE_PROCESSING,
                    ),
                    and_(retrying(), retry_due),
                )
            )
            .order_by(Capture.received_at)
            .limit(SWEEP_BATCH)
        )
    )


def seconds_until_next(db: Session, retry_unit_seconds: float) -> float | None:
    """When the next capture becomes due (0 if one already is), or None with nothing pending."""
    retry_at = [
        (
            and_(retrying(), Capture.attempts == attempt),
            Capture.updated_at + timedelta(seconds=delay * retry_unit_seconds),
        )
        for attempt, delay in enumerate(RETRY_DELAYS, start=1)
    ]
    due_at = case(
        (
            Capture.processing_status == CaptureStatus.CAPTURED,
            Capture.updated_at + NOT_STARTED_AFTER,
        ),
        (
            Capture.processing_status == CaptureStatus.PROCESSING,
            Capture.updated_at + STALE_PROCESSING,
        ),
        *retry_at,
    )
    seconds = db.scalar(
        select(func.extract("epoch", func.min(due_at) - func.now())).where(
            or_(
                Capture.processing_status.in_([CaptureStatus.CAPTURED, CaptureStatus.PROCESSING]),
                retrying(),
            )
        )
    )
    return None if seconds is None else max(0.0, float(seconds))


def sweep(
    sessions: SessionFactory, ai: AIProvider | None, clock: Clock, retry_unit_seconds: float
) -> tuple[int, float | None]:
    """Run everything that is due. Returns how many captures were picked up, and the seconds
    until the next one is due (None when nothing is pending)."""
    with sessions() as db:
        ids = due_for_work(db, retry_unit_seconds)
    for capture_id in ids:
        run_capture(sessions, capture_id, ai, clock)
    with sessions() as db:
        return len(ids), seconds_until_next(db, retry_unit_seconds)


async def run_forever(
    sessions: SessionFactory,
    get_ai: Callable[[], AIProvider | None],
    clock: Clock,
    *,
    interval_seconds: float,
    retry_unit_seconds: float,
    idle_seconds: float = IDLE_CHECK_SECONDS,
) -> None:
    """The sweep loop the server runs while it's up. It starts right away, which recovers
    whatever a restart or a sleeping server interrupted, then sleeps until the next capture is
    due (at least interval_seconds, at most idle_seconds) or until a capture fails."""
    loop = asyncio.get_running_loop()
    wake = asyncio.Event()
    signals.listen(lambda: loop.call_soon_threadsafe(wake.set))
    try:
        while True:
            # Cleared before sweeping, so a failure during the sweep still wakes the next one.
            wake.clear()
            wait = interval_seconds
            try:
                picked, next_due = await asyncio.to_thread(
                    sweep, sessions, get_ai(), clock, retry_unit_seconds
                )
                if picked:
                    logger.info("Background sweep picked up %s capture(s)", picked)
                wait = idle_seconds if next_due is None else min(idle_seconds, next_due)
            except Exception:  # noqa: BLE001 - one bad sweep mustn't stop the loop
                logger.exception("Background sweep failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), max(interval_seconds, wait))
    finally:
        signals.listen(None)
