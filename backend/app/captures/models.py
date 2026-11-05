import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    CaptureStatus,
    ClarificationKind,
    ClarificationStatus,
    InputType,
    SourceType,
)
from app.db.base import Base, TimestampMixin, str_enum, uuid_pk


class Source(Base, TimestampMixin):
    """A registered origin of automatically collected data (an iPhone automation, a PC agent...)."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[SourceType] = mapped_column(str_enum(SourceType, "source_type"))
    name: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(300))
    attributes: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class Capture(Base, TimestampMixin):
    """One user interaction (a typed message or a voice transcript): the provenance root."""

    __tablename__ = "captures"
    __table_args__ = (
        UniqueConstraint("user_id", "client_capture_id", name="uq_captures_user_client_capture_id"),
        Index("ix_captures_user_received_at", "user_id", "received_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    client_capture_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    input_type: Mapped[InputType] = mapped_column(str_enum(InputType, "input_type"))
    raw_text: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processing_status: Mapped[CaptureStatus] = mapped_column(
        str_enum(CaptureStatus, "processing_status"), default=CaptureStatus.CAPTURED
    )
    # Set when the capture was sent to correct one specific event.
    target_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    intent: Mapped[str | None] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    model_provider: Mapped[str | None] = mapped_column(String(50))
    model_name: Mapped[str | None] = mapped_column(String(100))
    extraction_version: Mapped[str | None] = mapped_column(String(32))
    extraction_result: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    response_text: Mapped[str | None] = mapped_column(Text)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    ai_usage: Mapped[dict | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def text(self) -> str:
        return self.transcript or self.raw_text or ""


class Clarification(Base):
    """An optional follow-up question attached to records that were already saved."""

    __tablename__ = "clarifications"
    __table_args__ = (Index("ix_clarifications_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    capture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("captures.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ClarificationKind] = mapped_column(str_enum(ClarificationKind, "kind"))
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[ClarificationStatus] = mapped_column(
        str_enum(ClarificationStatus, "status"), default=ClarificationStatus.OPEN
    )
    answer: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
