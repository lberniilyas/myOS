import base64
import json
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from sqlalchemy import exists, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.areas.models import Area
from app.auth.models import User
from app.captures.models import Capture, Clarification
from app.clock import Clock
from app.core.enums import (
    OPEN_TASK_STATUSES,
    CaptureStatus,
    ChangeSource,
    ClarificationStatus,
    CreatedBy,
    DurationPrecision,
    LinkSource,
    RevisionChangeType,
    SourceType,
    TaskStatus,
    TimePrecision,
)
from app.core.formatting import format_amount, format_duration
from app.core.money import normalize_currency
from app.core.timeutil import local_date_of, local_today, zone_for
from app.db.queries import get_owned
from app.errors import ValidationFailedError
from app.events.models import (
    Event,
    EventGoal,
    EventKnowledge,
    EventProject,
    EventRevision,
    EventTask,
)
from app.events.schemas import (
    EntityRef,
    EventCreate,
    EventDetail,
    EventSummary,
    EventUpdate,
    HabitRef,
    KnowledgeRef,
    Provenance,
)
from app.goals.models import Goal
from app.knowledge.models import Knowledge, KnowledgeAlias
from app.projects.models import Project, ProjectAlias
from app.tasks.models import Task

SNAPSHOT_FIELDS = (
    "event_type",
    "title",
    "description",
    "category",
    "occurred_on",
    "occurred_at",
    "ended_at",
    "duration_seconds",
    "time_precision",
    "duration_precision",
    "day_period",
    "amount",
    "currency",
    "amount_precision",
    "structured_data",
    "area_id",
    "deleted_at",
)


def _plain(value: object) -> object:
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def confidence_label(confidence: float | None) -> str | None:
    if confidence is None:
        return None
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


# --- serialization -----------------------------------------------------------------------


def to_summary(event: Event, timezone_name: str) -> EventSummary:
    local_time = None
    if event.occurred_at is not None:
        local_time = event.occurred_at.astimezone(zone_for(timezone_name)).strftime("%H:%M")
    return EventSummary(
        id=event.id,
        event_type=event.event_type,
        title=event.title,
        category=event.category,
        occurred_on=event.occurred_on,
        occurred_at=event.occurred_at,
        ended_at=event.ended_at,
        local_time=local_time,
        day_period=event.day_period,
        time_precision=event.time_precision,
        duration_seconds=event.duration_seconds,
        duration_precision=event.duration_precision,
        duration_display=format_duration(event.duration_seconds, event.duration_precision),
        amount=event.amount,
        currency=event.currency,
        amount_precision=event.amount_precision,
        amount_display=format_amount(event.amount, event.currency, event.amount_precision),
        projects=[
            EntityRef(id=link.project.id, name=link.project.name) for link in event.project_links
        ],
        source_type=event.source_type,
        capture_id=event.capture_id,
        created_at=event.created_at,
    )


def to_detail(db: Session, event: Event, timezone_name: str) -> EventDetail:
    summary = to_summary(event, timezone_name)
    capture = db.get(Capture, event.capture_id) if event.capture_id else None
    area = db.get(Area, event.area_id) if event.area_id else None
    revision_count = db.scalar(
        select(func.count()).select_from(EventRevision).where(EventRevision.event_id == event.id)
    )
    return EventDetail(
        **summary.model_dump(),
        description=event.description,
        structured_data=event.structured_data or {},
        area=EntityRef(id=area.id, name=area.name) if area else None,
        goals=[EntityRef(id=link.goal.id, name=link.goal.title) for link in event.goal_links],
        knowledge=[
            KnowledgeRef(
                id=link.knowledge.id,
                title=link.knowledge.title,
                understanding_state=link.knowledge.understanding_state,
            )
            for link in event.knowledge_links
        ],
        tasks=[EntityRef(id=link.task.id, name=link.task.title) for link in event.task_links],
        habits=[
            HabitRef(id=link.habit.id, name=link.habit.name, outcome=link.outcome)
            for link in event.habit_links
        ],
        provenance=Provenance(
            source_type=event.source_type,
            created_by=event.created_by.value,
            capture_id=event.capture_id,
            input_type=capture.input_type.value if capture else None,
            captured_at=capture.captured_at if capture else None,
            evidence=event.evidence,
            extraction_confidence=event.extraction_confidence,
            confidence_label=confidence_label(event.extraction_confidence),
            extraction_version=event.extraction_version,
            model_name=capture.model_name if capture else None,
        ),
        updated_at=event.updated_at,
        corrected_at=event.corrected_at,
        deleted_at=event.deleted_at,
        revision_count=revision_count or 0,
        related_event_count=related_event_count(db, event),
    )


