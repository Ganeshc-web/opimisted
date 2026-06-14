import uuid
from datetime import datetime

from app import db


class Goal(db.Model):
    __tablename__ = "goals"

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = db.Column(
        db.Uuid(as_uuid=True), db.ForeignKey("assessment_record.id"), nullable=False
    )
    category = db.Column(db.String(50), nullable=False)
    goal_type = db.Column(db.String(100), nullable=False)
    child_id = db.Column(db.Uuid(as_uuid=True), db.ForeignKey("child.id"), nullable=True)
    target_year = db.Column(db.Integer, nullable=False)
    today_cost = db.Column(db.Float, nullable=False)
    inflation_rate = db.Column(db.Float, default=0.06)
    future_cost = db.Column(db.Float, nullable=True)
    monthly_sip = db.Column(db.Float, nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
