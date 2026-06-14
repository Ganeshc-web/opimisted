"""add child_id to goals

Revision ID: 355fbae41eae
Revises: bf50a285a4f1
Create Date: 2026-06-14 19:33:50.894207

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '355fbae41eae'
down_revision = 'bf50a285a4f1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('goals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('child_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            'fk_goals_child_id', 'child', ['child_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('goals', schema=None) as batch_op:
        batch_op.drop_constraint('fk_goals_child_id', type_='foreignkey')
        batch_op.drop_column('child_id')
