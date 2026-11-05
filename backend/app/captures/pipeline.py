"""The capture lifecycle (spec #8 §9): store → understand → plan → persist → reply.

The raw input is committed before any AI call, so a failure never loses what the user said;
a failed capture can be retried later (spec #5 §28).
"""

import logging
import time
from datetime import timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.extraction_schema import EXTRACTION_VERSION, ExtractionOutput
from app.ai.prompts import load_prompt
from app.ai.provider import AIProvider, AIProviderError
from app.assistant.service import answer_question
from app.auth.models import User
from app.captures.apply import AppliedChanges, apply_plan
from app.captures.context import build_context, render_user_prompt
from app.captures.models import Capture, Clarification
from app.captures.planner import build_plan
from app.captures.schemas import (
    AnswerOut,
    CaptureCreate,
    CaptureInfo,
    CaptureResult,
    ClarificationOut,
    ErrorOut,
    EventChange,
    NamedRef,
    TaskRef,
)
from app.captures.summary import build_message
from app.clock import Clock
from app.core.enums import CaptureStatus, ClarificationKind
from app.events.service import to_summary

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = "v1"
DOUBLE_SUBMIT_WINDOW = timedelta(minutes=2)
FAILURE_MESSAGE = "I couldn't process that yet. Your entry is saved and I'll try again shortly."
# Longer than any single run can last (Vercel stops a function after 300 s), so a capture
# still marked PROCESSING after this was cut off by a crash or timeout.
STALE_PROCESSING = timedelta(minutes=10)
# Resending a failed capture runs it again, up to this many runs in total.
MAX_ATTEMPTS = 20


def clarification_out(item: Clarification) -> ClarificationOut:
    return ClarificationOut(
        id=item.id,
        kind=item.kind,
        question=item.question,
        options=item.options or [],
        answer_type="amount" if item.kind == ClarificationKind.AMOUNT else "choice",
        event_id=item.event_id,
        capture_id=item.capture_id,
        status=item.status,
        created_at=item.created_at,
    )


def _info(capture: Capture) -> CaptureInfo:
    return CaptureInfo(
        id=capture.id,
        status=capture.processing_status,
        input_type=capture.input_type,
        captured_at=capture.captured_at,
        intent=capture.intent,
        language=capture.language,
    )


def stored_result(capture: Capture) -> CaptureResult:
    if capture.result:
        result = CaptureResult.model_validate(capture.result)
        result.capture = _info(capture)
        return result
    error = None
    if capture.processing_status == CaptureStatus.PROCESSING:
        error = ErrorOut(
            code="STILL_PROCESSING", message="This entry is still being processed.", retryable=True
        )
    elif capture.error_code:
        error = ErrorOut(
            code=capture.error_code,
            message=FAILURE_MESSAGE,
            retryable=capture.attempts < MAX_ATTEMPTS,
        )
    return CaptureResult(
        capture=_info(capture), message=capture.response_text or FAILURE_MESSAGE, error=error
    )


