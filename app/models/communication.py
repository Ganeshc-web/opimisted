import uuid
from datetime import datetime, timezone

from app import db


class CommunicationDetails(db.Model):
    __tablename__ = "communication_details"
    __table_args__ = (
        db.Index("ix_communication_details_assessment_id", "assessment_id"),
    )

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("assessment_record.id"), nullable=False
    )
    mobile = db.Column(db.String(15), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    spouse_mobile = db.Column(db.String(15), nullable=True)
    spouse_email = db.Column(db.String(120), nullable=True)
    residential_address = db.Column(db.Text, nullable=True)
    consent = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
