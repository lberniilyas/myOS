"""Apply the user's answer to a follow-up question. Answers patch records that already exist."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.extraction_schema import Correction
from app.auth.models import User
from app.captures.apply import apply_plan
from app.captures.context import build_context
from app.captures.models import Capture, Clarification
from app.captures.planner import Planner
from app.captures.schemas import ClarificationAnswer
from app.core.enums import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    AmountPrecision,
    CaptureStatus,
    ChangeSource,
    ClarificationKind,
    ClarificationStatus,
    DurationPrecision,
    EventType,
    LinkSource,
    RevisionChangeType,
)
from app.core.formatting import format_duration
from app.core.money import parse_amount
from app.db.queries import get_owned
from app.errors import ConflictError, ValidationFailedError
from app.events.models import Event, EventProject
from app.events.service import record_revision, snapshot, soft_delete
from app.projects import service as project_service
from app.projects.models import Project
from app.projects.schemas import ProjectCreate


@dataclass
class AnswerResult:
    message: str
    events: list[Event] = field(default_factory=list)


def _option(clarification: Clarification, answer: ClarificationAnswer) -> dict:
    for option in clarification.options or []:
        if option["id"] == answer.option_id:
            return option
    raise ValidationFailedError("Pick one of the offered answers.")


def _live_event(db: Session, clarification: Clarification) -> Event | None:
    if clarification.event_id is None:
        return None
    event = db.get(Event, clarification.event_id)
    if event is None or event.deleted_at is not None:
        clarification.status = ClarificationStatus.EXPIRED
        db.commit()
        raise ConflictError("That entry no longer exists.", code="CLARIFICATION_EXPIRED")
    return event


def _revise(db: Session, event: Event, before: dict, now: datetime, capture_id) -> None:
    event.corrected_at = now
    record_revision(
        db,
        event,
        before,
        change_type=RevisionChangeType.UPDATE,
        change_source=ChangeSource.CLARIFICATION,
        capture_id=capture_id,
    )


def _link_project(
    db: Session, user: User, event: Event, project: Project, mention: str | None
) -> None:
    if all(link.project_id != project.id for link in event.project_links):
        event.project_links.append(
            EventProject(project_id=project.id, link_source=LinkSource.CLARIFICATION)
        )
    if event.area_id is None:
        event.area_id = project.area_id
    if mention:
        try:
            project_service.add_alias(db, user, project, mention)
        except (ConflictError, ValidationFailedError):
            pass


def answer_clarification(
    db: Session,
    user: User,
    clarification: Clarification,
    answer: ClarificationAnswer,
    now: datetime,
) -> AnswerResult:
    if clarification.status != ClarificationStatus.OPEN:
        raise ConflictError("This question was already answered.", code="CLARIFICATION_CLOSED")
    kind = clarification.kind
    event = _live_event(db, clarification)
    message = "Thanks — updated."

    if kind == ClarificationKind.AMOUNT:
        amount = parse_amount(answer.value)
        if amount is None:
            raise ValidationFailedError("Enter an amount like 25 or 12.50.")
        before = snapshot(event)
        event.amount = amount
        event.amount_precision = AmountPrecision.EXACT
        if event.currency is None and user.default_currency:
            event.currency = user.default_currency
        _revise(db, event, before, now, clarification.capture_id)
        message = f"Saved the amount for {event.title}."
    else:
        option = _option(clarification, answer)
        value = option.get("value")
        if kind == ClarificationKind.PROJECT_CHOICE and value:
            project = get_owned(db, Project, uuid.UUID(value), user.id, label="Project")
            before = snapshot(event)
            _link_project(db, user, event, project, (clarification.payload or {}).get("mention"))
            _revise(db, event, before, now, clarification.capture_id)
            message = f"Linked {event.title} to {project.name}."
        elif kind == ClarificationKind.CREATE_PROJECT and value:
            try:
                project = project_service.create_project(db, user, ProjectCreate(name=value))
            except ConflictError:
                project = db.scalar(
                    select(Project).where(
                        Project.user_id == user.id,
                        Project.deleted_at.is_(None),
                        func.lower(Project.name) == value.lower(),
                    )
                )
                if project is None:
                    raise
            before = snapshot(event)
            _link_project(db, user, event, project, None)
            _revise(db, event, before, now, clarification.capture_id)
            message = f"Created the project {project.name} and linked {event.title} to it."
        elif kind == ClarificationKind.DURATION and value:
            before = snapshot(event)
            event.duration_seconds = int(value) * 60
            event.duration_precision = DurationPrecision.APPROXIMATE
            if event.occurred_at is not None:
                event.ended_at = event.occurred_at + timedelta(seconds=event.duration_seconds)
            _revise(db, event, before, now, clarification.capture_id)
            message = f"Saved {format_duration(event.duration_seconds, event.duration_precision)} for {event.title}."
        elif kind == ClarificationKind.EXPENSE_CATEGORY and value:
            allowed = (
                EXPENSE_CATEGORIES if event.event_type == EventType.EXPENSE else INCOME_CATEGORIES
            )
            if value not in allowed:
                raise ValidationFailedError("Unknown category.")
            before = snapshot(event)
            event.category = value
            _revise(db, event, before, now, clarification.capture_id)
            message = f"Filed it under {value}."
        elif kind == ClarificationKind.DATE and value:
            new_day = date.fromisoformat(value)
            before = snapshot(event)
            if event.occurred_at is not None:
                shift = new_day - event.occurred_on
                event.occurred_at += shift
                if event.ended_at is not None:
                    event.ended_at += shift
            event.occurred_on = new_day
            if event.time_precision == "UNKNOWN":
                event.time_precision = "DATE_ONLY"
            _revise(db, event, before, now, clarification.capture_id)
            message = f"Moved {event.title} to {new_day.isoformat()}."
        elif kind == ClarificationKind.DUPLICATE and value == "same":
            soft_delete(
                db,
                event,
                change_source=ChangeSource.DUPLICATE_MERGE,
                change_type=RevisionChangeType.MERGE,
                capture_id=clarification.capture_id,
                now=now,
            )
            message = "Kept just one entry."
        elif kind == ClarificationKind.CORRECTION_TARGET and value:
            target = get_owned(db, Event, uuid.UUID(value), user.id, label="Event")
            capture = db.get(Capture, clarification.capture_id)
            correction = Correction.model_validate(clarification.payload["correction"])
            correction = correction.model_copy(update={"target_ref": "e1", "candidate_refs": []})
            ctx = build_context(db, user, capture)
            ctx.events = {"e1": target}
            planner = Planner(db, ctx)
            planner.apply_correction(target, correction)
            applied = apply_plan(db, capture, planner.plan, now)
            message = "Done." if not applied.warnings else applied.warnings[0]
        else:
            message = "Okay, left it as it is."

    clarification.status = ClarificationStatus.ANSWERED
    clarification.answer = answer.model_dump()
    clarification.resolved_at = now
    _close_capture_if_done(db, clarification)
    db.commit()
    return AnswerResult(message=message, events=[event] if event is not None else [])


def dismiss_clarification(db: Session, clarification: Clarification, now: datetime) -> None:
    if clarification.status == ClarificationStatus.OPEN:
        clarification.status = ClarificationStatus.DISMISSED
        clarification.resolved_at = now
        _close_capture_if_done(db, clarification)
        db.commit()


def _close_capture_if_done(db: Session, clarification: Clarification) -> None:
    db.flush()
    still_open = db.scalar(
        select(func.count(Clarification.id)).where(
            Clarification.capture_id == clarification.capture_id,
            Clarification.status == ClarificationStatus.OPEN,
        )
    )
    if not still_open:
        capture = db.get(Capture, clarification.capture_id)
        if capture is not None and capture.processing_status == CaptureStatus.NEEDS_CLARIFICATION:
            capture.processing_status = CaptureStatus.PROCESSED
