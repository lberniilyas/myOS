"""Personal access keys, for sending entries from an iPhone Shortcut or Siri.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "access_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("hint", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_access_keys_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_access_keys_key_hash")),
    )
    op.create_index(op.f("ix_access_keys_user_id"), "access_keys", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_access_keys_user_id"), table_name="access_keys")
    op.drop_table("access_keys")
