"""Full export of everything the system stores about one user (principle 11: export your data)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.areas.models import Area
from app.auth.models import User
from app.captures.models import Capture, Clarification, Source
from app.events.models import (
    Event,
    EventGoal,
    EventHabit,
    EventKnowledge,
    EventProject,
    EventRevision,
    EventTask,
)
from app.goals.models import Goal
from app.habits.models import Habit
from app.knowledge.models import Knowledge, KnowledgeAlias
from app.projects.models import Project, ProjectAlias, project_goals
from app.tasks.models import Task

_EXCLUDED = {"password_hash", "search_vector"}


def _plain(value: object) -> object:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _row(obj: object) -> dict:
    mapper = inspect(obj).mapper
    return {
        attr.key: _plain(getattr(obj, attr.key))
        for attr in mapper.column_attrs
        if attr.key not in _EXCLUDED
    }


def export_user_data(db: Session, user: User) -> dict:
    def owned(model: type) -> list[dict]:
        return [_row(obj) for obj in db.scalars(select(model).where(model.user_id == user.id))]

    event_ids = select(Event.id).where(Event.user_id == user.id)

    def links(model: type) -> list[dict]:
        return [_row(obj) for obj in db.scalars(select(model).where(model.event_id.in_(event_ids)))]

    project_ids = select(Project.id).where(Project.user_id == user.id)
    project_goal_rows = db.execute(
        select(project_goals).where(project_goals.c.project_id.in_(project_ids))
    ).mappings()

    return {
        "format": "personal-os-export",
        "version": 1,
        "user": _row(user),
        "areas": owned(Area),
        "goals": owned(Goal),
        "projects": owned(Project),
        "project_aliases": owned(ProjectAlias),
        "project_goals": [{k: _plain(v) for k, v in row.items()} for row in project_goal_rows],
        "habits": owned(Habit),
        "tasks": owned(Task),
        "knowledge": owned(Knowledge),
        "knowledge_aliases": owned(KnowledgeAlias),
        "sources": owned(Source),
        "captures": owned(Capture),
        "events": owned(Event),
        "event_projects": links(EventProject),
        "event_goals": links(EventGoal),
        "event_knowledge": links(EventKnowledge),
        "event_tasks": links(EventTask),
        "event_habits": links(EventHabit),
        "event_revisions": owned(EventRevision),
        "clarifications": owned(Clarification),
    }
