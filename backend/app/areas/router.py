import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.areas.models import Area
from app.auth.deps import get_current_user
from app.auth.models import User
from app.clock import Clock, get_clock
from app.core.text import compact_key
from app.db.queries import get_owned
from app.db.session import get_db
from app.errors import ConflictError, ValidationFailedError

router = APIRouter(prefix="/v1/areas", tags=["areas"])


class AreaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class AreaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class AreaOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


def _key(db: Session, user: User, name: str, area_id: uuid.UUID | None = None) -> str:
    key = compact_key(name)
    if not key:
        raise ValidationFailedError("The area name needs at least one letter or digit.")
    clash = db.scalar(
        select(Area).where(
            Area.user_id == user.id, Area.name_key == key, Area.archived_at.is_(None)
        )
    )
    if clash is not None and clash.id != area_id:
        raise ConflictError(f"You already have an area called '{clash.name}'.", code="AREA_EXISTS")
    return key


def _out(area: Area) -> AreaOut:
    return AreaOut(
        id=area.id, name=area.name, description=area.description, created_at=area.created_at
    )


@router.get("", response_model=list[AreaOut])
def list_areas(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[AreaOut]:
    stmt = (
        select(Area).where(Area.user_id == user.id, Area.archived_at.is_(None)).order_by(Area.name)
    )
    return [_out(area) for area in db.scalars(stmt)]


@router.post("", response_model=AreaOut, status_code=201)
def create_area(
    payload: AreaCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AreaOut:
    name = payload.name.strip()
    area = Area(
        user_id=user.id, name=name, name_key=_key(db, user, name), description=payload.description
    )
    db.add(area)
    db.commit()
    return _out(area)


@router.patch("/{area_id}", response_model=AreaOut)
def update_area(
    area_id: uuid.UUID,
    payload: AreaUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AreaOut:
    area = get_owned(db, Area, area_id, user.id, label="Area")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name"):
        area.name = changes["name"].strip()
        area.name_key = _key(db, user, area.name, area.id)
    if "description" in changes:
        area.description = changes["description"]
    db.commit()
    return _out(area)


@router.delete("/{area_id}", status_code=204)
def archive_area(
    area_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    area = get_owned(db, Area, area_id, user.id, label="Area")
    area.archived_at = clock.now()
    db.commit()
    return Response(status_code=204)
