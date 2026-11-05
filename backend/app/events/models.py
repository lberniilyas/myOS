import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AmountPrecision,
    ChangeSource,
    CreatedBy,
    DayPeriod,
    DurationPrecision,
    EventType,
    HabitOutcome,
    LinkSource,
    RevisionChangeType,
    SourceType,
    TimePrecision,
)
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.goals.models import Goal
    from app.habits.models import Habit
    from app.knowledge.models import Knowledge
    from app.projects.models import Project
    from app.tasks.models import Task

SEARCH_DOCUMENT = (
    "to_tsvector('simple'::regconfig, "
    "coalesce(title, '') || ' ' || coalesce(description, '') || ' ' || coalesce(category, '')"
    " || ' ' || coalesce(structured_data->>'topic', '')"
    " || ' ' || coalesce(structured_data->>'output', ''))"
)


class Event(Base, TimestampMixin, SoftDeleteMixin):
    """Something that happened, was reported, or was observed: the core unit of the system."""

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="duration_non_negative"
        ),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency_iso"),
        CheckConstraint(
            "ended_at IS NULL OR occurred_at IS NULL OR ended_at >= occurred_at",
            name="end_after_start",
        ),
        CheckConstraint(
            "extraction_confidence IS NULL"
            " OR (extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_range",
        ),
        Index(
            "ix_events_timeline",
            "user_id",
            "occurred_on",
            "sort_at",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_events_user_type_day", "user_id", "event_type", "occurred_on"),
        Index("ix_events_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    area_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"))
    capture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("captures.id", ondelete="SET NULL"), index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL")
    )
    source_type: Mapped[SourceType] = mapped_column(str_enum(SourceType, "source_type"))
    created_by: Mapped[CreatedBy] = mapped_column(str_enum(CreatedBy, "created_by"))

    event_type: Mapped[EventType] = mapped_column(str_enum(EventType, "event_type"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64))

    # The local calendar day in the user's timezone; daily totals group on this.
    occurred_on: Mapped[date] = mapped_column(Date)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    time_precision: Mapped[TimePrecision] = mapped_column(str_enum(TimePrecision, "time_precision"))
    duration_precision: Mapped[DurationPrecision] = mapped_column(
        str_enum(DurationPrecision, "duration_precision")
    )
    day_period: Mapped[DayPeriod | None] = mapped_column(str_enum(DayPeriod, "day_period"))

    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    amount_precision: Mapped[AmountPrecision | None] = mapped_column(
        str_enum(AmountPrecision, "amount_precision")
    )

    structured_data: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # The exact words in the capture that support this event.
    evidence: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    extraction_version: Mapped[str | None] = mapped_column(String(32))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Timeline order: the start time when known, otherwise when it was recorded.
    sort_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), Computed("COALESCE(occurred_at, created_at)", persisted=True)
    )
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_DOCUMENT, persisted=True), deferred=True
    )

    project_links: Mapped[list["EventProject"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    goal_links: Mapped[list["EventGoal"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    knowledge_links: Mapped[list["EventKnowledge"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    task_links: Mapped[list["EventTask"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    habit_links: Mapped[list["EventHabit"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _link_source() -> Mapped[LinkSource]:
    return mapped_column(str_enum(LinkSource, "link_source"), default=LinkSource.AI)


class EventProject(Base):
    __tablename__ = "event_projects"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    link_source: Mapped[LinkSource] = _link_source()
    created_at: Mapped[datetime] = _created_at()

    project: Mapped["Project"] = relationship(lazy="joined")


class EventGoal(Base):
    __tablename__ = "event_goals"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    link_source: Mapped[LinkSource] = _link_source()
    created_at: Mapped[datetime] = _created_at()

    goal: Mapped["Goal"] = relationship(lazy="joined")


class EventKnowledge(Base):
    __tablename__ = "event_knowledge"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    link_source: Mapped[LinkSource] = _link_source()
    created_at: Mapped[datetime] = _created_at()

    knowledge: Mapped["Knowledge"] = relationship(lazy="joined")


class EventTask(Base):
    __tablename__ = "event_tasks"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    link_source: Mapped[LinkSource] = _link_source()
    created_at: Mapped[datetime] = _created_at()

    task: Mapped["Task"] = relationship(lazy="joined")


class EventHabit(Base):
    __tablename__ = "event_habits"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    habit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("habits.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    outcome: Mapped[HabitOutcome] = mapped_column(str_enum(HabitOutcome, "outcome"))
    link_source: Mapped[LinkSource] = _link_source()
    created_at: Mapped[datetime] = _created_at()

    habit: Mapped["Habit"] = relationship(lazy="joined")


class EventRevision(Base):
    """Audit trail: the event's state before and after every correction."""

    __tablename__ = "event_revisions"
    __table_args__ = (
        UniqueConstraint("event_id", "revision_number", name="uq_event_revisions_event_number"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    revision_number: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[RevisionChangeType] = mapped_column(
        str_enum(RevisionChangeType, "change_type")
    )
    change_source: Mapped[ChangeSource] = mapped_column(str_enum(ChangeSource, "change_source"))
    capture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("captures.id", ondelete="SET NULL")
    )
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()
