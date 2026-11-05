"""Build the minimum context the extraction model needs (spec #5 §6), with short refs.

The model only ever sees refs like p1 or e3, never database IDs, so it cannot point at a
record it wasn't shown.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.areas.models import Area
from app.auth.models import User
from app.captures.models import Capture
from app.core.enums import OPEN_TASK_STATUSES, CaptureStatus, GoalStatus, HabitFrequency
from app.core.formatting import format_amount, format_duration
from app.core.text import compact_key, normalize_phrase
from app.core.timeutil import zone_for
from app.events.models import Event
from app.goals.models import Goal
from app.habits.models import Habit
from app.knowledge.models import Knowledge
from app.projects.models import Project
from app.tasks.models import Task

LANGUAGE_NAMES = {"en": "English", "fr": "French", "ar": "Arabic"}
MAX_KNOWLEDGE = 50
MAX_RECENT_EVENTS = 25


@dataclass
class ExtractionContext:
    user: User
    capture: Capture
    now_local: datetime
    projects: dict[str, Project] = field(default_factory=dict)
    habits: dict[str, Habit] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)
    goals: dict[str, Goal] = field(default_factory=dict)
    areas: dict[str, Area] = field(default_factory=dict)
    knowledge: dict[str, Knowledge] = field(default_factory=dict)
    events: dict[str, Event] = field(default_factory=dict)
    recent_captures: list[tuple[Capture, list[str]]] = field(default_factory=list)
    target_event_ref: str | None = None

    def ref_of(self, mapping: dict, obj_id) -> str | None:
        return next((ref for ref, obj in mapping.items() if obj.id == obj_id), None)


def _numbered(prefix: str, items) -> dict:
    return {f"{prefix}{index}": item for index, item in enumerate(items, start=1)}


def _relevant_knowledge(db: Session, user: User, text: str) -> list[Knowledge]:
    items = list(
        db.scalars(
            select(Knowledge)
            .where(Knowledge.user_id == user.id, Knowledge.deleted_at.is_(None))
            .order_by(Knowledge.updated_at.desc())
            .limit(500)
        )
    )
    message_key = compact_key(text)
    message_words = {word for word in normalize_phrase(text).split() if len(word) >= 3}
    matched, recent = [], []
    for item in items:
        keys = [item.title_key] + [alias.alias_key for alias in item.aliases]
        words = set(normalize_phrase(item.title).split())
        if any(key and key in message_key for key in keys) or words & message_words:
            matched.append(item)
        elif len(recent) < 20:
            recent.append(item)
    return (matched + recent)[:MAX_KNOWLEDGE]


def build_context(db: Session, user: User, capture: Capture) -> ExtractionContext:
    now_local = capture.captured_at.astimezone(zone_for(user.timezone))
    ctx = ExtractionContext(user=user, capture=capture, now_local=now_local)

    projects = db.scalars(
        select(Project).where(Project.user_id == user.id, Project.deleted_at.is_(None))
    ).all()
    ctx.projects = _numbered(
        "p", sorted(projects, key=lambda p: (p.status != "ACTIVE", p.name.lower()))
    )
    ctx.habits = _numbered(
        "h",
        db.scalars(
            select(Habit)
            .where(Habit.user_id == user.id, Habit.archived_at.is_(None))
            .order_by(Habit.name)
        ),
    )
    ctx.tasks = _numbered(
        "t",
        db.scalars(
            select(Task)
            .where(
                Task.user_id == user.id,
                Task.deleted_at.is_(None),
                Task.status.in_(OPEN_TASK_STATUSES),
            )
            .order_by(Task.due_date.nulls_last(), Task.created_at.desc())
            .limit(40)
        ),
    )
    ctx.goals = _numbered(
        "g",
        db.scalars(
            select(Goal)
            .where(
                Goal.user_id == user.id, Goal.deleted_at.is_(None), Goal.status == GoalStatus.ACTIVE
            )
            .order_by(Goal.created_at)
        ),
    )
    ctx.areas = _numbered(
        "a",
        db.scalars(
            select(Area)
            .where(Area.user_id == user.id, Area.archived_at.is_(None))
            .order_by(Area.name)
        ),
    )
    ctx.knowledge = _numbered("k", _relevant_knowledge(db, user, capture.text))

    if capture.target_event_id is not None:
        target = db.get(Event, capture.target_event_id)
        events = [target] if target is not None and target.deleted_at is None else []
    else:
        since_day = now_local.date() - timedelta(days=1)
        events = list(
            db.scalars(
                select(Event)
                .where(
                    Event.user_id == user.id,
                    Event.deleted_at.is_(None),
                    (Event.occurred_on >= since_day)
                    | (Event.created_at >= capture.captured_at - timedelta(hours=12)),
                )
                .order_by(Event.created_at.desc())
                .limit(MAX_RECENT_EVENTS)
            )
        )
    ctx.events = _numbered("e", events)
    if capture.target_event_id is not None and events:
        ctx.target_event_ref = "e1"

    previous = db.scalars(
        select(Capture)
        .where(
            Capture.user_id == user.id,
            Capture.id != capture.id,
            Capture.captured_at >= capture.captured_at - timedelta(hours=6),
            Capture.captured_at <= capture.captured_at,
            Capture.processing_status.in_(
                [CaptureStatus.PROCESSED, CaptureStatus.NEEDS_CLARIFICATION]
            ),
        )
        .order_by(Capture.captured_at.desc())
        .limit(3)
    ).all()
    for prior in reversed(previous):
        refs = [ref for ref, event in ctx.events.items() if event.capture_id == prior.id]
        ctx.recent_captures.append((prior, refs))
    return ctx


def _event_line(ctx: ExtractionContext, ref: str, event: Event) -> str:
    when = event.occurred_on.isoformat()
    if event.occurred_at is not None:
        when += " " + event.occurred_at.astimezone(ctx.now_local.tzinfo).strftime("%H:%M")
    parts = [f"{ref}: {when}", event.event_type.value, f'"{event.title}"']
    if duration := format_duration(event.duration_seconds, event.duration_precision):
        parts.append(duration)
    if topic := (event.structured_data or {}).get("topic"):
        parts.append(f"topic {topic}")
    for link in event.project_links:
        parts.append(f"project {ctx.ref_of(ctx.projects, link.project_id) or link.project.name}")
    if amount := format_amount(event.amount, event.currency, event.amount_precision):
        parts.append(amount + (f" {event.category}" if event.category else ""))
    return "- " + " · ".join(parts)


def render_user_prompt(ctx: ExtractionContext) -> str:
    user = ctx.user
    lines = [
        "<context>",
        f"Current local time: {ctx.now_local:%A %Y-%m-%d %H:%M} ({user.timezone})",
        f"Write titles in: {LANGUAGE_NAMES.get(user.locale, 'English')}",
        f"Default currency: {user.default_currency or 'none set'}",
    ]

    def section(title: str, entries: list[str]) -> None:
        lines.append(f"\n{title}:")
        lines.extend(entries or ["- (none)"])

    section(
        "Projects",
        [
            f"- {ref}: {p.name} [{p.status.value}]"
            + (f" — also called: {', '.join(a.alias for a in p.aliases)}" if p.aliases else "")
            for ref, p in ctx.projects.items()
        ],
    )
    frequency = {
        HabitFrequency.DAILY: "day",
        HabitFrequency.WEEKLY: "week",
        HabitFrequency.MONTHLY: "month",
    }
    section(
        "Habits",
        [
            f"- {ref}: {h.name}"
            + (f" ({h.target_count} per {frequency[h.frequency]})" if h.target_count else "")
            for ref, h in ctx.habits.items()
        ],
    )
    section(
        "Open tasks",
        [
            f"- {ref}: {t.title}"
            + (f" (due {t.due_date.isoformat()})" if t.due_date else "")
            + (f" (project {ctx.ref_of(ctx.projects, t.project_id)})" if t.project_id else "")
            for ref, t in ctx.tasks.items()
        ],
    )
    section("Goals", [f"- {ref}: {g.title}" for ref, g in ctx.goals.items()])
    section("Life areas", [f"- {ref}: {a.name}" for ref, a in ctx.areas.items()])
    section(
        "Knowledge already recorded",
        [
            f"- {ref}: {k.title}"
            + (f" (also: {', '.join(a.alias for a in k.aliases)})" if k.aliases else "")
            + f" — {k.understanding_state.value.lower()}"
            for ref, k in ctx.knowledge.items()
        ],
    )
    section(
        "Recent events (newest first)", [_event_line(ctx, ref, e) for ref, e in ctx.events.items()]
    )
    section(
        "Recent messages (oldest first)",
        [
            f'- {c.captured_at.astimezone(ctx.now_local.tzinfo):%H:%M} "{c.text[:300]}"'
            + (f" → recorded {', '.join(refs)}" if refs else "")
            for c, refs in ctx.recent_captures
        ],
    )
    lines.append("</context>")
    if ctx.target_event_ref:
        lines += [
            "",
            "<correction_scope>",
            f"The person is correcting event {ctx.target_event_ref}. Treat the message as a correction "
            f"of {ctx.target_event_ref} unless it clearly describes something else.",
            "</correction_scope>",
        ]
    lines += ["", "<message>", ctx.capture.text, "</message>"]
    return "\n".join(lines)
