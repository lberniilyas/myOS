import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.clock import Clock, get_clock
from app.core.enums import OPEN_TASK_STATUSES, TaskStatus
from app.db.queries import get_owned
from app.db.session import get_db
from app.events.schemas import EntityRef
from app.goals.models import Goal
from app.projects.models import Project
from app.tasks.models import Task
from app.tasks.schemas import TaskCreate, TaskOut, TaskUpdate

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


def to_out(db: Session, task: Task) -> TaskOut:
    project = db.get(Project, task.project_id) if task.project_id else None
    goal = db.get(Goal, task.goal_id) if task.goal_id else None
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        completed_at=task.completed_at,
        project=EntityRef(id=project.id, name=project.name) if project else None,
        goal=EntityRef(id=goal.id, name=goal.title) if goal else None,
        capture_id=task.capture_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _check_refs(db: Session, user: User, project_id, goal_id) -> None:
    if project_id:
        get_owned(db, Project, project_id, user.id, label="Project")
    if goal_id:
        get_owned(db, Goal, goal_id, user.id, label="Goal")


@router.get("", response_model=list[TaskOut])
def list_tasks(
    status: TaskStatus | None = Query(default=None),
    open_only: bool = Query(default=False),
    project_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    stmt = select(Task).where(Task.user_id == user.id, Task.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Task.status == status)
    if open_only:
        stmt = stmt.where(Task.status.in_(OPEN_TASK_STATUSES))
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    stmt = stmt.order_by(Task.due_date.nulls_last(), Task.created_at)
    return [to_out(db, task) for task in db.scalars(stmt)]


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> TaskOut:
    _check_refs(db, user, payload.project_id, payload.goal_id)
    task = Task(user_id=user.id, **payload.model_dump())
    task.title = task.title.strip()
    if task.status == TaskStatus.COMPLETED:
        task.completed_at = clock.now()
    db.add(task)
    db.commit()
    return to_out(db, task)


@router.get("/{task_id}", response_model=TaskOut)
def read_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> TaskOut:
    return to_out(db, get_owned(db, Task, task_id, user.id, label="Task"))


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> TaskOut:
    task = get_owned(db, Task, task_id, user.id, label="Task")
    changes = payload.model_dump(exclude_unset=True)
    _check_refs(db, user, changes.get("project_id"), changes.get("goal_id"))
    for field, value in changes.items():
        if field in ("title", "status") and value is None:
            continue
        setattr(task, field, value.strip() if field == "title" else value)
    if "status" in changes and changes["status"]:
        if task.status == TaskStatus.COMPLETED and task.completed_at is None:
            task.completed_at = clock.now()
        elif task.status != TaskStatus.COMPLETED:
            task.completed_at = None
    db.commit()
    return to_out(db, task)


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    task = get_owned(db, Task, task_id, user.id, label="Task")
    task.deleted_at = clock.now()
    db.commit()
    return Response(status_code=204)
