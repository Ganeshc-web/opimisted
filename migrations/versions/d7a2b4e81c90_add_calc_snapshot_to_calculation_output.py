"""add calc snapshot fields to calculation_output

Revision ID: d7a2b4e81c90
Revises: c4e8f1a92b30
Create Date: 2026-07-09 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "d7a2b4e81c90"
down_revision = "c4e8f1a92b30"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calculation_output", schema=None) as batch_op:
        batch_op.add_column(sa.Column("client_annual_ret_reqd", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("spouse_annual_ret_reqd", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("inflation_pre", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("roi_pre", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("inflation_post", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("roi_post", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("calculation_output", schema=None) as batch_op:
        batch_op.drop_column("roi_post")
        batch_op.drop_column("inflation_post")
        batch_op.drop_column("roi_pre")
        batch_op.drop_column("inflation_pre")
        batch_op.drop_column("spouse_annual_ret_reqd")
        batch_op.drop_column("client_annual_ret_reqd")
