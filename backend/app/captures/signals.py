"""A nudge from where captures change to the background sweep.

The sweep sleeps until the next retry is due, so an idle server leaves the database alone
and a hosted database can scale to zero. When a capture fails, the pipeline calls changed(),
and the sweep wakes to plan its retry.
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

_listener: Callable[[], None] | None = None


def listen(callback: Callable[[], None] | None) -> None:
    global _listener
    _listener = callback


def changed() -> None:
    if _listener is None:
        return
    try:
        _listener()
    except Exception:  # noqa: BLE001 - a missed nudge only delays a retry; never fail a save
        logger.exception("Couldn't wake the background sweep")