def related_event_count(db: Session, event: Event) -> int:
    project_ids = [link.project_id for link in event.project_links]
    knowledge_ids = [link.knowledge_id for link in event.knowledge_links]
    if not project_ids and not knowledge_ids:
        return 0
    conditions = []
    if project_ids:
        conditions.append(
            exists().where(
                EventProject.event_id == Event.id, EventProject.project_id.in_(project_ids)
            )
        )
    if knowledge_ids:
        conditions.append(
            exists().where(
                EventKnowledge.event_id == Event.id, EventKnowledge.knowledge_id.in_(knowledge_ids)
            )
        )
    count = db.scalar(
        select(func.count(Event.id)).where(
            Event.user_id == event.user_id,
            Event.deleted_at.is_(None),
            Event.id != event.id,
            or_(*conditions),
        )
    )
    return count or 0


# --- revisions -----------------------------------------------------------------------------


def snapshot(event: Event) -> dict:
    data = {field: _plain(getattr(event, field)) for field in SNAPSHOT_FIELDS}
    data["project_ids"] = sorted(str(link.project_id) for link in event.project_links)
    data["goal_ids"] = sorted(str(link.goal_id) for link in event.goal_links)
    data["knowledge_ids"] = sorted(str(link.knowledge_id) for link in event.knowledge_links)
    data["task_ids"] = sorted(str(link.task_id) for link in event.task_links)
    data["habits"] = sorted(
        (
            {"habit_id": str(link.habit_id), "outcome": link.outcome.value}
            for link in event.habit_links
        ),
        key=lambda item: item["habit_id"],
    )
    return data


def record_revision(
    db: Session,
    event: Event,
    before: dict | None,
    *,
    change_type: RevisionChangeType,
    change_source: ChangeSource,
    capture_id: uuid.UUID | None = None,
) -> EventRevision:
    db.flush()
    current = db.scalar(
        select(func.max(EventRevision.revision_number)).where(EventRevision.event_id == event.id)
    )
    revision = EventRevision(
        event_id=event.id,
        user_id=event.user_id,
        revision_number=(current or 0) + 1,
        change_type=change_type,
        change_source=change_source,
        capture_id=capture_id,
        before=before,
        after=snapshot(event),
    )
    db.add(revision)
    return revision


# --- links ---------------------------------------------------------------------------------


def _owned_ids(db: Session, model: type, ids: Iterable[uuid.UUID], user: User, label: str) -> list:
    unique_ids = list(dict.fromkeys(ids))
    for entity_id in unique_ids:
        get_owned(db, model, entity_id, user.id, label=label)
    return unique_ids


def replace_links(
    db: Session,
    event: Event,
    user: User,
    *,
    project_ids: list[uuid.UUID] | None = None,
    goal_ids: list[uuid.UUID] | None = None,
    knowledge_ids: list[uuid.UUID] | None = None,
    task_ids: list[uuid.UUID] | None = None,
    source: LinkSource = LinkSource.USER,
) -> None:
    if project_ids is not None:
        ids = _owned_ids(db, Project, project_ids, user, "Project")
        event.project_links = [EventProject(project_id=i, link_source=source) for i in ids]
    if goal_ids is not None:
        ids = _owned_ids(db, Goal, goal_ids, user, "Goal")
        event.goal_links = [EventGoal(goal_id=i, link_source=source) for i in ids]
    if knowledge_ids is not None:
        ids = _owned_ids(db, Knowledge, knowledge_ids, user, "Knowledge")
        event.knowledge_links = [EventKnowledge(knowledge_id=i, link_source=source) for i in ids]
    if task_ids is not None:
        ids = _owned_ids(db, Task, task_ids, user, "Task")
        event.task_links = [EventTask(task_id=i, link_source=source) for i in ids]


