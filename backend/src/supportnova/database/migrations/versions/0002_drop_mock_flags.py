"""drop the development-mock flags - every stored AI output now comes from the configured model

Revision ID: 0002_drop_mock_flags
Revises: 0001_initial
Create Date: 2026-09-24 10:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002_drop_mock_flags'
down_revision: str | None = '0001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (('complaints', 'is_mock_analysis'), ('analyses', 'is_mock'), ('ai_runs', 'is_mock'),
           ('customer_responses', 'is_mock'), ('evaluation_runs', 'is_mock'))


def upgrade() -> None:
    for table, column in COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)


def downgrade() -> None:
    for table, column in COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()))
