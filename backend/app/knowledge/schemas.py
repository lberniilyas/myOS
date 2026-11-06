import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.enums import KnowledgeType, UnderstandingState
from app.core.fields import NonBlank
from app.events.schemas import EventSummary


class KnowledgeCreate(BaseModel):
    title: NonBlank = Field(max_length=300)
    description: str | None = None
    knowledge_type: KnowledgeType = KnowledgeType.CONCEPT
    understanding_state: UnderstandingState = UnderstandingState.ENCOUNTERED
    aliases: list[str] = Field(default_factory=list)


class KnowledgeUpdate(BaseModel):
    title: NonBlank | None = Field(default=None, max_length=300)
    description: str | None = None
    knowledge_type: KnowledgeType | None = None
    understanding_state: UnderstandingState | None = None
    add_aliases: list[str] = Field(default_factory=list)


class KnowledgeOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    knowledge_type: KnowledgeType
    understanding_state: UnderstandingState
    first_encountered_on: date | None
    aliases: list[str]
    evidence_count: int
    last_seen_on: date | None
    created_at: datetime


class KnowledgeDetail(KnowledgeOut):
    evidence: list[EventSummary]
