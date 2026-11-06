import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider, get_ai_provider
from app.auth.deps import get_current_user
from app.auth.models import User
from app.captures import pipeline
from app.captures.models import Capture
from app.captures.schemas import CaptureResult
from app.clock import Clock, get_clock
from app.core.enums import CaptureStatus, EventType, InputType
from app.db.queries import get_owned
from app.db.session import get_db
from app.errors import ConflictError
from app.events import service
from app.events.models import Event, EventRevision
from app.events.schemas import (
    CorrectionRequest,
    DeletedEvent,
    EventCreate,
    EventDetail,
    EventUpdate,
    RevisionOut,
    TimelinePage,
)

router = APIRouter(prefix="/v1", tags=["events"])


@router.get("/timeline", response_model=TimelinePage)
def timeline(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    event_type: list[EventType] | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimelinePage:
    events, next_cursor = service.timeline(
        db,
        user,
        start=start,
        end=end,
        event_types=event_type,
        project_id=project_id,
        query=q,
        limit=limit,
        cursor=cursor,
    )
    return TimelinePage(
        items=[service.to_summary(e, user.timezone) for e in events], next_cursor=next_cursor
    )


@router.post("/events", response_model=EventDetail, status_code=201)
def create_event(
    payload: EventCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> EventDetail:
    event = service.create_manual_event(db, user, payload, clock)
    return service.to_detail(db, event, user.timezone)


@router.get("/events/deleted", response_model=list[DeletedEvent])
def list_deleted(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DeletedEvent]:
    """Recently deleted entries, newest first, so a deletion can be undone."""
    events = db.scalars(
        select(Event)
        .where(Event.user_id == user.id, Event.deleted_at.is_not(None))
        .order_by(Event.deleted_at.desc())
        .limit(limit)
    )
    return [
        DeletedEvent(**service.to_summary(e, user.timezone).model_dump(), deleted_at=e.deleted_at)
        for e in events
    ]


@router.get("/events/{event_id}", response_model=EventDetail)
def read_event(
    event_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> EventDetail:
    event = get_owned(db, Event, event_id, user.id, label="Event", include_deleted=True)
    return service.to_detail(db, event, user.timezone)


@router.patch("/events/{event_id}", response_model=EventDetail)
def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> EventDetail:
    event = get_owned(db, Event, event_id, user.id, label="Event")
    event = service.update_event(db, user, event, payload, clock.now())
    return service.to_detail(db, event, user.timezone)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: uuid.UUID,
    permanent: bool = Query(default=False, description="Erase the event and its history for good."),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    event = get_owned(db, Event, event_id, user.id, label="Event", include_deleted=permanent)
    if permanent:
        capture_id = event.capture_id
        if event.deleted_at is None:
            service.soft_delete(db, event, now=clock.now())  # reopens tasks, closes questions
        db.delete(event)
        db.flush()
        # "Permanent" includes the words you said, once no other entry comes from them.
        if capture_id is not None and not db.scalar(
            select(func.count(Event.id)).where(Event.capture_id == capture_id)
        ):
            capture = db.get(Capture, capture_id)
            if capture is not None:
                db.delete(capture)
    else:
        service.soft_delete(db, event, now=clock.now())
    db.commit()
    return Response(status_code=204)


@router.post("/events/{event_id}/restore", response_model=EventDetail)
def restore_event(
    event_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> EventDetail:
    event = get_owned(db, Event, event_id, user.id, label="Event", include_deleted=True)
    if event.deleted_at is None:
        raise ConflictError("This event isn't deleted.", code="NOT_DELETED")
    service.restore(db, event, clock.now())
    db.commit()
    return service.to_detail(db, event, user.timezone)


@router.get("/events/{event_id}/revisions", response_model=list[RevisionOut])
def list_revisions(
    event_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[RevisionOut]:
    event = get_owned(db, Event, event_id, user.id, label="Event", include_deleted=True)
    revisions = db.scalars(
        select(EventRevision)
        .where(EventRevision.event_id == event.id)
        .order_by(EventRevision.revision_number)
    )
    return [
        RevisionOut(
            id=r.id,
            revision_number=r.revision_number,
            change_type=r.change_type.value,
            change_source=r.change_source.value,
            capture_id=r.capture_id,
            before=r.before,
            after=r.after,
            created_at=r.created_at,
        )
        for r in revisions
    ]


@router.post("/events/{event_id}/correct", response_model=CaptureResult)
def correct_event(
    event_id: uuid.UUID,
    payload: CorrectionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai: AIProvider | None = Depends(get_ai_provider),
    clock: Clock = Depends(get_clock),
) -> CaptureResult:
    """Correct one event in plain words, e.g. "actually this happened yesterday"."""
    event = get_owned(db, Event, event_id, user.id, label="Event")
    now = clock.now()
    capture = Capture(
        user_id=user.id,
        input_type=InputType.TEXT,
        raw_text=payload.text.strip(),
        captured_at=now,
        received_at=now,
        target_event_id=event.id,
        processing_status=CaptureStatus.CAPTURED,
    )
    db.add(capture)
    db.commit()
    return pipeline.process_capture(db, user, capture, ai, clock)