# --- manual create / edit ------------------------------------------------------------------


def _currency_or_error(value: str | None) -> str | None:
    if value is None:
        return None
    code = normalize_currency(value)
    if code is None:
        raise ValidationFailedError("Use an ISO 4217 currency code such as 'MAD' or 'EUR'.")
    return code


def create_manual_event(db: Session, user: User, payload: EventCreate, clock: Clock) -> Event:
    occurred_at = payload.occurred_at
    ended_at = payload.ended_at
    if occurred_at is not None and occurred_at.tzinfo is None:
        raise ValidationFailedError("occurred_at needs a timezone offset.")
    if ended_at is not None and ended_at.tzinfo is None:
        raise ValidationFailedError("ended_at needs a timezone offset.")
    if occurred_at is not None:
        occurred_on = local_date_of(occurred_at, user.timezone)
    else:
        occurred_on = payload.occurred_on or local_today(user.timezone, clock)
    duration_seconds = round(payload.duration_minutes * 60) if payload.duration_minutes else None
    if occurred_at and ended_at:
        if ended_at < occurred_at:
            raise ValidationFailedError("ended_at must be after occurred_at.")
        if duration_seconds is None:
            duration_seconds = int((ended_at - occurred_at).total_seconds())
    elif occurred_at and duration_seconds and ended_at is None:
        ended_at = occurred_at + timedelta(seconds=duration_seconds)
    event = Event(
        user_id=user.id,
        source_type=SourceType.MANUAL_INPUT,
        created_by=CreatedBy.USER,
        event_type=payload.event_type,
        title=payload.title.strip(),
        description=payload.description,
        category=payload.category,
        occurred_on=occurred_on,
        occurred_at=occurred_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        time_precision=TimePrecision.EXACT if occurred_at else TimePrecision.DATE_ONLY,
        duration_precision=(
            payload.duration_precision or DurationPrecision.EXACT
            if duration_seconds is not None
            else DurationPrecision.UNKNOWN
        ),
        amount=payload.amount.quantize(Decimal("0.01")) if payload.amount else None,
        currency=_currency_or_error(payload.currency)
        or (user.default_currency if payload.amount else None),
        amount_precision=(payload.amount_precision or "EXACT") if payload.amount else None,
        structured_data=payload.structured_data,
    )
    db.add(event)
    replace_links(
        db,
        event,
        user,
        project_ids=payload.project_ids,
        goal_ids=payload.goal_ids,
        knowledge_ids=payload.knowledge_ids,
        task_ids=payload.task_ids,
    )
    db.commit()
    return event


