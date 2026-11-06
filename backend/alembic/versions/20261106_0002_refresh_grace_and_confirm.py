"""Keep the replaced refresh token for one rotation; allow CONFIRM questions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
    "PROJECT_CHOICE",
    "CREATE_PROJECT",
    "DURATION",
    "EXPENSE_CATEGORY",
    "AMOUNT",
    "DUPLICATE",
    "CORRECTION_TARGET",
    "DATE",
)


def _kind_check(kinds: Sequence[str]) -> str:
    return "kind IN (" + ", ".join(f"'{kind}'" for kind in kinds) + ")"


def upgrade() -> None:
    op.add_column(
        "auth_sessions",
        sa.Column("previous_refresh_token_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_auth_sessions_previous_refresh_token_hash"),
        "auth_sessions",
        ["previous_refresh_token_hash"],
        unique=False,
    )
    op.drop_constraint(op.f("ck_clarifications_kind"), "clarifications", type_="check")
    op.create_check_constraint(
        op.f("ck_clarifications_kind"), "clarifications", _kind_check((*KINDS, "CONFIRM"))
    )


def downgrade() -> None:
    op.execute("DELETE FROM clarifications WHERE kind = 'CONFIRM'")
    op.drop_constraint(op.f("ck_clarifications_kind"), "clarifications", type_="check")
    op.create_check_constraint(op.f("ck_clarifications_kind"), "clarifications", _kind_check(KINDS))
    op.drop_index(op.f("ix_auth_sessions_previous_refresh_token_hash"), table_name="auth_sessions")
    op.drop_column("auth_sessions", "previous_refresh_token_hash")
