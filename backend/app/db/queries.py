import uuid
from typing import TypeVar

from sqlalchemy.orm import Session

from app.errors import NotFoundError

T = TypeVar("T")


def get_owned(
    db: Session,
    model: type[T],
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    label: str,
    include_deleted: bool = False,
) -> T:
    """Fetch a row that belongs to the user; other users' rows look exactly like missing ones."""
    obj = db.get(model, entity_id)
    if obj is None or obj.user_id != user_id:
        raise NotFoundError(f"{label} not found.")
    if not include_deleted and getattr(obj, "deleted_at", None) is not None:
        raise NotFoundError(f"{label} not found.")
    return obj