def update_event(
    db: Session, user: User, event: Event, payload: EventUpdate, now: datetime
) -> Event:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return event
    before = snapshot(event)

    for field in ("event_type", "title", "description", "category", "structured_data"):
        if field in changes:
            value = changes[field]
            if field == "title" and value is None:
                raise ValidationFailedError("title can't be empty.")
            if field == "structured_data" and value is None:
                value = {}
            setattr(
                event,
                field,
                value.strip() if isinstance(value, str) and field == "title" else value,
            )

    if "area_id" in changes:
        area_id = changes["area_id"]
        if area_id is not None:
            get_owned(db, Area, area_id, user.id, label="Area")
        event.area_id = area_id

    if "occurred_at" in changes:
        occurred_at = changes["occurred_at"]
        if occurred_at is not None:
            if occurred_at.tzinfo is None:
                raise ValidationFailedError("occurred_at needs a timezone offset.")
            event.occurred_on = local_date_of(occurred_at, user.timezone)
            event.time_precision = changes.get("time_precision") or TimePrecision.EXACT
        else:
            event.time_precision = TimePrecision.DATE_ONLY
        event.occurred_at = occurred_at
    if "occurred_on" in changes and changes["occurred_on"] is not None:
        new_day = changes["occurred_on"]
        if event.occurred_at is not None and "occurred_at" not in changes:
            shift = new_day - event.occurred_on
            event.occurred_at = event.occurred_at + shift
            if event.ended_at is not None:
                event.ended_at = event.ended_at + shift
        event.occurred_on = new_day
    if "time_precision" in changes and changes["time_precision"] and "occurred_at" not in changes:
        event.time_precision = changes["time_precision"]
    if "ended_at" in changes:
        ended_at = changes["ended_at"]
        if ended_at is not None and ended_at.tzinfo is None:
            raise ValidationFailedError("ended_at needs a timezone offset.")
        event.ended_at = ended_at
    minutes = changes.get("duration_minutes")
    # An edit form that sends back the minutes it shows isn't a new measurement: "~2h" stays
    # approximate unless the length or its precision really changed.
    resent = (
        minutes is not None
        and event.duration_seconds is not None
        and abs(round(minutes * 60) - event.duration_seconds) < 60
        and not changes.get("duration_precision")
    )
    if "duration_minutes" in changes and not resent:
        event.duration_seconds = round(minutes * 60) if minutes else None
        event.duration_precision = (
            changes.get("duration_precision") or DurationPrecision.EXACT
            if minutes
            else DurationPrecision.UNKNOWN
        )
        if event.occurred_at is not None and event.duration_seconds and "ended_at" not in changes:
            event.ended_at = event.occurred_at + timedelta(seconds=event.duration_seconds)
    elif "duration_precision" in changes and changes["duration_precision"]:
        event.duration_precision = changes["duration_precision"]
    if event.occurred_at and event.ended_at:
        if event.ended_at < event.occurred_at:
            raise ValidationFailedError("ended_at must be after occurred_at.")
        if ("duration_minutes" not in changes or resent) and (
            "ended_at" in changes or "occurred_at" in changes
        ):
            event.duration_seconds = int((event.ended_at - event.occurred_at).total_seconds())

    if "amount" in changes:
        amount = changes["amount"]
        event.amount = amount.quantize(Decimal("0.01")) if amount is not None else None
        if amount is None:
            event.amount_precision = None
        elif event.amount_precision is None:
            event.amount_precision = changes.get("amount_precision") or "EXACT"
        if amount is not None and event.currency is None and "currency" not in changes:
            event.currency = user.default_currency  # decision #6: the profile's usual currency
    if "currency" in changes:
        event.currency = _currency_or_error(changes["currency"])
    if "amount_precision" in changes and changes["amount_precision"] and event.amount is not None:
        event.amount_precision = changes["amount_precision"]

    replace_links(
        db,
        event,
        user,
        project_ids=changes.get("project_ids"),
        goal_ids=changes.get("goal_ids"),
        knowledge_ids=changes.get("knowledge_ids"),
        task_ids=changes.get("task_ids"),
    )
    event.corrected_at = now
    record_revision(
        db,
        event,
        before,
        change_type=RevisionChangeType.UPDATE,
        change_source=ChangeSource.USER_EDIT,
    )
    db.commit()
    db.refresh(event)
    return event


def soft_delete(
    db: Session,
    event: Event,
    *,
    change_source: ChangeSource = ChangeSource.USER_EDIT,
    change_type: RevisionChangeType = RevisionChangeType.DELETE,
    capture_id: uuid.UUID | None = None,
    now: datetime,
) -> None:
    before = snapshot(event)
    event.deleted_at = now
    record_revision(
        db,
        event,
        before,
        change_type=change_type,
        change_source=change_source,
        capture_id=capture_id,
    )
    _reopen_tasks_it_completed(db, event)
    _expire_questions_about(db, event, now)


def restore(db: Session, event: Event, now: datetime) -> None:
    before = snapshot(event)
    event.deleted_at = None
    record_revision(
        db,
        event,
        before,
        change_type=RevisionChangeType.RESTORE,
        change_source=ChangeSource.USER_EDIT,
    )
    for link in event.task_links:
        task = link.task
        if link.link_source == LinkSource.AI and task.status in OPEN_TASK_STATUSES:
            task.status = TaskStatus.COMPLETED
            task.completed_at = event.ended_at or event.occurred_at or now


def _reopen_tasks_it_completed(db: Session, event: Event) -> None:
    """A task this event marked done is open again, unless another live entry also did it."""
    for link in event.task_links:
        task = link.task
        if link.link_source != LinkSource.AI or task.status != TaskStatus.COMPLETED:
            continue
        also_done = db.scalar(
            select(func.count(EventTask.event_id))
            .join(Event, Event.id == EventTask.event_id)
            .where(
                EventTask.task_id == task.id,
                Event.id != event.id,
                Event.deleted_at.is_(None),
            )
        )
        if not also_done:
            task.status = TaskStatus.TODO
            task.completed_at = None


