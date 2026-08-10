import uuid
from datetime import datetime, timezone

from app import db


class AssessmentRecord(db.Model):
    __tablename__ = "assessment_record"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = db.Column(db.String(50), default="in_progress")
    flow1_submitted_at = db.Column(db.DateTime, nullable=True)
    flow2_submitted_at = db.Column(db.DateTime, nullable=True)
    flow3_submitted_at = db.Column(db.DateTime, nullable=True)
    flow4_submitted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    communication = db.relationship("CommunicationDetails", uselist=False)
    personal = db.relationship("PersonalDetails", uselist=False)
    family = db.relationship("FamilyDetails", uselist=False)
    goals = db.relationship("Goal")
