import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.enums import CaptureStatus, ClarificationKind, ClarificationStatus, InputType
from app.events.schemas import EventSummary


class CaptureCreate(BaseModel):
    input_type: Literal[InputType.TEXT, InputType.VOICE] = InputType.TEXT
    content: str = Field(
        min_length=1, max_length=10000, description="Typed text, or a voice transcript."
    )
    client_capture_id: uuid.UUID | None = Field(
        default=None,
        description="Generated on the device; resending the same id never creates duplicates.",
    )
    captured_at: datetime | None = Field(
        default=None, description="When the user made the capture (with offset)."
    )

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Say or type something first.")
        return value.strip()

    @field_validator("captured_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("captured_at needs a timezone offset.")
        return value


class ClarificationOut(BaseModel):
    id: uuid.UUID
    kind: ClarificationKind
    question: str
    options: list[dict[str, Any]]
    answer_type: Literal["choice", "amount"]
    event_id: uuid.UUID | None
    capture_id: uuid.UUID
    status: ClarificationStatus
    created_at: datetime


class ClarificationAnswer(BaseModel):
    option_id: str | None = None
    value: str | None = Field(
        default=None, max_length=100, description="Free answer, e.g. an amount."
    )


class EventChange(BaseModel):
    event: EventSummary
    changes: list[str]


class NamedRef(BaseModel):
    id: uuid.UUID
    title: str


class TaskRef(BaseModel):
    id: uuid.UUID
    title: str
    due_date: Any = None


class CaptureInfo(BaseModel):
    id: uuid.UUID
    status: CaptureStatus
    input_type: InputType
    captured_at: datetime
    intent: str | None
    language: str | None


class AnswerOut(BaseModel):
    text: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class ErrorOut(BaseModel):
    code: str
    message: str
    retryable: bool = False


class CaptureResult(BaseModel):
    capture: CaptureInfo
    message: str
    events_created: list[EventSummary] = Field(default_factory=list)
    events_updated: list[EventChange] = Field(default_factory=list)
    events_deleted: list[NamedRef] = Field(default_factory=list)
    tasks_created: list[TaskRef] = Field(default_factory=list)
    tasks_completed: list[TaskRef] = Field(default_factory=list)
    knowledge_created: list[NamedRef] = Field(default_factory=list)
    clarifications: list[ClarificationOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    answer: AnswerOut | None = None
    error: ErrorOut | None = None


class CaptureListItem(BaseModel):
    id: uuid.UUID
    status: CaptureStatus
    input_type: InputType
    text: str | None
    captured_at: datetime
    response_text: str | None
    error_code: str | None
