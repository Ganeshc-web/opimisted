"""add services table

Revision ID: h9c3d5e02f60
Revises: g8b2c4d91e50
Create Date: 2026-08-01 09:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "h9c3d5e02f60"
down_revision = "g8b2c4d91e50"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon_url", sa.String(length=500), nullable=True),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("services")
