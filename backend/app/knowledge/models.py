import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import KnowledgeType, UnderstandingState
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, str_enum, uuid_pk


class Knowledge(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "knowledge"
    __table_args__ = (
        Index(
            "uq_knowledge_user_title_key",
            "user_id",
            "title_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    title_key: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    knowledge_type: Mapped[KnowledgeType] = mapped_column(
        str_enum(KnowledgeType, "knowledge_type"), default=KnowledgeType.CONCEPT
    )
    understanding_state: Mapped[UnderstandingState] = mapped_column(
        str_enum(UnderstandingState, "understanding_state"),
        default=UnderstandingState.ENCOUNTERED,
    )
    first_encountered_on: Mapped[date | None] = mapped_column(Date)

    aliases: Mapped[list["KnowledgeAlias"]] = relationship(
        back_populates="knowledge",
        cascade="all, delete-orphan",
        order_by="KnowledgeAlias.created_at",
        lazy="selectin",
    )


class KnowledgeAlias(Base):
    __tablename__ = "knowledge_aliases"
    __table_args__ = (
        UniqueConstraint("user_id", "alias_key", name="uq_knowledge_aliases_user_alias_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    knowledge_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(300))
    alias_key: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    knowledge: Mapped[Knowledge] = relationship(back_populates="aliases")
