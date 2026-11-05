import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import UNDERSTANDING_RANK, KnowledgeType, UnderstandingState
from app.core.text import compact_key
from app.errors import ConflictError, ValidationFailedError
from app.events.models import Event, EventKnowledge
from app.knowledge.models import Knowledge, KnowledgeAlias


def find_by_key(db: Session, user_id: uuid.UUID, key: str) -> Knowledge | None:
    knowledge = db.scalar(
        select(Knowledge).where(
            Knowledge.user_id == user_id, Knowledge.title_key == key, Knowledge.deleted_at.is_(None)
        )
    )
    if knowledge is not None:
        return knowledge
    alias = db.scalar(
        select(KnowledgeAlias).where(
            KnowledgeAlias.user_id == user_id, KnowledgeAlias.alias_key == key
        )
    )
    if alias is not None and alias.knowledge.deleted_at is None:
        return alias.knowledge
    return None


def add_alias(db: Session, knowledge: Knowledge, alias: str) -> bool:
    """Attach an alias unless it is empty, redundant, or already names another item."""
    alias = alias.strip()
    key = compact_key(alias)
    if not key or key == knowledge.title_key:
        return False
    owner = find_by_key(db, knowledge.user_id, key)
    if owner is not None:
        return False
    knowledge.aliases.append(
        KnowledgeAlias(
            user_id=knowledge.user_id, knowledge_id=knowledge.id, alias=alias, alias_key=key
        )
    )
    db.flush()
    return True


def create_knowledge(
    db: Session,
    user_id: uuid.UUID,
    title: str,
    *,
    description: str | None = None,
    knowledge_type: KnowledgeType = KnowledgeType.CONCEPT,
    understanding: UnderstandingState = UnderstandingState.ENCOUNTERED,
    aliases: Iterable[str] = (),
    first_encountered_on: date | None = None,
    area_id: uuid.UUID | None = None,
) -> Knowledge:
    title = title.strip()
    key = compact_key(title)
    if not key:
        raise ValidationFailedError("The title needs at least one letter or digit.")
    if (existing := find_by_key(db, user_id, key)) is not None:
        raise ConflictError(
            f"'{title}' is already recorded as '{existing.title}'.", code="KNOWLEDGE_EXISTS"
        )
    knowledge = Knowledge(
        user_id=user_id,
        title=title,
        title_key=key,
        description=description,
        knowledge_type=knowledge_type,
        understanding_state=understanding,
        first_encountered_on=first_encountered_on,
        area_id=area_id,
    )
    db.add(knowledge)
    db.flush()
    for alias in aliases:
        add_alias(db, knowledge, alias)
    return knowledge


def raise_understanding(knowledge: Knowledge, state: UnderstandingState) -> bool:
    """Understanding only moves forward automatically; lowering it is the user's call."""
    if UNDERSTANDING_RANK[state] > UNDERSTANDING_RANK[knowledge.understanding_state]:
        knowledge.understanding_state = state
        return True
    return False


def evidence_stats(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, date | None]]:
    if not ids:
        return {}
    rows = db.execute(
        select(EventKnowledge.knowledge_id, func.count(Event.id), func.max(Event.occurred_on))
        .join(Event, Event.id == EventKnowledge.event_id)
        .where(EventKnowledge.knowledge_id.in_(ids), Event.deleted_at.is_(None))
        .group_by(EventKnowledge.knowledge_id)
    ).all()
    return {kid: (count, last) for kid, count, last in rows}
