import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.enums import (
    AmountPrecision,
    DayPeriod,
    DurationPrecision,
    EventType,
    HabitOutcome,
    SourceType,
    TimePrecision,
    UnderstandingState,
)


class EntityRef(BaseModel):
    id: uuid.UUID
    name: str


class KnowledgeRef(BaseModel):
    id: uuid.UUID
    title: str
    understanding_state: UnderstandingState


class HabitRef(BaseModel):
    id: uuid.UUID
    name: str
    outcome: HabitOutcome


class EventSummary(BaseModel):
    id: uuid.UUID
    event_type: EventType
    title: str
    category: str | None
    occurred_on: date
    occurred_at: datetime | None
    ended_at: datetime | None
    local_time: str | None = Field(description="Start time in the user's timezone, when known.")
    day_period: DayPeriod | None
    time_precision: TimePrecision
    duration_seconds: int | None
    duration_precision: DurationPrecision
    duration_display: str | None
    amount: Decimal | None
    currency: str | None
    amount_precision: AmountPrecision | None
    amount_display: str | None
    projects: list[EntityRef]
    source_type: SourceType
    capture_id: uuid.UUID | None
    created_at: datetime


class Provenance(BaseModel):
    source_type: SourceType
    created_by: str
    capture_id: uuid.UUID | None
    input_type: str | None
    captured_at: datetime | None
    evidence: str | None = Field(description="The exact words this event was extracted from.")
    extraction_confidence: float | None
    confidence_label: str | None
    extraction_version: str | None
    model_name: str | None


class EventDetail(EventSummary):
    description: str | None
    structured_data: dict
    area: EntityRef | None
    goals: list[EntityRef]
    knowledge: list[KnowledgeRef]
    tasks: list[EntityRef]
    habits: list[HabitRef]
    provenance: Provenance
    updated_at: datetime
    corrected_at: datetime | None
    deleted_at: datetime | None
    revision_count: int
    related_event_count: int


class TimelinePage(BaseModel):
    items: list[EventSummary]
    next_cursor: str | None


class EventCreate(BaseModel):
    """Manual, structured entry for when precision matters (spec #5 §35)."""

    event_type: EventType
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    category: str | None = Field(default=None, max_length=64)
    occurred_on: date | None = None
    occurred_at: datetime | None = None
    ended_at: datetime | None = None
    duration_minutes: float | None = Field(default=None, gt=0, le=24 * 60)
    duration_precision: DurationPrecision | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    amount_precision: AmountPrecision | None = None
    structured_data: dict = Field(default_factory=dict)
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    goal_ids: list[uuid.UUID] = Field(default_factory=list)
    knowledge_ids: list[uuid.UUID] = Field(default_factory=list)
    task_ids: list[uuid.UUID] = Field(default_factory=list)


class EventUpdate(BaseModel):
    event_type: EventType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    category: str | None = Field(default=None, max_length=64)
    occurred_on: date | None = None
    occurred_at: datetime | None = None
    ended_at: datetime | None = None
    duration_minutes: float | None = Field(default=None, gt=0, le=24 * 60)
    duration_precision: DurationPrecision | None = None
    time_precision: TimePrecision | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = None
    amount_precision: AmountPrecision | None = None
    structured_data: dict | None = None
    area_id: uuid.UUID | None = None
    project_ids: list[uuid.UUID] | None = None
    goal_ids: list[uuid.UUID] | None = None
    knowledge_ids: list[uuid.UUID] | None = None
    task_ids: list[uuid.UUID] | None = None


class CorrectionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class RevisionOut(BaseModel):
    id: uuid.UUID
    revision_number: int
    change_type: str
    change_source: str
    capture_id: uuid.UUID | None
    before: dict | None
    after: dict | None
    created_at: datetime
