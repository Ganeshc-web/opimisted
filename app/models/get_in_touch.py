import uuid
from datetime import datetime, timezone

from app import db


class GetInTouchLead(db.Model):
    __tablename__ = "get_in_touch_leads"
    __table_args__ = (
        db.Index("ix_get_in_touch_leads_email", "email"),
        db.Index("ix_get_in_touch_leads_mobile", "mobile"),
    )

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    mobile = db.Column(db.String(15), nullable=False)
    message = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
