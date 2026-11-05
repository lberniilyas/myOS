"""Deterministic duplicate scoring. It only ever triggers a question, never a silent merge."""

from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher

from app.core.enums import MONEY_EVENT_TYPES
from app.core.text import mention_key
from app.events.models import Event

ASK_THRESHOLD = 0.8


def _label(title: str, topic: str | None) -> str:
    return mention_key(f"{title} {topic or ''}")


def duplicate_score(
    *,
    event_type: str,
    title: str,
    topic: str | None,
    occurred_at: datetime | None,
    ended_at: datetime | None,
    duration_seconds: int | None,
    amount: Decimal | None,
    category: str | None,
    project_ids: set,
    existing: Event,
) -> float:
    """0..1 likelihood that a proposed event repeats an existing one on the same day."""
    if existing.event_type != event_type:
        return 0.0
    if occurred_at and existing.occurred_at:
        end = ended_at or occurred_at
        existing_end = existing.ended_at or existing.occurred_at
        if end < existing.occurred_at or existing_end < occurred_at:
            return 0.0
    existing_projects = {link.project_id for link in existing.project_links}
    if project_ids and existing_projects and not (project_ids & existing_projects):
        return 0.0
    similarity = SequenceMatcher(
        None,
        _label(title, topic),
        _label(existing.title, (existing.structured_data or {}).get("topic")),
    ).ratio()

    if event_type in MONEY_EVENT_TYPES:
        if amount is not None and existing.amount is not None and amount != existing.amount:
            return 0.0
        same_amount = amount is not None and amount == existing.amount
        same_category = category is not None and category == existing.category
        return 0.5 * same_amount + 0.3 * similarity + 0.2 * same_category

    if duration_seconds and existing.duration_seconds:
        longer = max(duration_seconds, existing.duration_seconds)
        gap = abs(duration_seconds - existing.duration_seconds) / longer
        if gap > 0.5:
            return 0.0
        duration_match = 1.0 if gap <= 0.2 else 0.5
    else:
        duration_match = 0.5
    project_match = 1.0 if project_ids == existing_projects else 0.5
    return 0.5 * similarity + 0.25 * duration_match + 0.25 * project_match
