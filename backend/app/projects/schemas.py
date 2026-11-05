import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.enums import ProjectStatus, TaskStatus
from app.events.schemas import EntityRef, EventSummary, KnowledgeRef


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    area_id: uuid.UUID | None = None
    parent_project_id: uuid.UUID | None = None
    start_date: date | None = None
    target_date: date | None = None
    aliases: list[str] = Field(default_factory=list)
    goal_ids: list[uuid.UUID] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ProjectStatus | None = None
    area_id: uuid.UUID | None = None
    parent_project_id: uuid.UUID | None = None
    start_date: date | None = None
    target_date: date | None = None
    goal_ids: list[uuid.UUID] | None = None


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: ProjectStatus
    area_id: uuid.UUID | None
    parent_project_id: uuid.UUID | None
    start_date: date | None
    target_date: date | None
    completed_at: datetime | None
    aliases: list[str]
    goals: list[EntityRef]
    created_at: datetime
    updated_at: datetime


class ProjectStats(BaseModel):
    total_seconds: int
    total_display: str | None
    last_7_days_seconds: int
    last_30_days_seconds: int
    event_count: int
    last_activity_on: date | None


class TaskLite(BaseModel):
    id: uuid.UUID
    title: str
    status: TaskStatus
    due_date: date | None


class ProjectDetail(ProjectOut):
    stats: ProjectStats
    open_tasks: list[TaskLite]
    recent_events: list[EventSummary]
    knowledge: list[KnowledgeRef]
