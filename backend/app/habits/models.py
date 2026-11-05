import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import HabitFrequency, HabitStatus
from app.db.base import Base, TimestampMixin, str_enum, uuid_pk


class Habit(Base, TimestampMixin):
    __tablename__ = "habits"
    __table_args__ = (
        Index(
            "uq_habits_user_name_key",
            "user_id",
            "name_key",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        CheckConstraint("target_count IS NULL OR target_count > 0", name="target_count_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[HabitFrequency] = mapped_column(
        str_enum(HabitFrequency, "habit_frequency"), default=HabitFrequency.WEEKLY
    )
    target_count: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[HabitStatus] = mapped_column(
        str_enum(HabitStatus, "habit_status"), default=HabitStatus.ACTIVE
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
