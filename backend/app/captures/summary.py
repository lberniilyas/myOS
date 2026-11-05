"""The short reply after a capture (spec #5 §26): what was logged, in one sentence."""

from app.captures.apply import AppliedChanges
from app.core.enums import EventType, HabitOutcome
from app.core.formatting import format_amount, format_duration
from app.events.models import Event


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def describe(event: Event) -> str:
    duration = format_duration(event.duration_seconds, event.duration_precision)
    topic = (event.structured_data or {}).get("topic")
    project = event.project_links[0].project.name if event.project_links else None
    kind = event.event_type
    if kind == EventType.STUDY:
        subject = (
            f"{topic} study" if topic and "study" not in topic.lower() else topic or event.title
        )
        return f"{duration} {subject}" if duration else subject
    if kind == EventType.PROJECT_WORK:
        subject = f"{project} work" if project else event.title
        return f"{duration} {subject}" if duration else subject
    if kind in (EventType.EXPENSE, EventType.INCOME):
        amount = format_amount(event.amount, event.currency, event.amount_precision)
        noun = "expense" if kind == EventType.EXPENSE else "income"
        if not amount:
            return f"{event.title} ({noun}, amount unknown)"
        label = event.category or event.title.lower()
        return f"{amount} {noun}" if label == noun else f"{amount} {label} {noun}"
    if kind == EventType.KNOWLEDGE:
        titles = [link.knowledge.title for link in event.knowledge_links] or [event.title]
        return f"what you learned about {_join(titles)}"
    if event.habit_links:
        link = event.habit_links[0]
        state = "done" if link.outcome == HabitOutcome.COMPLETED else "missed"
        base = (
            f"{duration} {event.title}" if duration and kind == EventType.EXERCISE else event.title
        )
        return base if kind == EventType.EXERCISE else f"{link.habit.name} {state}"
    if kind == EventType.STATE:
        state = (event.structured_data or {}).get("state", {})
        return f"how you felt ({state.get('value', event.title)})"
    return f"{duration} {event.title}" if duration else event.title


def build_message(applied: AppliedChanges, *, question_answer: str | None = None) -> str:
    sentences = []
    if applied.created:
        sentences.append("Logged " + _join([describe(e) for e in applied.created]) + ".")
    for event, changes in applied.updated:
        what = _join(changes) if changes else "details"
        sentences.append(f"Updated {event.title} ({what}).")
    if applied.deleted:
        sentences.append("Removed " + _join([e.title for e in applied.deleted]) + ".")
    if applied.unchanged:
        sentences.append("Already had " + _join([e.title for e in applied.unchanged]) + ".")
    if applied.tasks_completed:
        sentences.append("Marked done: " + _join([t.title for t in applied.tasks_completed]) + ".")
    if applied.tasks_created:
        sentences.append(
            "Added to your tasks: " + _join([t.title for t in applied.tasks_created]) + "."
        )
    if question_answer:
        sentences.append(question_answer)
    if not sentences:
        sentences.append("I didn't find anything to record in that.")
    if applied.clarifications:
        sentences.append(applied.clarifications[0].question)
    return " ".join(sentences)
