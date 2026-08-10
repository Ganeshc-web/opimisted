import uuid
from datetime import datetime, timezone

from app import db


class EmailTemplate(db.Model):
    """Editable email copy used for automated sends (e.g. report delivery)."""

    __tablename__ = "email_templates"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_key = db.Column(db.String(80), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    body_plain = db.Column(db.Text, nullable=False)
    updated_by = db.Column(db.String(120), nullable=True)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
