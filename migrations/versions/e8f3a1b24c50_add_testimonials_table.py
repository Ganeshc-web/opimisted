"""add testimonials table

Revision ID: e8f3a1b24c50
Revises: d7a2b4e81c90
Create Date: 2026-07-09 16:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "e8f3a1b24c50"
down_revision = "d7a2b4e81c90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "testimonials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_name", sa.String(length=120), nullable=False),
        sa.Column("review_message", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("testimonials")
