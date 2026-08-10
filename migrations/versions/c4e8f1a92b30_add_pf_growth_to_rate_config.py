"""add pf_growth to rate_config

Revision ID: c4e8f1a92b30
Revises: a1f3c8e92d10
Create Date: 2026-07-07 12:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "c4e8f1a92b30"
down_revision = "a1f3c8e92d10"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("rate_config", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("pf_growth", sa.Float(), nullable=False, server_default="0.05")
        )


def downgrade():
    with op.batch_alter_table("rate_config", schema=None) as batch_op:
        batch_op.drop_column("pf_growth")
