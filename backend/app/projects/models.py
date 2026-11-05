import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ProjectStatus
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.goals.models import Goal

project_goals = Table(
    "project_goals",
    Base.metadata,
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("goal_id", ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True),
)


class Project(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "uq_projects_user_name_key",
            "user_id",
            "name_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"))
    parent_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        str_enum(ProjectStatus, "project_status"), default=ProjectStatus.ACTIVE
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attributes: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )

    aliases: Mapped[list["ProjectAlias"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectAlias.created_at",
        lazy="selectin",
    )
    goals: Mapped[list["Goal"]] = relationship(secondary=project_goals, lazy="selectin")


class ProjectAlias(Base):
    __tablename__ = "project_aliases"
    __table_args__ = (
        UniqueConstraint("user_id", "alias_key", name="uq_project_aliases_user_alias_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(200))
    alias_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="aliases")