def claim_for_retry(db: Session, capture: Capture) -> bool:
    """Atomically take a failed capture, or one stuck in PROCESSING after its run died.

    Returns False when it doesn't need a run or another request already took it, so two
    resends arriving together never process the same words twice.
    """
    # Compared on the database clock: a crash or a timeout leaves no other trace.
    stuck = and_(
        Capture.processing_status == CaptureStatus.PROCESSING,
        Capture.updated_at < func.now() - STALE_PROCESSING,
    )
    claimed = db.execute(
        update(Capture)
        .where(
            Capture.id == capture.id,
            Capture.attempts < MAX_ATTEMPTS,
            or_(
                Capture.processing_status.in_([CaptureStatus.FAILED, CaptureStatus.CAPTURED]),
                stuck,
            ),
        )
        .values(processing_status=CaptureStatus.PROCESSING, updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    db.refresh(capture)
    return claimed == 1


def submit_capture(
    db: Session, user: User, payload: CaptureCreate, ai: AIProvider | None, clock: Clock
) -> CaptureResult:
    now = clock.now()
    if payload.client_capture_id is not None:
        existing = db.scalar(
            select(Capture).where(
                Capture.user_id == user.id, Capture.client_capture_id == payload.client_capture_id
            )
        )
        if existing is not None:
            # The app resends what it couldn't get processed, so a resend doubles as a retry.
            if claim_for_retry(db, existing):
                return process_capture(db, user, existing, ai, clock)
            return stored_result(existing)
    else:
        recent = db.scalar(
            select(Capture)
            .where(
                Capture.user_id == user.id,
                Capture.raw_text == payload.content,
                Capture.received_at >= now - DOUBLE_SUBMIT_WINDOW,
                Capture.processing_status.in_(
                    [CaptureStatus.PROCESSED, CaptureStatus.NEEDS_CLARIFICATION]
                ),
            )
            .order_by(Capture.received_at.desc())
        )
        if recent is not None:
            return stored_result(recent)

    capture = Capture(
        user_id=user.id,
        client_capture_id=payload.client_capture_id,
        input_type=payload.input_type,
        raw_text=payload.content,
        transcript=payload.content if payload.input_type == "VOICE" else None,
        captured_at=min(payload.captured_at or now, now),
        received_at=now,
        processing_status=CaptureStatus.CAPTURED,
    )
    db.add(capture)
    try:
        db.commit()
    except IntegrityError:
        # The same entry arrived twice at once (offline queue and a retry); the other request has it.
        db.rollback()
        if payload.client_capture_id is None:
            raise
        existing = db.scalar(
            select(Capture).where(
                Capture.user_id == user.id, Capture.client_capture_id == payload.client_capture_id
            )
        )
        if existing is None:
            raise
        return stored_result(existing)
    return process_capture(db, user, capture, ai, clock)


def _fail(db: Session, capture: Capture, code: str, detail: str, started: float) -> CaptureResult:
    db.rollback()
    retryable = capture.attempts < MAX_ATTEMPTS
    capture.processing_status = CaptureStatus.FAILED
    capture.error_code = code
    capture.error_detail = detail[:2000]
    capture.processing_ms = round((time.perf_counter() - started) * 1000)
    capture.response_text = FAILURE_MESSAGE
    db.commit()
    return CaptureResult(
        capture=_info(capture),
        message=FAILURE_MESSAGE,
        error=ErrorOut(code=code, message=detail, retryable=retryable),
    )


def process_capture(
    db: Session, user: User, capture: Capture, ai: AIProvider | None, clock: Clock
) -> CaptureResult:
    started = time.perf_counter()
    if ai is None:
        return _fail(
            db,
            capture,
            "AI_NOT_CONFIGURED",
            "AI processing is switched off on this server.",
            started,
        )

    capture.processing_status = CaptureStatus.PROCESSING
    capture.attempts = (capture.attempts or 0) + 1
    capture.error_code = capture.error_detail = None
    db.commit()

    try:
        ctx = build_context(db, user, capture)
        extraction = ai.generate_structured(
            task="extraction",
            system=load_prompt("extraction", EXTRACTION_PROMPT_VERSION),
            user=render_user_prompt(ctx),
            output_model=ExtractionOutput,
        )
    except AIProviderError as exc:
        logger.warning("Extraction failed for capture %s: %s", capture.id, exc.code)
        return _fail(db, capture, exc.code, exc.message, started)
    except Exception:  # noqa: BLE001 - an unexpected SDK error must not strand the capture
        logger.exception("Extraction crashed for capture %s", capture.id)
        return _fail(
            db, capture, "AI_ERROR", "Something went wrong while understanding this.", started
        )

    output = extraction.output
    capture.model_provider = ai.name
    capture.model_name = extraction.model
    capture.extraction_version = EXTRACTION_VERSION
    capture.extraction_result = output.model_dump(mode="json")
    capture.language = (output.language or "")[:16] or None
    capture.intent = output.intent
    capture.ai_usage = extraction.usage

    try:
        plan = build_plan(db, ctx, output)
        applied = apply_plan(db, capture, plan, clock.now())
    except Exception:  # noqa: BLE001 - any failure here must leave the capture retryable
        logger.exception("Applying capture %s failed", capture.id)
        return _fail(
            db, capture, "PERSISTENCE_FAILED", "Something went wrong while saving.", started
        )

    answer = None
    if plan.question_text:
        try:
            result = answer_question(db, user, plan.question_text, ai, clock)
            answer = AnswerOut(text=result.text, evidence=result.evidence)
        except AIProviderError as exc:
            applied.warnings.append(f"I couldn't answer the question right now ({exc.code}).")

    response = _build_response(capture, applied, answer, user.timezone)
    capture.processing_status = (
        CaptureStatus.NEEDS_CLARIFICATION if applied.clarifications else CaptureStatus.PROCESSED
    )
    response.capture = _info(capture)
    capture.response_text = response.message
    capture.processed_at = clock.now()
    capture.processing_ms = round((time.perf_counter() - started) * 1000)
    capture.result = response.model_dump(mode="json")
    db.commit()
    return response


def _build_response(
    capture: Capture, applied: AppliedChanges, answer: AnswerOut | None, tz: str
) -> CaptureResult:
    return CaptureResult(
        capture=_info(capture),
        message=build_message(applied, question_answer=answer.text if answer else None),
        events_created=[to_summary(e, tz) for e in applied.created],
        events_updated=[
            EventChange(event=to_summary(e, tz), changes=changes) for e, changes in applied.updated
        ],
        events_deleted=[NamedRef(id=e.id, title=e.title) for e in applied.deleted],
        tasks_created=[
            TaskRef(id=t.id, title=t.title, due_date=t.due_date) for t in applied.tasks_created
        ],
        tasks_completed=[
            TaskRef(id=t.id, title=t.title, due_date=t.due_date) for t in applied.tasks_completed
        ],
        knowledge_created=[NamedRef(id=k.id, title=k.title) for k in applied.knowledge_created],
        clarifications=[clarification_out(c) for c in applied.clarifications],
        warnings=applied.warnings,
        answer=answer,
    )
