"""add insurance snapshot and institution_name

Revision ID: c5d8e1f42a70
Revises: a4b7e2c91f60
Create Date: 2026-07-10 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c5d8e1f42a70"
down_revision = "a4b7e2c91f60"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calculation_output", schema=None) as batch_op:
        batch_op.add_column(sa.Column("household_monthly", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("insurance_items", sa.JSON(), nullable=True))

    with op.batch_alter_table("education_programs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("institution_name", sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table("education_programs", schema=None) as batch_op:
        batch_op.drop_column("institution_name")

    with op.batch_alter_table("calculation_output", schema=None) as batch_op:
        batch_op.drop_column("insurance_items")
        batch_op.drop_column("household_monthly")
