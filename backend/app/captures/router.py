import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider, get_ai_provider
from app.auth.deps import get_current_user
from app.auth.models import User
from app.captures import pipeline, worker
from app.captures.clarifications import answer_clarification, dismiss_clarification
from app.captures.models import Capture, Clarification
from app.captures.retries import retrying
from app.captures.schemas import (
    CaptureCreate,
    CaptureListItem,
    CaptureResult,
    ClarificationAnswer,
    ClarificationOut,
)
from app.clock import Clock, get_clock
from app.config import get_settings
from app.core.enums import CaptureStatus, ClarificationStatus
from app.db.queries import get_owned
from app.db.session import get_db, get_session_factory
from app.errors import ConflictError
from app.events.models import Event
from app.events.schemas import EventSummary
from app.events.service import to_summary

router = APIRouter(prefix="/v1", tags=["capture"])
SessionFactory = worker.SessionFactory


@router.post("/captures", response_model=CaptureResult)
def create_capture(
    payload: CaptureCreate,
    response: Response,
    tasks: BackgroundTasks,
    background: bool = Query(
        default=False,
        description=(
            "Reply as soon as the words are stored (202) and understand them afterwards; poll "
            "GET /v1/captures/{id}. Ignored on serverless hosts, which can't work after replying."
        ),
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai: AIProvider | None = Depends(get_ai_provider),
    clock: Clock = Depends(get_clock),
    sessions: SessionFactory = Depends(get_session_factory),
) -> CaptureResult:
    """Tell the system what happened. Returns what was recorded, in one short reply."""
    later = None
    if background and get_settings().background_captures:

        def later(capture_id: uuid.UUID) -> None:
            tasks.add_task(worker.run_capture, sessions, capture_id, ai, clock, claimed=True)

    result = pipeline.submit_capture(db, user, payload, ai, clock, later=later)
    if result.capture.status in (CaptureStatus.CAPTURED, CaptureStatus.PROCESSING):
        response.status_code = 202
    return result


@router.get("/captures", response_model=list[CaptureListItem])
def list_captures(
    status: CaptureStatus | None = Query(default=None),
    unfinished: bool = Query(
        default=False,
        description="Only captures that need the person: failed for good or stuck. Retry or remove.",
    ),
    pending: bool = Query(
        default=False,
        description="Only captures still being understood, or failed but retried by the server.",
    ),
    limit: int = Query(default=30, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CaptureListItem]:
    stmt = select(Capture).where(Capture.user_id == user.id)
    if status:
        stmt = stmt.where(Capture.processing_status == status)
    stuck = and_(
        Capture.processing_status == CaptureStatus.PROCESSING,
        Capture.updated_at < func.now() - pipeline.STALE_PROCESSING,
    )
    # Without a background worker (serverless) the server never retries by itself.
    server_retries = retrying() if get_settings().background_captures else false()
    if unfinished:
        stmt = stmt.where(
            or_(and_(Capture.processing_status == CaptureStatus.FAILED, ~server_retries), stuck)
        )
    if pending:
        stmt = stmt.where(
            or_(
                and_(
                    Capture.processing_status.in_(
                        [CaptureStatus.CAPTURED, CaptureStatus.PROCESSING]
                    ),
                    ~stuck,
                ),
                server_retries,
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
            will_retry=pipeline.server_will_retry(c),
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
