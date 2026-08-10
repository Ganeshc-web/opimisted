"""add get in touch leads table

Revision ID: a1f3c8e92d10
Revises: db08ccbfa999
Create Date: 2026-07-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a1f3c8e92d10"
down_revision = "db08ccbfa999"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "get_in_touch_leads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("mobile", sa.String(length=15), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("get_in_touch_leads", schema=None) as batch_op:
        batch_op.create_index("ix_get_in_touch_leads_email", ["email"], unique=False)
        batch_op.create_index("ix_get_in_touch_leads_mobile", ["mobile"], unique=False)


def downgrade():
    with op.batch_alter_table("get_in_touch_leads", schema=None) as batch_op:
        batch_op.drop_index("ix_get_in_touch_leads_mobile")
        batch_op.drop_index("ix_get_in_touch_leads_email")
    op.drop_table("get_in_touch_leads")
