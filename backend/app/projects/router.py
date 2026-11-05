import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.clock import Clock, get_clock
from app.core.enums import ProjectStatus
from app.core.timeutil import local_today
from app.db.queries import get_owned
from app.db.session import get_db
from app.projects import service
from app.projects.models import Project
from app.projects.schemas import (
    AliasCreate,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
)

router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    status: ProjectStatus | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectOut]:
    stmt = select(Project).where(Project.user_id == user.id, Project.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Project.status == status)
    return [service.to_out(p) for p in db.scalars(stmt.order_by(Project.name))]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProjectOut:
    return service.to_out(service.create_project(db, user, payload))


@router.get("/{project_id}", response_model=ProjectDetail)
def read_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ProjectDetail:
    project = get_owned(db, Project, project_id, user.id, label="Project")
    return service.to_detail(db, user, project, local_today(user.timezone, clock))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> ProjectOut:
    project = get_owned(db, Project, project_id, user.id, label="Project")
    return service.to_out(service.update_project(db, user, project, payload, clock.now()))


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    project = get_owned(db, Project, project_id, user.id, label="Project")
    service.delete_project(db, project, clock.now())
    return Response(status_code=204)


@router.post("/{project_id}/aliases", response_model=ProjectOut, status_code=201)
def add_alias(
    project_id: uuid.UUID,
    payload: AliasCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = get_owned(db, Project, project_id, user.id, label="Project")
    service.add_alias(db, user, project, payload.alias)
    db.commit()
    return service.to_out(project)


@router.delete("/{project_id}/aliases/{alias}", response_model=ProjectOut)
def remove_alias(
    project_id: uuid.UUID,
    alias: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = get_owned(db, Project, project_id, user.id, label="Project")
    service.remove_alias(db, project, alias)
    db.commit()
    return service.to_out(project)
