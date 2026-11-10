from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.analytics.review import WeeklyReview, weekly_review
from app.analytics.service import daily_summary
from app.auth.deps import get_current_user
from app.auth.models import User
from app.clock import Clock, get_clock
from app.core.timeutil import local_today
from app.db.session import get_db
from app.events.models import Event
from app.events.schemas import EntityRef, EventSummary
from app.events.service import like_pattern, search_condition, to_summary
from app.knowledge.models import Knowledge, KnowledgeAlias
from app.projects.models import Project, ProjectAlias
from app.tasks.models import Task

router = APIRouter(prefix="/v1", tags=["summary & search"])


@router.get("/summary/daily")
def summary_daily(
    day: date | None = Query(default=None, alias="date"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> dict[str, Any]:
    """Home screen data for one day: only sections backed by recorded events."""
    target = day or local_today(user.timezone, clock)
    summary = daily_summary(db, user.id, user.timezone, target)
    recent = db.scalars(
        select(Event)
        .where(Event.user_id == user.id, Event.deleted_at.is_(None), Event.occurred_on == target)
        .order_by(Event.sort_at.desc())
        .limit(6)
    )
    summary["recent_events"] = [
        to_summary(e, user.timezone).model_dump(mode="json") for e in recent
    ]
    return summary


@router.get("/review/weekly", response_model=WeeklyReview)
def review_weekly(
    week: date | None = Query(
        default=None, description="Any day in the week to review; this week by default."
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> WeeklyReview:
    """A week against last week and your 4-week average, with what stands out.

    Numbers come from your records and the observations from fixed rules, never from the AI.
    """
    today = local_today(user.timezone, clock)
    return weekly_review(db, user.id, user.week_start, today, week)


class SearchResults(BaseModel):
    events: list[EventSummary]
    projects: list[EntityRef]
    knowledge: list[EntityRef]
    tasks: list[EntityRef]


@router.get("/search", response_model=SearchResults)
def search(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SearchResults:
    pattern = like_pattern(q)
    events = db.scalars(
        select(Event)
        .where(Event.user_id == user.id, Event.deleted_at.is_(None), search_condition(q))
        .order_by(Event.occurred_on.desc(), Event.sort_at.desc())
        .limit(limit)
    )
    project_alias = select(ProjectAlias.project_id).where(
        ProjectAlias.alias.ilike(pattern, escape="\\")
    )
    projects = db.scalars(
        select(Project)
        .where(
            Project.user_id == user.id,
            Project.deleted_at.is_(None),
            or_(Project.name.ilike(pattern, escape="\\"), Project.id.in_(project_alias)),
        )
        .limit(limit)
    )
    knowledge_alias = select(KnowledgeAlias.knowledge_id).where(
        KnowledgeAlias.alias.ilike(pattern, escape="\\")
    )
    knowledge = db.scalars(
        select(Knowledge)
        .where(
            Knowledge.user_id == user.id,
            Knowledge.deleted_at.is_(None),
            or_(Knowledge.title.ilike(pattern, escape="\\"), Knowledge.id.in_(knowledge_alias)),
        )
        .limit(limit)
    )
    tasks = db.scalars(
        select(Task)
        .where(
            Task.user_id == user.id,
            Task.deleted_at.is_(None),
            Task.title.ilike(pattern, escape="\\"),
        )
        .limit(limit)
    )
    return SearchResults(
        events=[to_summary(e, user.timezone) for e in events],
        projects=[EntityRef(id=p.id, name=p.name) for p in projects],
        knowledge=[EntityRef(id=k.id, name=k.title) for k in knowledge],
        tasks=[EntityRef(id=t.id, name=t.title) for t in tasks],
    )
