import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.enums import GoalStatus
from app.core.fields import NonBlank
from app.events.schemas import EntityRef, EventSummary


class GoalCreate(BaseModel):
    title: NonBlank = Field(max_length=300)
    description: str | None = None
    status: GoalStatus = GoalStatus.ACTIVE
    area_id: uuid.UUID | None = None
    parent_goal_id: uuid.UUID | None = None
    start_date: date | None = None
    target_date: date | None = None


class GoalUpdate(BaseModel):
    title: NonBlank | None = Field(default=None, max_length=300)
    description: str | None = None
    status: GoalStatus | None = None
    area_id: uuid.UUID | None = None
    parent_goal_id: uuid.UUID | None = None
    start_date: date | None = None
    target_date: date | None = None


class GoalOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: GoalStatus
    area_id: uuid.UUID | None
    parent_goal_id: uuid.UUID | None
    start_date: date | None
    target_date: date | None
    projects: list[EntityRef]
    created_at: datetime
    updated_at: datetime


class EvidenceTotal(BaseModel):
    event_type: str
    seconds: int
    display: str | None
    events: int


class GoalDetail(GoalOut):
    """Answers "am I actually moving toward this goal?" with recorded evidence (spec #2 §9)."""

    last_7_days: list[EvidenceTotal]
    last_30_days: list[EvidenceTotal]
    recent_evidence: list[EventSummary]
    open_task_count: int
