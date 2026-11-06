import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.enums import TaskPriority, TaskStatus
from app.core.fields import NonBlank
from app.events.schemas import EntityRef


class TaskCreate(BaseModel):
    title: NonBlank = Field(max_length=500)
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority | None = None
    due_date: date | None = None
    project_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None


class TaskUpdate(BaseModel):
    title: NonBlank | None = Field(default=None, max_length=500)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: date | None = None
    project_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority | None
    due_date: date | None
    completed_at: datetime | None
    project: EntityRef | None
    goal: EntityRef | None
    capture_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
