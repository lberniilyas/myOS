import uuid

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider, get_ai_provider
from app.auth.deps import get_current_user
from app.auth.models import User
from app.captures import pipeline
from app.captures.clarifications import answer_clarification, dismiss_clarification
from app.captures.models import Capture, Clarification
from app.captures.schemas import (
    CaptureCreate,
    CaptureListItem,
    CaptureResult,
    ClarificationAnswer,
    ClarificationOut,
)
from app.clock import Clock, get_clock
from app.core.enums import CaptureStatus, ClarificationStatus
from app.db.queries import get_owned
from app.db.session import get_db
from app.errors import ConflictError
from app.events.models import Event
from app.events.schemas import EventSummary
from app.events.service import to_summary

router = APIRouter(prefix="/v1", tags=["capture"])


@router.post("/captures", response_model=CaptureResult)
def create_capture(
    payload: CaptureCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai: AIProvider | None = Depends(get_ai_provider),
    clock: Clock = Depends(get_clock),
) -> CaptureResult:
    """Tell the system what happened. Returns what was recorded, in one short reply."""
    return pipeline.submit_capture(db, user, payload, ai, clock)


@router.get("/captures", response_model=list[CaptureListItem])
def list_captures(
    status: CaptureStatus | None = Query(default=None),
    unfinished: bool = Query(
        default=False, description="Only captures that failed or got stuck, to retry or remove."
    ),
    limit: int = Query(default=30, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CaptureListItem]:
    stmt = select(Capture).where(Capture.user_id == user.id)
    if status:
        stmt = stmt.where(Capture.processing_status == status)
    if unfinished:
        stmt = stmt.where(
            or_(
                Capture.processing_status == CaptureStatus.FAILED,
                and_(
                    Capture.processing_status == CaptureStatus.PROCESSING,
                    Capture.updated_at < func.now() - pipeline.STALE_PROCESSING,
                ),
            )
        )
    captures = db.scalars(stmt.order_by(Capture.received_at.desc()).limit(limit))
    return [
        CaptureListItem(
            id=c.id,
            client_capture_id=c.client_capture_id,
            status=c.processing_status,
            input_type=c.input_type,
            text=c.text,
            captured_at=c.captured_at,
            response_text=c.response_text,
            error_code=c.error_code,
            attempts=c.attempts,
        )
        for c in captures
    ]


@router.get("/captures/{capture_id}", response_model=CaptureResult)
def read_capture(
    capture_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CaptureResult:
    return pipeline.stored_result(get_owned(db, Capture, capture_id, user.id, label="Capture"))


@router.post("/captures/{capture_id}/retry", response_model=CaptureResult)
def retry_capture(
    capture_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai: AIProvider | None = Depends(get_ai_provider),
    clock: Clock = Depends(get_clock),
) -> CaptureResult:
    capture = get_owned(db, Capture, capture_id, user.id, label="Capture")
    if not pipeline.claim_for_retry(db, capture):
        raise ConflictError(
            "Only captures that failed or got stuck can be retried.", code="NOT_RETRYABLE"
        )
    return pipeline.process_capture(db, user, capture, ai, clock)


@router.delete("/captures/{capture_id}", status_code=204)
def delete_capture(
    capture_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    """Erase a message that never became entries (one that failed, say), words included."""
    capture = get_owned(db, Capture, capture_id, user.id, label="Capture")
    if db.scalar(select(func.count(Event.id)).where(Event.capture_id == capture.id)):
        raise ConflictError(
            "This message created entries; delete those entries instead.", code="HAS_ENTRIES"
        )
    db.delete(capture)
    db.commit()
    return Response(status_code=204)


@router.get("/clarifications", response_model=list[ClarificationOut])
def list_clarifications(
    status: ClarificationStatus = Query(default=ClarificationStatus.OPEN),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ClarificationOut]:
    stmt = (
        select(Clarification)
        .where(
            Clarification.user_id == user.id,
            Clarification.status == status,
            # Questions about entries deleted since they were asked are moot.
            ~exists().where(Event.id == Clarification.event_id, Event.deleted_at.is_not(None)),
        )
        .order_by(Clarification.created_at.desc())
        .limit(50)
    )
    return [pipeline.clarification_out(c) for c in db.scalars(stmt)]


class ClarificationAnswered(BaseModel):
    message: str
    clarification: ClarificationOut
    events: list[EventSummary]


@router.post("/clarifications/{clarification_id}/answer", response_model=ClarificationAnswered)
def answer(
    clarification_id: uuid.UUID,
    payload: ClarificationAnswer,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ClarificationAnswered:
    clarification = get_owned(db, Clarification, clarification_id, user.id, label="Question")
    result = answer_clarification(db, user, clarification, payload, clock.now())
    return ClarificationAnswered(
        message=result.message,
        clarification=pipeline.clarification_out(clarification),
        events=[to_summary(e, user.timezone) for e in result.events if e.deleted_at is None],
    )


@router.post("/clarifications/{clarification_id}/dismiss", response_model=ClarificationOut)
def dismiss(
    clarification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ClarificationOut:
    clarification = get_owned(db, Clarification, clarification_id, user.id, label="Question")
    dismiss_clarification(db, clarification, clock.now())
    return pipeline.clarification_out(clarification)
