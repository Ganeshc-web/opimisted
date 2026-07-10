"""add report email daily count table

Revision ID: f2a9c3d81e40
Revises: e8f3a1b24c50
Create Date: 2026-07-09 22:40:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "f2a9c3d81e40"
down_revision = "e8f3a1b24c50"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_email_daily_count",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("day"),
    )


def downgrade():
    op.drop_table("report_email_daily_count")
