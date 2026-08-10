"""add provisions_made (PF+NPS+SA) to calculation_output

Revision ID: g8b2c4d91e50
Revises: c5d8e1f42a70
Create Date: 2026-07-18 14:05:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "g8b2c4d91e50"
down_revision = "c5d8e1f42a70"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("calculation_output", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "client_provisions_made",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "spouse_provisions_made",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade():
    with op.batch_alter_table("calculation_output", schema=None) as batch_op:
        batch_op.drop_column("spouse_provisions_made")
        batch_op.drop_column("client_provisions_made")
