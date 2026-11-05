import uuid
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.areas.models import Area
from app.auth.deps import get_current_user
from app.auth.models import User
from app.clock import Clock, get_clock
from app.core.enums import OPEN_TASK_STATUSES, DurationPrecision, GoalStatus
from app.core.formatting import format_duration
from app.core.timeutil import local_today
from app.db.queries import get_owned
from app.db.session import get_db
from app.errors import ValidationFailedError
from app.events.models import Event, EventGoal, EventProject
from app.events.schemas import EntityRef
from app.events.service import to_summary
from app.goals.models import Goal
from app.goals.schemas import EvidenceTotal, GoalCreate, GoalDetail, GoalOut, GoalUpdate
from app.projects.models import Project, project_goals
from app.tasks.models import Task

router = APIRouter(prefix="/v1/goals", tags=["goals"])


def _projects_of(db: Session, goal: Goal) -> list[Project]:
    return list(
        db.scalars(
            select(Project)
            .join(project_goals, project_goals.c.project_id == Project.id)
            .where(project_goals.c.goal_id == goal.id, Project.deleted_at.is_(None))
            .order_by(Project.name)
        )
    )


def _to_out(db: Session, goal: Goal) -> GoalOut:
    return GoalOut(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        status=goal.status,
        area_id=goal.area_id,
        parent_goal_id=goal.parent_goal_id,
        start_date=goal.start_date,
        target_date=goal.target_date,
        projects=[EntityRef(id=p.id, name=p.name) for p in _projects_of(db, goal)],
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


def _check_refs(db: Session, user: User, area_id, parent_goal_id, goal_id=None) -> None:
    if area_id:
        get_owned(db, Area, area_id, user.id, label="Area")
    if parent_goal_id:
        if parent_goal_id == goal_id:
            raise ValidationFailedError("A goal can't be its own parent.")
        get_owned(db, Goal, parent_goal_id, user.id, label="Parent goal")


@router.get("", response_model=list[GoalOut])
def list_goals(
    status: GoalStatus | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GoalOut]:
    stmt = select(Goal).where(Goal.user_id == user.id, Goal.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Goal.status == status)
    return [_to_out(db, goal) for goal in db.scalars(stmt.order_by(Goal.created_at))]


@router.post("", response_model=GoalOut, status_code=201)
def create_goal(
    payload: GoalCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> GoalOut:
    _check_refs(db, user, payload.area_id, payload.parent_goal_id)
    goal = Goal(user_id=user.id, **payload.model_dump())
    goal.title = goal.title.strip()
    db.add(goal)
    db.commit()
    return _to_out(db, goal)


@router.get("/{goal_id}", response_model=GoalDetail)
def read_goal(
    goal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> GoalDetail:
    goal = get_owned(db, Goal, goal_id, user.id, label="Goal")
    today = local_today(user.timezone, clock)
    project_ids = [p.id for p in _projects_of(db, goal)]
    evidence = or_(
        exists().where(EventGoal.event_id == Event.id, EventGoal.goal_id == goal.id),
        exists().where(EventProject.event_id == Event.id, EventProject.project_id.in_(project_ids))
        if project_ids
        else False,
    )
    base = select(Event).where(Event.user_id == user.id, Event.deleted_at.is_(None), evidence)
    recent_30 = list(db.scalars(base.where(Event.occurred_on >= today - timedelta(days=29))))

    def totals(events: list[Event]) -> list[EvidenceTotal]:
        seconds: dict[str, int] = defaultdict(int)
        counts: dict[str, int] = defaultdict(int)
        approximate: dict[str, bool] = defaultdict(bool)
        for event in events:
            key = event.event_type.value
            counts[key] += 1
            seconds[key] += event.duration_seconds or 0
            approximate[key] |= event.duration_precision == DurationPrecision.APPROXIMATE
        return [
            EvidenceTotal(
                event_type=key,
                seconds=seconds[key],
                display=format_duration(
                    seconds[key],
                    DurationPrecision.APPROXIMATE if approximate[key] else DurationPrecision.EXACT,
                )
                if seconds[key]
                else None,
                events=counts[key],
            )
            for key in sorted(counts)
        ]

    week_start = today - timedelta(days=6)
    recent = list(
        db.scalars(base.order_by(Event.occurred_on.desc(), Event.sort_at.desc()).limit(10))
    )
    open_tasks = db.scalar(
        select(func.count(Task.id)).where(
            Task.user_id == user.id,
            Task.deleted_at.is_(None),
            Task.status.in_(OPEN_TASK_STATUSES),
            or_(
                Task.goal_id == goal.id, Task.project_id.in_(project_ids) if project_ids else False
            ),
        )
    )
    return GoalDetail(
        **_to_out(db, goal).model_dump(),
        last_7_days=totals([e for e in recent_30 if e.occurred_on >= week_start]),
        last_30_days=totals(recent_30),
        recent_evidence=[to_summary(event, user.timezone) for event in recent],
        open_task_count=open_tasks or 0,
    )


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(
    goal_id: uuid.UUID,
    payload: GoalUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GoalOut:
    goal = get_owned(db, Goal, goal_id, user.id, label="Goal")
    changes = payload.model_dump(exclude_unset=True)
    _check_refs(db, user, changes.get("area_id"), changes.get("parent_goal_id"), goal.id)
    for field, value in changes.items():
        if field in ("title", "status") and value is None:
            continue
        setattr(goal, field, value.strip() if field == "title" else value)
    db.commit()
    return _to_out(db, goal)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(
    goal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    goal = get_owned(db, Goal, goal_id, user.id, label="Goal")
    goal.deleted_at = clock.now()
    db.commit()
    return Response(status_code=204)
