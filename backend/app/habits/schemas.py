import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.enums import HabitFrequency, HabitOutcome, HabitStatus


class HabitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    frequency: HabitFrequency = HabitFrequency.WEEKLY
    target_count: int | None = Field(default=None, gt=0, le=1000)
    area_id: uuid.UUID | None = None


class HabitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    frequency: HabitFrequency | None = None
    target_count: int | None = Field(default=None, gt=0, le=1000)
    status: HabitStatus | None = None
    area_id: uuid.UUID | None = None


class HabitOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    frequency: HabitFrequency
    target_count: int | None
    status: HabitStatus
    area_id: uuid.UUID | None
    created_at: datetime


class HabitPeriod(BaseModel):
    start: date
    end: date
    completed: int
    missed: int
    target_count: int | None


class HabitOccurrence(BaseModel):
    event_id: uuid.UUID
    occurred_on: date
    title: str
    outcome: HabitOutcome


class HabitDetail(HabitOut):
    current_period: HabitPeriod
    recent: list[HabitOccurrence]
