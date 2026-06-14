"""add retirement ages to personal details

Revision ID: bf50a285a4f1
Revises: 13ece6158a32
Create Date: 2026-06-14 19:21:38.668583

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bf50a285a4f1'
down_revision = '13ece6158a32'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('personal_details', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('client_retirement_age', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('spouse_retirement_age', sa.Integer(), nullable=True)
        )

    op.execute(
        "UPDATE personal_details SET client_retirement_age = 60 "
        "WHERE client_retirement_age IS NULL"
    )
    op.execute(
        "UPDATE personal_details SET spouse_retirement_age = 55 "
        "WHERE spouse_retirement_age IS NULL"
    )

    with op.batch_alter_table('personal_details', schema=None) as batch_op:
        batch_op.alter_column('client_retirement_age', nullable=False)
        batch_op.alter_column('spouse_retirement_age', nullable=False)


def downgrade():
    with op.batch_alter_table('personal_details', schema=None) as batch_op:
        batch_op.drop_column('spouse_retirement_age')
        batch_op.drop_column('client_retirement_age')
