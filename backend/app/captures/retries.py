"""When the server retries a failed capture on its own (see worker.py)."""

from sqlalchemy import and_

from app.captures.models import Capture
from app.core.enums import CaptureStatus

# Failures that can clear up by themselves. Missing or rejected keys, refusals and unknown
# models need a person, so those wait on Home for "Try again".
AUTO_RETRY_CODES = (
    "AI_RATE_LIMITED",
    "AI_UNAVAILABLE",
    "AI_TIMEOUT",
    "AI_EMPTY_RESPONSE",
    "AI_OUTPUT_TRUNCATED",
    "AI_INVALID_OUTPUT",
    "AI_ERROR",
    "PERSISTENCE_FAILED",
)
# Pause before the 2nd, 3rd, 4th and 5th attempt, in retry units (a minute in production).
RETRY_DELAYS = (1, 5, 15, 60)
AUTO_ATTEMPTS = len(RETRY_DELAYS) + 1


def retrying():
    """SQL condition: failed, but the server will try again on its own."""
    return and_(
        Capture.processing_status == CaptureStatus.FAILED,
        Capture.error_code.in_(AUTO_RETRY_CODES),
        Capture.attempts < AUTO_ATTEMPTS,
    )


def will_retry(capture: Capture) -> bool:
    return (
        capture.processing_status == CaptureStatus.FAILED
        and capture.error_code in AUTO_RETRY_CODES
        and capture.attempts < AUTO_ATTEMPTS
    )
