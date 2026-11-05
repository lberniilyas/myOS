import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import TaskPriority, TaskStatus
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, str_enum, uuid_pk


class Task(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    goal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    capture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("captures.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        str_enum(TaskStatus, "task_status"), default=TaskStatus.TODO
    )
    priority: Mapped[TaskPriority | None] = mapped_column(str_enum(TaskPriority, "task_priority"))
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
