import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.clock import Clock, get_clock
from app.core.text import compact_key
from app.db.queries import get_owned
from app.db.session import get_db
from app.errors import ConflictError, ValidationFailedError
from app.events.models import Event, EventKnowledge
from app.events.service import to_summary
from app.knowledge import service
from app.knowledge.models import Knowledge, KnowledgeAlias
from app.knowledge.schemas import KnowledgeCreate, KnowledgeDetail, KnowledgeOut, KnowledgeUpdate

router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])


def _to_out(knowledge: Knowledge, stats: dict) -> KnowledgeOut:
    count, last_seen = stats.get(knowledge.id, (0, None))
    return KnowledgeOut(
        id=knowledge.id,
        title=knowledge.title,
        description=knowledge.description,
        knowledge_type=knowledge.knowledge_type,
        understanding_state=knowledge.understanding_state,
        first_encountered_on=knowledge.first_encountered_on,
        aliases=[alias.alias for alias in knowledge.aliases],
        evidence_count=count,
        last_seen_on=last_seen,
        created_at=knowledge.created_at,
    )


@router.get("", response_model=list[KnowledgeOut])
def list_knowledge(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeOut]:
    stmt = select(Knowledge).where(Knowledge.user_id == user.id, Knowledge.deleted_at.is_(None))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        alias_match = select(KnowledgeAlias.knowledge_id).where(KnowledgeAlias.alias.ilike(pattern))
        stmt = stmt.where(or_(Knowledge.title.ilike(pattern), Knowledge.id.in_(alias_match)))
    items = list(db.scalars(stmt.order_by(Knowledge.updated_at.desc()).limit(limit)))
    stats = service.evidence_stats(db, [k.id for k in items])
    return [_to_out(k, stats) for k in items]


@router.post("", response_model=KnowledgeOut, status_code=201)
def create_knowledge(
    payload: KnowledgeCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> KnowledgeOut:
    knowledge = service.create_knowledge(
        db,
        user.id,
        payload.title,
        description=payload.description,
        knowledge_type=payload.knowledge_type,
        understanding=payload.understanding_state,
        aliases=payload.aliases,
    )
    db.commit()
    return _to_out(knowledge, {})


@router.get("/{knowledge_id}", response_model=KnowledgeDetail)
def read_knowledge(
    knowledge_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> KnowledgeDetail:
    knowledge = get_owned(db, Knowledge, knowledge_id, user.id, label="Knowledge")
    events = list(
        db.scalars(
            select(Event)
            .join(EventKnowledge, EventKnowledge.event_id == Event.id)
            .where(EventKnowledge.knowledge_id == knowledge.id, Event.deleted_at.is_(None))
            .order_by(Event.occurred_on.desc(), Event.sort_at.desc())
            .limit(50)
        )
    )
    stats = service.evidence_stats(db, [knowledge.id])
    return KnowledgeDetail(
        **_to_out(knowledge, stats).model_dump(),
        evidence=[to_summary(event, user.timezone) for event in events],
    )


@router.patch("/{knowledge_id}", response_model=KnowledgeOut)
def update_knowledge(
    knowledge_id: uuid.UUID,
    payload: KnowledgeUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeOut:
    knowledge = get_owned(db, Knowledge, knowledge_id, user.id, label="Knowledge")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("title"):
        title = changes["title"].strip()
        key = compact_key(title)
        if not key:
            raise ValidationFailedError("The title needs at least one letter or digit.")
        owner = service.find_by_key(db, user.id, key)
        if owner is not None and owner.id != knowledge.id:
            raise ConflictError(
                f"'{title}' is already recorded as '{owner.title}'.", code="KNOWLEDGE_EXISTS"
            )
        knowledge.aliases = [a for a in knowledge.aliases if a.alias_key != key]
        knowledge.title, knowledge.title_key = title, key
    for field in ("description", "knowledge_type", "understanding_state"):
        if field in changes and not (field != "description" and changes[field] is None):
            setattr(knowledge, field, changes[field])
    for alias in payload.add_aliases:
        service.add_alias(db, knowledge, alias)
    db.commit()
    return _to_out(knowledge, service.evidence_stats(db, [knowledge.id]))


@router.delete("/{knowledge_id}", status_code=204)
def delete_knowledge(
    knowledge_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    clock: Clock = Depends(get_clock),
) -> Response:
    knowledge = get_owned(db, Knowledge, knowledge_id, user.id, label="Knowledge")
    knowledge.deleted_at = clock.now()
    knowledge.aliases = []
    db.commit()
    return Response(status_code=204)