def _expire_questions_about(db: Session, event: Event, now: datetime) -> None:
    """Open questions about a deleted entry no longer make sense."""
    questions = db.scalars(
        select(Clarification).where(
            Clarification.event_id == event.id,
            Clarification.status == ClarificationStatus.OPEN,
        )
    ).all()
    for question in questions:
        question.status = ClarificationStatus.EXPIRED
        question.resolved_at = now
    db.flush()
    for capture_id in {q.capture_id for q in questions}:
        still_open = db.scalar(
            select(func.count(Clarification.id)).where(
                Clarification.capture_id == capture_id,
                Clarification.status == ClarificationStatus.OPEN,
            )
        )
        capture = db.get(Capture, capture_id)
        if (
            not still_open
            and capture is not None
            and capture.processing_status == CaptureStatus.NEEDS_CLARIFICATION
        ):
            capture.processing_status = CaptureStatus.PROCESSED


# --- timeline ------------------------------------------------------------------------------


def encode_cursor(event: Event) -> str:
    payload = {
        "d": event.occurred_on.isoformat(),
        "s": event.sort_at.isoformat(),
        "i": str(event.id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[date, datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return (
            date.fromisoformat(payload["d"]),
            datetime.fromisoformat(payload["s"]),
            uuid.UUID(payload["i"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ValidationFailedError("Invalid cursor.") from exc


def like_pattern(query: str) -> str:
    """A LIKE pattern matching the words literally: % and _ typed by the person are not wildcards."""
    escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_condition(query: str):
    """Events matching the words in their own fields, the person's original words, or the names
    and nicknames of the projects and concepts they are linked to ("TenderPilot", "RAG")."""
    pattern = like_pattern(query)

    def like(column):
        return column.ilike(pattern, escape="\\")

    linked_project = (
        select(EventProject.event_id)
        .join(Project, Project.id == EventProject.project_id)
        .outerjoin(ProjectAlias, ProjectAlias.project_id == Project.id)
        .where(EventProject.event_id == Event.id, or_(like(Project.name), like(ProjectAlias.alias)))
        .exists()
    )
    linked_knowledge = (
        select(EventKnowledge.event_id)
        .join(Knowledge, Knowledge.id == EventKnowledge.knowledge_id)
        .outerjoin(KnowledgeAlias, KnowledgeAlias.knowledge_id == Knowledge.id)
        .where(
            EventKnowledge.event_id == Event.id,
            or_(like(Knowledge.title), like(KnowledgeAlias.alias)),
        )
        .exists()
    )
    return or_(
        Event.search_vector.op("@@")(func.websearch_to_tsquery("simple", query)),
        like(Event.title),
        like(Event.description),
        like(Event.evidence),
        like(Event.category),
        linked_project,
        linked_knowledge,
    )


def timeline(
    db: Session,
    user: User,
    *,
    start: date | None,
    end: date | None,
    event_types: list[str] | None,
    project_id: uuid.UUID | None,
    query: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[Event], str | None]:
    stmt = select(Event).where(Event.user_id == user.id, Event.deleted_at.is_(None))
    if start:
        stmt = stmt.where(Event.occurred_on >= start)
    if end:
        stmt = stmt.where(Event.occurred_on <= end)
    if event_types:
        stmt = stmt.where(Event.event_type.in_(event_types))
    if project_id:
        stmt = stmt.where(
            exists().where(EventProject.event_id == Event.id, EventProject.project_id == project_id)
        )
    if query and query.strip():
        stmt = stmt.where(search_condition(query))
    if cursor:
        on, sort_at, event_id = decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(Event.occurred_on, Event.sort_at, Event.id) < (on, sort_at, event_id)
        )
    stmt = stmt.order_by(Event.occurred_on.desc(), Event.sort_at.desc(), Event.id.desc()).limit(
        limit + 1
    )
    rows = list(db.scalars(stmt))
    next_cursor = encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor
