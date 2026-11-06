import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.service import time_totals
from app.areas.models import Area
from app.auth.models import User
from app.core.enums import OPEN_TASK_STATUSES, ProjectStatus
from app.core.text import compact_key
from app.db.queries import get_owned
from app.errors import ConflictError, ValidationFailedError
from app.events.models import Event, EventKnowledge, EventProject
from app.events.schemas import EntityRef, KnowledgeRef
from app.events.service import to_summary
from app.goals.models import Goal
from app.knowledge.models import Knowledge
from app.projects.models import Project, ProjectAlias
from app.projects.schemas import (
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectStats,
    ProjectUpdate,
    TaskLite,
)
from app.tasks.models import Task


def _key_or_error(value: str, what: str) -> str:
    key = compact_key(value)
    if not key:
        raise ValidationFailedError(f"The {what} needs at least one letter or digit.")
    return key


def _name_owner(db: Session, user_id: uuid.UUID, key: str) -> Project | None:
    """The live project whose name or alias already uses this key, if any."""
    project = db.scalar(
        select(Project).where(
            Project.user_id == user_id, Project.name_key == key, Project.deleted_at.is_(None)
        )
    )
    if project is not None:
        return project
    alias = db.scalar(
        select(ProjectAlias).where(ProjectAlias.user_id == user_id, ProjectAlias.alias_key == key)
    )
    return alias.project if alias else None


def _goals(db: Session, user: User, goal_ids: list[uuid.UUID]) -> list[Goal]:
    return [get_owned(db, Goal, gid, user.id, label="Goal") for gid in dict.fromkeys(goal_ids)]


def create_project(db: Session, user: User, payload: ProjectCreate) -> Project:
    name = payload.name.strip()
    key = _key_or_error(name, "project name")
    if (owner := _name_owner(db, user.id, key)) is not None:
        raise ConflictError(
            f"'{name}' is already used by the project '{owner.name}'.", code="PROJECT_NAME_TAKEN"
        )
    if payload.area_id:
        get_owned(db, Area, payload.area_id, user.id, label="Area")
    if payload.parent_project_id:
        get_owned(db, Project, payload.parent_project_id, user.id, label="Parent project")
    project = Project(
        user_id=user.id,
        name=name,
        name_key=key,
        description=payload.description,
        status=payload.status,
        area_id=payload.area_id,
        parent_project_id=payload.parent_project_id,
        start_date=payload.start_date,
        target_date=payload.target_date,
        attributes={},
    )
    project.goals = _goals(db, user, payload.goal_ids)
    db.add(project)
    db.flush()
    for alias in payload.aliases:
        add_alias(db, user, project, alias)
    db.commit()
    return project


def add_alias(db: Session, user: User, project: Project, alias: str) -> ProjectAlias | None:
    alias = alias.strip()
    key = _key_or_error(alias, "alias")
    owner = _name_owner(db, user.id, key)
    if owner is not None:
        if owner.id == project.id:
            return None
        raise ConflictError(
            f"'{alias}' already refers to the project '{owner.name}'.", code="ALIAS_TAKEN"
        )
    entry = ProjectAlias(user_id=user.id, project_id=project.id, alias=alias, alias_key=key)
    project.aliases.append(entry)
    db.flush()
    return entry


def remove_alias(db: Session, project: Project, alias: str) -> None:
    key = compact_key(alias)
    project.aliases = [entry for entry in project.aliases if entry.alias_key != key]


def update_project(
    db: Session, user: User, project: Project, payload: ProjectUpdate, now: datetime
) -> Project:
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"]:
        name = changes["name"].strip()
        key = _key_or_error(name, "project name")
        owner = _name_owner(db, user.id, key)
        if owner is not None and owner.id != project.id:
            raise ConflictError(
                f"'{name}' is already used by the project '{owner.name}'.",
                code="PROJECT_NAME_TAKEN",
            )
        project.aliases = [entry for entry in project.aliases if entry.alias_key != key]
        project.name, project.name_key = name, key
    for field in ("description", "start_date", "target_date"):
        if field in changes:
            setattr(project, field, changes[field])
    if "area_id" in changes:
        if changes["area_id"]:
            get_owned(db, Area, changes["area_id"], user.id, label="Area")
        project.area_id = changes["area_id"]
    if "parent_project_id" in changes:
        parent_id = changes["parent_project_id"]
        if parent_id == project.id:
            raise ValidationFailedError("A project can't be its own parent.")
        if parent_id:
            parent = get_owned(db, Project, parent_id, user.id, label="Parent project")
            seen = set()
            while parent.parent_project_id is not None and parent.id not in seen:
                if parent.parent_project_id == project.id:
                    raise ValidationFailedError(
                        "A project can't sit under one of its own sub-projects."
                    )
                seen.add(parent.id)
                parent = db.get(Project, parent.parent_project_id)
        project.parent_project_id = parent_id
    if "status" in changes and changes["status"]:
        project.status = changes["status"]
        if project.status == ProjectStatus.COMPLETED and project.completed_at is None:
            project.completed_at = now
        elif project.status != ProjectStatus.COMPLETED:
            project.completed_at = None
    if "goal_ids" in changes and changes["goal_ids"] is not None:
        project.goals = _goals(db, user, changes["goal_ids"])
    db.commit()
    return project


def delete_project(db: Session, project: Project, now: datetime) -> None:
    """Soft delete. Past events keep their link; the name and aliases become free again."""
    project.deleted_at = now
    project.aliases = []
    db.commit()


def to_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        area_id=project.area_id,
        parent_project_id=project.parent_project_id,
        start_date=project.start_date,
        target_date=project.target_date,
        completed_at=project.completed_at,
        aliases=[entry.alias for entry in project.aliases],
        goals=[
            EntityRef(id=goal.id, name=goal.title)
            for goal in project.goals
            if goal.deleted_at is None
        ],
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def to_detail(db: Session, user: User, project: Project, today) -> ProjectDetail:
    def seconds_since(days: int | None) -> int:
        start = today - timedelta(days=days - 1) if days else None
        return time_totals(db, user.id, start=start, end=None, project_id=project.id)[0]["seconds"]

    total = time_totals(db, user.id, start=None, end=None, project_id=project.id)[0]
    linked = (
        select(Event)
        .join(EventProject, EventProject.event_id == Event.id)
        .where(
            EventProject.project_id == project.id,
            Event.user_id == user.id,
            Event.deleted_at.is_(None),
        )
    )
    recent = list(
        db.scalars(linked.order_by(Event.occurred_on.desc(), Event.sort_at.desc()).limit(10))
    )
    last_activity = db.scalar(
        select(func.max(Event.occurred_on))
        .join(EventProject, EventProject.event_id == Event.id)
        .where(EventProject.project_id == project.id, Event.deleted_at.is_(None))
    )
    open_tasks = db.scalars(
        select(Task)
        .where(
            Task.project_id == project.id,
            Task.deleted_at.is_(None),
            Task.status.in_(OPEN_TASK_STATUSES),
        )
        .order_by(Task.due_date.nulls_last(), Task.created_at)
    )
    knowledge = db.execute(
        select(Knowledge.id, Knowledge.title, Knowledge.understanding_state)
        .join(EventKnowledge, EventKnowledge.knowledge_id == Knowledge.id)
        .join(EventProject, EventProject.event_id == EventKnowledge.event_id)
        .join(Event, Event.id == EventKnowledge.event_id)
        .where(
            EventProject.project_id == project.id,
            Event.deleted_at.is_(None),
            Knowledge.deleted_at.is_(None),
        )
        .distinct()
    ).all()
    return ProjectDetail(
        **to_out(project).model_dump(),
        stats=ProjectStats(
            total_seconds=total["seconds"],
            total_display=total["display"],
            last_7_days_seconds=seconds_since(7),
            last_30_days_seconds=seconds_since(30),
            event_count=total["events"],
            last_activity_on=last_activity,
        ),
        open_tasks=[
            TaskLite(id=task.id, title=task.title, status=task.status, due_date=task.due_date)
            for task in open_tasks
        ],
        recent_events=[to_summary(event, user.timezone) for event in recent],
        knowledge=[
            KnowledgeRef(id=kid, title=title, understanding_state=state)
            for kid, title, state in knowledge
        ],
    )
