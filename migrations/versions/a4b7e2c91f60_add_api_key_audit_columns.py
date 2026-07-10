"""add api key audit columns

Revision ID: a4b7e2c91f60
Revises: f2a9c3d81e40
Create Date: 2026-07-09 23:05:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "a4b7e2c91f60"
down_revision = "f2a9c3d81e40"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("key_prefix", sa.String(length=12), nullable=True)
        )
        batch_op.add_column(
            sa.Column("key_suffix", sa.String(length=8), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "request_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("expires_at", sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_column("expires_at")
        batch_op.drop_column("request_count")
        batch_op.drop_column("key_suffix")
        batch_op.drop_column("key_prefix")
