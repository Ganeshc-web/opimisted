import uuid
from datetime import datetime, timezone

from app import db


class Goal(db.Model):
    __tablename__ = "goals"
    __table_args__ = (
        db.Index("ix_goals_assessment_id", "assessment_id"),
    )

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("assessment_record.id"), nullable=False
    )
    category = db.Column(db.String(50), nullable=False)
    goal_type = db.Column(db.String(100), nullable=False)
    child_id = db.Column(db.Uuid(as_uuid=True), db.ForeignKey("child.id"), nullable=True)
    education_program_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("education_programs.id"), nullable=True
    )
    tour_destination_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("tour_destinations.id"), nullable=True
    )
    target_year = db.Column(db.Integer, nullable=False)
    today_cost = db.Column(db.Float, nullable=False)
    inflation_rate = db.Column(db.Float, default=0.06)
    future_cost = db.Column(db.Float, nullable=True)
    monthly_sip = db.Column(db.Float, nullable=True)
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
