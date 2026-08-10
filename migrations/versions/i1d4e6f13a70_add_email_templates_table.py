"""add email_templates table for admin-editable report mail copy

Revision ID: i1d4e6f13a70
Revises: h9c3d5e02f60
Create Date: 2026-08-02 15:20:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "i1d4e6f13a70"
down_revision = "h9c3d5e02f60"
branch_labels = None
depends_on = None


DEFAULT_SUBJECT = "Your Wealth Wisdom Goal Analysis Report is Ready"

DEFAULT_BODY = """Hello {{client_name}},

Greetings from Wealth Wisdom.

Thank you for trusting us with your financial goals. We are glad to share that your personalized Goal Analysis Report is ready.

Please find your report attached ({{attachment_name}}). It covers your goals, suggested investment directions, and planning insights based on the details you shared with us.

We hope this report helps you take the next step with clarity and confidence.

If you have any questions, feel free to reply to this email or write to us at info@wealthswisdom.com - we are happy to help.

Warm regards,
Team Wealth Wisdom
https://wealthswisdom.com
"""


def upgrade():
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("body_plain", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key"),
    )

    email_templates = sa.table(
        "email_templates",
        sa.column("id", sa.Uuid()),
        sa.column("template_key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("subject", sa.String()),
        sa.column("body_html", sa.Text()),
        sa.column("body_plain", sa.Text()),
        sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        email_templates,
        [
            {
                "id": uuid.uuid4(),
                "template_key": "report_delivery",
                "name": "Report delivery",
                "subject": DEFAULT_SUBJECT,
                "body_html": DEFAULT_BODY,
                "body_plain": DEFAULT_BODY,
                "updated_by": "system",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade():
    op.drop_table("email_templates")
