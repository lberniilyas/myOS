from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider, AIProviderError, get_ai_provider
from app.assistant.service import answer_question
from app.auth.deps import get_current_user
from app.auth.models import User
from app.clock import Clock, get_clock
from app.db.session import get_db
from app.errors import AppError, ServiceUnavailableError

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


class AssistantQuery(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class AssistantResponse(BaseModel):
    answer: str
    evidence: list[dict[str, Any]]
    event_ids: list[str]


@router.post("/query", response_model=AssistantResponse)
def query(
    payload: AssistantQuery,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ai: AIProvider | None = Depends(get_ai_provider),
    clock: Clock = Depends(get_clock),
) -> AssistantResponse:
    if ai is None:
        raise ServiceUnavailableError(
            "AI is switched off on this server.", code="AI_NOT_CONFIGURED"
        )
    try:
        answer = answer_question(db, user, payload.message.strip(), ai, clock)
    except AIProviderError as exc:
        raise AppError(
            exc.message, code=exc.code, status_code=503 if exc.retryable else 502
        ) from exc
    return AssistantResponse(
        answer=answer.text, evidence=answer.evidence, event_ids=answer.event_ids
    )
